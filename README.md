# Abo Dashboard — Deploy en Render

## Estructura del repo

```
dashboard.py            ← API Flask + asyncpg (standalone, sin bot)
dashboard_static/
  index.html            ← Frontend
gunicorn_config.py      ← Config de Gunicorn con init del pool asyncio
requirements.txt        ← Flask, asyncpg, gunicorn
render.yaml             ← Deploy automático (opcional)
.env.example            ← Variables a configurar
```

## Pasos

### 1. Crea un repo nuevo (o carpeta en el mismo repo de Abo)

Sube estos archivos. Puede ser un repo separado —
el dashboard no necesita el código del bot.

### 2. Crea un Web Service en Render

- New → Web Service → conecta tu repo
- Runtime: **Python**
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn dashboard:app -c gunicorn_config.py`
- Health check path: `/health`

### 3. Variables de entorno en Render

En el panel del servicio → Environment:

| Variable          | Valor                                      |
|-------------------|--------------------------------------------|
| `DATABASE_URL`    | La misma que tienes en Railway para Abo    |
| `DASHBOARD_SECRET`| Una clave larga (ej. `openssl rand -hex 32`) |

`PORT` lo añade Render solo — no la pongas.

### 4. Deploy

Render hace el deploy automáticamente al hacer push.
La URL del servicio será algo como:
`https://abo-dashboard.onrender.com`

### 5. Abre el dashboard

Ve a `https://abo-dashboard.onrender.com` e ingresa:

- **DASHBOARD_SECRET**: la clave que pusiste
- **Guild ID**: el ID numérico de tu servidor de Discord
- **URL de la API**: `https://abo-dashboard.onrender.com`
  (sin / al final)

## Plan gratuito de Render

El plan Free hiberna el servicio tras 15 min de inactividad.
La primera petición tarda ~30 s en despertar.
Para evitarlo, usa el plan Starter ($7/mes) o añade un cron
externo que haga ping a `/health` cada 10 minutos.

## Seguridad

`DASHBOARD_SECRET` es la única barrera de acceso.
Usa `openssl rand -hex 32` para generar una clave segura.
