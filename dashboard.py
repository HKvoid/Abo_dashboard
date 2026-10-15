"""
dashboard.py — Web Service standalone para Render.
El pool asyncpg se inicializa dentro del worker con before_request,
porque on_starting corre en el master y los workers no heredan el loop.
"""
import os
import asyncio
import threading
import asyncpg

from flask import Flask, jsonify, request, send_from_directory, g
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL     = os.getenv("DATABASE_URL", "")
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "")
PORT             = int(os.getenv("PORT", "10000"))

app = Flask(__name__, static_folder="dashboard_static", static_url_path="")

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
    _pool = await asyncpg.create_pool(
        dsn=_normalize_dsn(DATABASE_URL),
        ssl="require",
        min_size=1, max_size=4,
        command_timeout=20,
        statement_cache_size=0,
    )


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
    return jsonify({"status": "ok"}), 200


# ── Frontend ──────────────────────────────────────────────────────────────────
@app.get("/")
def serve_dashboard():
    return send_from_directory("dashboard_static", "index.html")
