"""
dashboard.py — Web Service standalone para Render.
El pool asyncpg se inicializa dentro del worker con before_request,
porque on_starting corre en el master y los workers no heredan el loop.
"""
import os
import asyncio
import threading
import io
import json
import asyncpg
from PIL import Image, UnidentifiedImageError

from flask import Flask, jsonify, request, send_from_directory, Response
from functools import wraps
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

# Contrato compartido con el bot, mantenido como archivo independiente.
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "dashboard_schema.sql")
with open(SCHEMA_PATH, encoding="utf-8") as schema_file:
    ABO_SCHEMA = schema_file.read()

load_dotenv()

DATABASE_URL     = os.getenv("DATABASE_URL", "")
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "")
PORT             = int(os.getenv("PORT", "10000"))
MAX_IMAGE_BYTES  = 5 * 1024 * 1024

app = Flask(__name__, static_folder="dashboard_static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES + 64 * 1024  # margen para multipart/form-data
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

_pool = None
_loop = None
_initialized = False
_init_lock = threading.Lock()


def _normalize_dsn(dsn):
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    p = urlsplit(dsn)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if k.lower() != "channel_binding"]
    if not any(k.lower() == "sslmode" for k, _ in q):
        q.append(("sslmode", "require"))
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))


def _run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _ensure_initialized():
    """Inicializa el loop y el pool la primera vez que llega un request al worker."""
    global _pool, _loop, _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        loop = asyncio.new_event_loop()
        _loop = loop
        t = threading.Thread(target=_run_loop, args=(loop,), daemon=True)
        t.start()
        future = asyncio.run_coroutine_threadsafe(_init_pool_inner(), loop)
        future.result(timeout=20)
        _initialized = True
        print("[Abo Dashboard] Pool de Neon listo en worker ✅")


async def _init_pool_inner():
    global _pool
    if not DATABASE_URL:
        raise RuntimeError("Falta DATABASE_URL para iniciar el dashboard")
    _pool = await asyncpg.create_pool(
        dsn=_normalize_dsn(DATABASE_URL),
        ssl="require",
        min_size=1, max_size=4,
        command_timeout=20,
        statement_cache_size=0,
    )
    async with _pool.acquire() as connection:
        await connection.execute(ABO_SCHEMA)
        await connection.execute("""CREATE TABLE IF NOT EXISTS dashboard_uploads (
            guild_id BIGINT NOT NULL, kind TEXT NOT NULL, mime_type TEXT NOT NULL,
            file_data BYTEA NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (guild_id, kind)
        )""")


@app.before_request
def before_request():
    if request.path != "/health":
        _ensure_initialized()


def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=15)


async def _fetch(q, *a):
    async with _pool.acquire() as c: return await c.fetch(q, *a)

async def _fetchrow(q, *a):
    async with _pool.acquire() as c: return await c.fetchrow(q, *a)

async def _fetchval(q, *a):
    async with _pool.acquire() as c: return await c.fetchval(q, *a)

async def _execute(q, *a):
    async with _pool.acquire() as c: return await c.execute(q, *a)


# ── Auth ──────────────────────────────────────────────────────────────────────
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if DASHBOARD_SECRET:
            if request.headers.get("X-Dashboard-Token", "") != DASHBOARD_SECRET:
                return jsonify({"error": "No autorizado"}), 401
        return f(*args, **kwargs)
    return decorated


# ── Settings ──────────────────────────────────────────────────────────────────
@app.get("/api/settings/<int:guild_id>")
@require_auth
def get_settings(guild_id):
    rows = run_async(_fetch(
        "SELECT setting_key, setting_value FROM guild_settings WHERE guild_id = $1",
        guild_id
    ))
    return jsonify({r["setting_key"]: r["setting_value"] for r in rows})


@app.post("/api/settings/<int:guild_id>")
@require_auth
def save_settings(guild_id):
    data = request.get_json(force=True) or {}
    if not data:
        return jsonify({"error": "Sin datos"}), 400

    async def _save():
        async with _pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO guild_settings (guild_id, setting_key, setting_value)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (guild_id, setting_key) DO UPDATE
                   SET setting_value = EXCLUDED.setting_value, updated_at = NOW()""",
                [(guild_id, k, str(v)) for k, v in data.items()],
            )
    run_async(_save())
    return jsonify({"ok": True})


@app.delete("/api/settings/<int:guild_id>/<key>")
@require_auth
def delete_setting(guild_id, key):
    run_async(_execute(
        "DELETE FROM guild_settings WHERE guild_id = $1 AND setting_key = $2",
        guild_id, key
    ))
    return jsonify({"ok": True})


# ── Imágenes de bienvenida/despedida ──────────────────────────────────────────
_IMAGE_TYPES = {
    "image/png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "image/gif": lambda b: b.startswith((b"GIF87a", b"GIF89a")),
    "image/webp": lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP",
}
_GREETING_KINDS = {"welcome", "leave"}


def _public_base_url():
    return (os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or request.url_root).rstrip("/")


@app.post("/api/uploads/<int:guild_id>/<kind>")
@require_auth
def upload_greeting_image(guild_id, kind):
    if kind not in _GREETING_KINDS:
        return jsonify({"error": "Tipo de imagen no válido"}), 400
    image = request.files.get("image")
    if not image or not image.filename:
        return jsonify({"error": "Selecciona una imagen"}), 400
    mime = (image.mimetype or "").lower()
    validator = _IMAGE_TYPES.get(mime)
    if not validator:
        return jsonify({"error": "Formato no compatible. Usa PNG, JPG, GIF o WebP"}), 415
    raw = image.stream.read(MAX_IMAGE_BYTES + 1)
    if not raw:
        return jsonify({"error": "El archivo está vacío"}), 400
    if len(raw) > MAX_IMAGE_BYTES:
        return jsonify({"error": "La imagen supera el límite de 5 MB"}), 413
    if not validator(raw):
        return jsonify({"error": "El contenido no coincide con el formato de imagen"}), 415
    try:
        with Image.open(io.BytesIO(raw)) as decoded:
            expected_format = {"image/png": "PNG", "image/jpeg": "JPEG", "image/gif": "GIF", "image/webp": "WEBP"}[mime]
            if decoded.format != expected_format or decoded.width * decoded.height > 40_000_000:
                return jsonify({"error": "La imagen no es válida o tiene dimensiones demasiado grandes"}), 415
            decoded.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return jsonify({"error": "No se pudo validar el archivo como imagen"}), 415
    url = f"{_public_base_url()}/api/uploads/{guild_id}/{kind}"

    async def _store():
        async with _pool.acquire() as conn:
            await conn.execute("""CREATE TABLE IF NOT EXISTS dashboard_uploads (
                guild_id BIGINT NOT NULL,
                kind TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                file_data BYTEA NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (guild_id, kind)
            )""")
            await conn.execute("""INSERT INTO dashboard_uploads (guild_id, kind, mime_type, file_data)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (guild_id, kind) DO UPDATE SET
                mime_type=EXCLUDED.mime_type, file_data=EXCLUDED.file_data, updated_at=NOW()""",
                guild_id, kind, mime, raw)
            await conn.execute("""INSERT INTO guild_settings (guild_id, setting_key, setting_value)
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, setting_key) DO UPDATE SET
                setting_value=EXCLUDED.setting_value, updated_at=NOW()""",
                guild_id, f"{kind}_image_url", url)
        return True

    run_async(_store())
    return jsonify({"ok": True, "url": url, "mime_type": mime, "size": len(raw)})


@app.get("/api/uploads/<int:guild_id>/<kind>")
def get_greeting_image(guild_id, kind):
    if kind not in _GREETING_KINDS:
        return jsonify({"error": "Imagen no encontrada"}), 404
    row = run_async(_fetchrow(
        "SELECT mime_type, file_data FROM dashboard_uploads WHERE guild_id=$1 AND kind=$2",
        guild_id, kind))
    if not row:
        return jsonify({"error": "Imagen no encontrada"}), 404
    return Response(bytes(row["file_data"]), mimetype=row["mime_type"],
                    headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"})


@app.delete("/api/uploads/<int:guild_id>/<kind>")
@require_auth
def delete_greeting_image(guild_id, kind):
    if kind not in _GREETING_KINDS:
        return jsonify({"error": "Tipo de imagen no válido"}), 400
    async def _delete():
        async with _pool.acquire() as conn:
            await conn.execute("DELETE FROM dashboard_uploads WHERE guild_id=$1 AND kind=$2", guild_id, kind)
            await conn.execute("""INSERT INTO guild_settings (guild_id, setting_key, setting_value)
                VALUES ($1, $2, '')
                ON CONFLICT (guild_id, setting_key) DO UPDATE SET
                setting_value='', updated_at=NOW()""", guild_id, f"{kind}_image_url")
    run_async(_delete())
    return jsonify({"ok": True})


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"error": "La imagen supera el límite de 5 MB"}), 413


# ── Warns ─────────────────────────────────────────────────────────────────────
@app.get("/api/warns/<int:guild_id>")
@require_auth
def get_warns(guild_id):
    limit  = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    q      = request.args.get("q", "").strip()

    if q:
        rows = run_async(_fetch(
            """SELECT id, guild_id, user_id, moderator_id, reason,
                      created_at AT TIME ZONE 'UTC' AS created_at
               FROM warns WHERE guild_id = $1 AND (reason ILIKE $2 OR user_id::text = $3)
               ORDER BY created_at DESC LIMIT $4 OFFSET $5""",
            guild_id, f"%{q}%", q, limit, offset
        ))
    else:
        rows = run_async(_fetch(
            """SELECT id, guild_id, user_id, moderator_id, reason,
                      created_at AT TIME ZONE 'UTC' AS created_at
               FROM warns WHERE guild_id = $1
               ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
            guild_id, limit, offset
        ))

    total = run_async(_fetchval("SELECT COUNT(*) FROM warns WHERE guild_id = $1", guild_id))

    def s(r):
        d = dict(r)
        d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
        return d

    return jsonify({"warns": [s(r) for r in rows], "total": total})


@app.delete("/api/warns/<int:warn_id>")
@require_auth
def delete_warn(warn_id):
    run_async(_execute("DELETE FROM warns WHERE id = $1", warn_id))
    return jsonify({"ok": True})


@app.delete("/api/warns/<int:guild_id>/user/<int:user_id>")
@require_auth
def delete_user_warns(guild_id, user_id):
    run_async(_execute(
        "DELETE FROM warns WHERE guild_id = $1 AND user_id = $2", guild_id, user_id
    ))
    return jsonify({"ok": True})


# ── Tickets ───────────────────────────────────────────────────────────────────
@app.get("/api/tickets/<int:guild_id>")
@require_auth
def get_tickets(guild_id):
    status = request.args.get("status", "")
    limit  = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    base = """SELECT id, channel_id, opener_id, title, details, status,
                     claimed_by, closed_by,
                     created_at AT TIME ZONE 'UTC' AS created_at,
                     closed_at  AT TIME ZONE 'UTC' AS closed_at
              FROM tickets WHERE guild_id = $1"""
    if status:
        rows = run_async(_fetch(
            base + " AND status=$2 ORDER BY created_at DESC LIMIT $3 OFFSET $4",
            guild_id, status, limit, offset
        ))
    else:
        rows = run_async(_fetch(
            base + " ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            guild_id, limit, offset
        ))

    total = run_async(_fetchval("SELECT COUNT(*) FROM tickets WHERE guild_id=$1", guild_id))

    def s(r):
        d = dict(r)
        for k in ("created_at", "closed_at"):
            if d.get(k): d[k] = d[k].isoformat()
        return d

    return jsonify({"tickets": [s(r) for r in rows], "total": total})


@app.get("/api/tickets/<int:guild_id>/stats")
@require_auth
def ticket_stats(guild_id):
    row = run_async(_fetchrow(
        """SELECT COUNT(*) FILTER (WHERE status='open')   AS open_count,
                  COUNT(*) FILTER (WHERE status='open' AND claimed_by IS NOT NULL) AS claimed_count,
                  COUNT(*) FILTER (WHERE status='closed') AS closed_count,
                  COUNT(*)                                 AS total
           FROM tickets WHERE guild_id=$1""", guild_id
    ))
    return jsonify(dict(row))


# ── Excepciones purga ─────────────────────────────────────────────────────────
@app.get("/api/purge-exceptions/<int:guild_id>")
@require_auth
def get_purge_exceptions(guild_id):
    rows = run_async(_fetch(
        """SELECT user_id, razon, added_by,
                  created_at AT TIME ZONE 'UTC' AS created_at
           FROM purge_exceptions WHERE guild_id=$1 ORDER BY created_at DESC""",
        guild_id
    ))
    def s(r):
        d = dict(r)
        if d.get("created_at"): d["created_at"] = d["created_at"].isoformat()
        return d
    return jsonify({"exceptions": [s(r) for r in rows]})


@app.post("/api/purge-exceptions/<int:guild_id>")
@require_auth
def add_purge_exception(guild_id):
    body     = request.get_json(force=True) or {}
    user_id  = body.get("user_id")
    razon    = body.get("razon", "Agregado desde dashboard")
    added_by = body.get("added_by", 0)
    if not user_id:
        return jsonify({"error": "user_id requerido"}), 400
    run_async(_execute(
        """INSERT INTO purge_exceptions (guild_id, user_id, razon, added_by)
           VALUES ($1,$2,$3,$4)
           ON CONFLICT (guild_id, user_id) DO UPDATE
           SET razon=EXCLUDED.razon, added_by=EXCLUDED.added_by, created_at=NOW()""",
        guild_id, int(user_id), str(razon), int(added_by)
    ))
    return jsonify({"ok": True})


@app.delete("/api/purge-exceptions/<int:guild_id>/<int:user_id>")
@require_auth
def delete_purge_exception(guild_id, user_id):
    run_async(_execute(
        "DELETE FROM purge_exceptions WHERE guild_id=$1 AND user_id=$2",
        guild_id, user_id
    ))
    return jsonify({"ok": True})


# ── Color roles ───────────────────────────────────────────────────────────────
@app.get("/api/color-roles/<int:guild_id>")
@require_auth
def get_color_roles(guild_id):
    rows = run_async(_fetch(
        "SELECT categoria, clave, role_id FROM color_roles WHERE guild_id=$1", guild_id
    ))
    result = {}
    for r in rows:
        result.setdefault(r["categoria"], {})[r["clave"]] = r["role_id"]
    return jsonify(result)


# ── Paneles de tickets ────────────────────────────────────────────────────────
@app.get("/api/ticket-panels/<int:guild_id>")
@require_auth
def get_ticket_panels(guild_id):
    rows = run_async(_fetch(
        """SELECT id, name, title, description, image_url, buttons, channel_id, message_id,
                  created_at AT TIME ZONE 'UTC' AS created_at,
                  updated_at AT TIME ZONE 'UTC' AS updated_at
           FROM ticket_panels WHERE guild_id=$1 ORDER BY name""", guild_id
    ))
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["buttons"] = json.loads(item["buttons"] or "[]")
        except (TypeError, json.JSONDecodeError):
            item["buttons"] = []
        for key in ("created_at", "updated_at"):
            if item.get(key): item[key] = item[key].isoformat()
        result.append(item)
    return jsonify({"panels": result})


def _panel_payload(body):
    name = str(body.get("name", "")).strip()[:80]
    title = str(body.get("title", "Ayuda y soporte")).strip()[:100]
    description = str(body.get("description", "Selecciona una opción para crear un ticket.")).strip()[:1000]
    image_url = str(body.get("image_url", "")).strip()[:1000]
    buttons = body.get("buttons", [])
    if not name:
        raise ValueError("El nombre del panel es obligatorio")
    if not isinstance(buttons, list) or not buttons:
        raise ValueError("Agrega al menos un botón")
    clean = []
    for item in buttons[:10]:
        if not isinstance(item, dict): continue
        label = str(item.get("label", "")).strip()[:40]
        if label:
            style = str(item.get("style", "secondary"))
            if style not in {"secondary", "success", "danger", "primary"}: style = "secondary"
            clean.append({"emoji": str(item.get("emoji", "🎫"))[:8] or "🎫", "label": label, "style": style})
    if not clean:
        raise ValueError("Agrega al menos un botón válido")
    if image_url and not image_url.startswith(("http://", "https://")):
        raise ValueError("La imagen debe ser una URL http:// o https://")
    return name, title or name, description, image_url, json.dumps(clean, ensure_ascii=False)


@app.post("/api/ticket-panels/<int:guild_id>")
@require_auth
def create_ticket_panel(guild_id):
    try:
        name, title, description, image_url, buttons = _panel_payload(request.get_json(force=True) or {})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    try:
        row = run_async(_fetchrow(
            """INSERT INTO ticket_panels (guild_id, name, title, description, image_url, buttons)
               VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
            guild_id, name, title, description, image_url, buttons,
        ))
    except asyncpg.UniqueViolationError:
        return jsonify({"error": "Ya existe un panel con ese nombre"}), 409
    return jsonify({"ok": True, "id": row["id"]}), 201


@app.put("/api/ticket-panels/<int:guild_id>/<int:panel_id>")
@require_auth
def update_ticket_panel(guild_id, panel_id):
    try:
        name, title, description, image_url, buttons = _panel_payload(request.get_json(force=True) or {})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    try:
        status = run_async(_execute(
            """UPDATE ticket_panels SET name=$1, title=$2, description=$3, image_url=$4, buttons=$5,
                      updated_at=NOW() WHERE id=$6 AND guild_id=$7""",
            name, title, description, image_url, buttons, panel_id, guild_id,
        ))
    except asyncpg.UniqueViolationError:
        return jsonify({"error": "Ya existe un panel con ese nombre"}), 409
    if status.endswith("0"):
        return jsonify({"error": "Panel no encontrado"}), 404
    return jsonify({"ok": True})


@app.delete("/api/ticket-panels/<int:guild_id>/<int:panel_id>")
@require_auth
def delete_ticket_panel(guild_id, panel_id):
    status = run_async(_execute("DELETE FROM ticket_panels WHERE id=$1 AND guild_id=$2", panel_id, guild_id))
    if status.endswith("0"):
        return jsonify({"error": "Panel no encontrado"}), 404
    return jsonify({"ok": True})

@app.post("/api/ticket-panels/<int:guild_id>/<int:panel_id>/image")
@require_auth
def upload_ticket_panel_image(guild_id, panel_id):
    panel = run_async(_fetchrow("SELECT id FROM ticket_panels WHERE id=$1 AND guild_id=$2", panel_id, guild_id))
    if not panel:
        return jsonify({"error": "Panel no encontrado"}), 404
    image = request.files.get("image")
    if not image or not image.filename:
        return jsonify({"error": "Selecciona una imagen"}), 400
    mime = (image.mimetype or "").lower()
    validator = _IMAGE_TYPES.get(mime)
    if not validator:
        return jsonify({"error": "Formato no compatible. Usa PNG, JPG, GIF o WebP"}), 415
    raw = image.stream.read(MAX_IMAGE_BYTES + 1)
    if not raw or len(raw) > MAX_IMAGE_BYTES or not validator(raw):
        return jsonify({"error": "La imagen no es válida o supera el límite de 5 MB"}), 415
    try:
        with Image.open(io.BytesIO(raw)) as decoded:
            expected = {"image/png":"PNG", "image/jpeg":"JPEG", "image/gif":"GIF", "image/webp":"WEBP"}[mime]
            if decoded.format != expected or decoded.width * decoded.height > 40_000_000: return jsonify({"error":"La imagen no es válida"}), 415
            decoded.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return jsonify({"error": "No se pudo validar la imagen"}), 415
    kind = f"panel:{panel_id}"
    url = f"{_public_base_url()}/api/ticket-panels/{guild_id}/{panel_id}/image"
    async def _store():
        async with _pool.acquire() as conn:
            await conn.execute("""INSERT INTO dashboard_uploads (guild_id, kind, mime_type, file_data)
                VALUES ($1,$2,$3,$4) ON CONFLICT (guild_id, kind) DO UPDATE SET
                mime_type=EXCLUDED.mime_type, file_data=EXCLUDED.file_data, updated_at=NOW()""", guild_id, kind, mime, raw)
            await conn.execute("UPDATE ticket_panels SET image_url=$1, updated_at=NOW() WHERE id=$2 AND guild_id=$3", url, panel_id, guild_id)
    run_async(_store())
    return jsonify({"ok": True, "url": url, "size": len(raw)})


@app.get("/api/ticket-panels/<int:guild_id>/<int:panel_id>/image")
def get_ticket_panel_image(guild_id, panel_id):
    row = run_async(_fetchrow("SELECT mime_type, file_data FROM dashboard_uploads WHERE guild_id=$1 AND kind=$2", guild_id, f"panel:{panel_id}"))
    if not row: return jsonify({"error": "Imagen no encontrada"}), 404
    return Response(bytes(row["file_data"]), mimetype=row["mime_type"], headers={"Cache-Control":"public, max-age=3600", "X-Content-Type-Options":"nosniff"})


@app.delete("/api/ticket-panels/<int:guild_id>/<int:panel_id>/image")
@require_auth
def delete_ticket_panel_image(guild_id, panel_id):
    async def _delete():
        async with _pool.acquire() as conn:
            await conn.execute("DELETE FROM dashboard_uploads WHERE guild_id=$1 AND kind=$2", guild_id, f"panel:{panel_id}")
            await conn.execute("UPDATE ticket_panels SET image_url='', updated_at=NOW() WHERE id=$1 AND guild_id=$2", panel_id, guild_id)
    run_async(_delete())
    return jsonify({"ok": True})

# ── Abo Cards ─────────────────────────────────────────────────────────────────
_CARD_RARITIES = {"Común", "Rara", "Épica", "Legendaria"}
_CARD_SLUG_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")


def _card_image_from_request(required=False):
    image = request.files.get("image")
    if not image or not image.filename:
        if required:
            raise ValueError("Selecciona una imagen para la carta")
        return None
    mime = (image.mimetype or "").lower()
    validator = _IMAGE_TYPES.get(mime)
    if not validator:
        raise ValueError("Formato no compatible. Usa PNG, JPG, GIF o WebP")
    raw = image.stream.read(MAX_IMAGE_BYTES + 1)
    if not raw or len(raw) > MAX_IMAGE_BYTES or not validator(raw):
        raise ValueError("La imagen no es válida o supera el límite de 5 MB")
    try:
        with Image.open(io.BytesIO(raw)) as decoded:
            expected = {"image/png":"PNG", "image/jpeg":"JPEG", "image/gif":"GIF", "image/webp":"WEBP"}[mime]
            if decoded.format != expected or decoded.width * decoded.height > 40_000_000:
                raise ValueError("La imagen no es válida o tiene dimensiones demasiado grandes")
            decoded.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("No se pudo validar la imagen") from error
    ext = {"image/png":"png", "image/jpeg":"jpg", "image/gif":"gif", "image/webp":"webp"}[mime]
    return mime, raw, ext


def _card_json(row):
    data = dict(row)
    data["has_image"] = bool(data.pop("image_data", None))
    data["created_at"] = data["created_at"].isoformat() if data.get("created_at") else None
    return data


@app.get("/api/cards/<int:guild_id>")
@require_auth
def get_cards(guild_id):
    rows = run_async(_fetch("""SELECT slug,name,rarity,image_file,drop_weight,base_value,active,emoji_name,emoji_id,image_data,set_slug,created_at
                              FROM card_catalog ORDER BY created_at ASC, name ASC"""))
    return jsonify({"cards": [_card_json(row) for row in rows]})


@app.post("/api/cards/<int:guild_id>")
@require_auth
def create_card(guild_id):
    form = request.form
    slug = form.get("slug", "").strip().lower()
    name = form.get("name", "").strip()
    rarity = form.get("rarity", "Común").strip()
    emoji_name = form.get("emoji_name", "").strip()
    emoji_id = form.get("emoji_id", "").strip()
    set_slug = form.get("set_slug", "original").strip().lower() or "original"
    try:
        weight = int(form.get("drop_weight", "25"))
        value = int(form.get("base_value", "100"))
    except ValueError:
        return jsonify({"error": "Peso y valor deben ser números enteros"}), 400
    if not _CARD_SLUG_RE.fullmatch(slug): return jsonify({"error": "El slug debe usar minúsculas, números, guion o guion bajo (2–40 caracteres)"}), 400
    if not name or len(name) > 80: return jsonify({"error": "El nombre es obligatorio y debe tener máximo 80 caracteres"}), 400
    if rarity not in _CARD_RARITIES or not 1 <= weight <= 10000 or not 1 <= value <= 10_000_000:
        return jsonify({"error": "Rareza, peso o valor no válidos"}), 400
    if emoji_id and not emoji_id.isdigit(): return jsonify({"error": "El ID del emoji debe ser numérico"}), 400
    run_async(_execute("INSERT INTO card_sets (slug,name) VALUES ($1,$2) ON CONFLICT (slug) DO NOTHING", set_slug, set_slug.replace("_", " ").title()))
    try:
        uploaded = _card_image_from_request(required=True)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    mime, raw, ext = uploaded
    image_file = f"{slug}.{ext}"
    try:
        run_async(_execute("""INSERT INTO card_catalog (slug,name,rarity,image_file,drop_weight,base_value,active,emoji_name,emoji_id,image_mime,image_data,set_slug)
                             VALUES ($1,$2,$3,$4,$5,$6,TRUE,$7,$8,$9,$10,$11)""",
                             slug,name,rarity,image_file,weight,value,emoji_name,emoji_id,mime,raw,set_slug))
    except asyncpg.UniqueViolationError:
        return jsonify({"error": "Ya existe una carta con ese slug"}), 409
    return jsonify({"ok": True, "slug": slug}), 201


@app.put("/api/cards/<int:guild_id>/<slug>")
@require_auth
def update_card(guild_id, slug):
    if not _CARD_SLUG_RE.fullmatch(slug): return jsonify({"error": "Slug inválido"}), 400
    form = request.form
    name = form.get("name", "").strip()
    rarity = form.get("rarity", "Común").strip()
    emoji_name = form.get("emoji_name", "").strip()
    emoji_id = form.get("emoji_id", "").strip()
    set_slug = form.get("set_slug", "original").strip().lower() or "original"
    run_async(_execute("INSERT INTO card_sets (slug,name) VALUES ($1,$2) ON CONFLICT (slug) DO NOTHING", set_slug, set_slug.replace("_", " ").title()))
    try:
        weight = int(form.get("drop_weight", "25")); value = int(form.get("base_value", "100"))
    except ValueError:
        return jsonify({"error": "Peso y valor deben ser números enteros"}), 400
    if not name or len(name) > 80 or rarity not in _CARD_RARITIES or not 1 <= weight <= 10000 or not 1 <= value <= 10_000_000:
        return jsonify({"error": "Datos de carta no válidos"}), 400
    if emoji_id and not emoji_id.isdigit(): return jsonify({"error": "El ID del emoji debe ser numérico"}), 400
    try:
        uploaded = _card_image_from_request(required=False)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if uploaded:
        mime, raw, ext = uploaded
        image_file = f"{slug}.{ext}"
        query = """UPDATE card_catalog SET name=$1,rarity=$2,drop_weight=$3,base_value=$4,emoji_name=$5,emoji_id=$6,image_file=$7,image_mime=$8,image_data=$9,set_slug=$10,active=TRUE WHERE slug=$11"""
        args = (name,rarity,weight,value,emoji_name,emoji_id,image_file,mime,raw,set_slug,slug)
    elif form.get("remove_image") == "1":
        query = """UPDATE card_catalog SET name=$1,rarity=$2,drop_weight=$3,base_value=$4,emoji_name=$5,emoji_id=$6,image_file=$7,image_mime='',image_data=NULL,set_slug=$8,active=TRUE WHERE slug=$9"""
        args = (name,rarity,weight,value,emoji_name,emoji_id,f"{slug}.png",set_slug,slug)
    else:
        query = """UPDATE card_catalog SET name=$1,rarity=$2,drop_weight=$3,base_value=$4,emoji_name=$5,emoji_id=$6,set_slug=$7,active=TRUE WHERE slug=$8"""
        args = (name,rarity,weight,value,emoji_name,emoji_id,set_slug,slug)
    updated = run_async(_execute(query, *args))
    if int(str(updated).split()[-1]) == 0:
        return jsonify({"error": "Carta no encontrada"}), 404
    return jsonify({"ok": True, "slug": slug})


@app.delete("/api/cards/<int:guild_id>/<slug>")
@require_auth
def delete_card(guild_id, slug):
    result = run_async(_execute("UPDATE card_catalog SET active=FALSE WHERE slug=$1", slug))
    if int(str(result).split()[-1]) == 0: return jsonify({"error": "Carta no encontrada"}), 404
    return jsonify({"ok": True})

_CARD_MESSAGE_KEYS = {"pack_opened", "level_up", "pity_rare", "pity_epic", "set_complete"}

@app.get("/api/card-messages/<int:guild_id>")
@require_auth
def get_card_messages(guild_id):
    rows = run_async(_fetch("SELECT message_key,title,description,color,updated_at FROM card_message_templates WHERE guild_id=$1 ORDER BY message_key", guild_id))
    return jsonify({"messages": [{**dict(row), "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None} for row in rows]})

@app.put("/api/card-messages/<int:guild_id>/<message_key>")
@require_auth
def update_card_message(guild_id, message_key):
    if message_key not in _CARD_MESSAGE_KEYS:
        return jsonify({"error": "Mensaje no permitido"}), 400
    data = request.get_json(silent=True) or {}
    title, description = str(data.get("title", "")).strip(), str(data.get("description", "")).strip()
    try: color = int(data.get("color", 5793266))
    except (TypeError, ValueError): return jsonify({"error": "El color no es válido"}), 400
    if not title or not description or len(title) > 256 or len(description) > 4000 or not 0 <= color <= 16777215:
        return jsonify({"error": "Título, descripción o color no válidos"}), 400
    run_async(_execute("""INSERT INTO card_message_templates (guild_id,message_key,title,description,color,updated_by)
        VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (guild_id,message_key) DO UPDATE SET title=EXCLUDED.title,description=EXCLUDED.description,color=EXCLUDED.color,updated_by=EXCLUDED.updated_by,updated_at=NOW()""", guild_id, message_key, title, description, color, session.get("user_id")))
    return jsonify({"ok": True})

# ── Stats ─────────────────────────────────────────────────────────────────────
@app.get("/api/stats/<int:guild_id>")
@require_auth
def get_stats(guild_id):
    return jsonify({
        "warns_total":      run_async(_fetchval("SELECT COUNT(*) FROM warns WHERE guild_id=$1", guild_id)),
        "tickets_open":     run_async(_fetchval("SELECT COUNT(*) FROM tickets WHERE guild_id=$1 AND status='open'", guild_id)),
        "exceptions_count": run_async(_fetchval("SELECT COUNT(*) FROM purge_exceptions WHERE guild_id=$1", guild_id)),
        "memory_users":     run_async(_fetchval("SELECT COUNT(DISTINCT user_id) FROM memory")),
    })


# ── Memoria IA ────────────────────────────────────────────────────────────────
@app.delete("/api/memory/<int:user_id>")
@require_auth
def clear_user_memory(user_id):
    run_async(_execute("DELETE FROM memory WHERE user_id=$1", user_id))
    return jsonify({"ok": True})


@app.delete("/api/memory/all")
@require_auth
def clear_all_memory():
    run_async(_execute("DELETE FROM memory"))
    return jsonify({"ok": True})


# ── Healthcheck ───────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    try:
        _ensure_initialized()
        run_async(_fetchval("SELECT 1"))
        return jsonify({"status": "ok", "database": "ok"}), 200
    except Exception as error:
        app.logger.warning("Healthcheck sin conexión: %s", error)
        return jsonify({"status": "degraded", "database": "unavailable"}), 503


# ── Frontend ──────────────────────────────────────────────────────────────────
@app.get("/")
def serve_dashboard():
    return send_from_directory("dashboard_static", "index.html")
