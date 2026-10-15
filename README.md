# Abo Dashboard

Dashboard web independiente para Abo. Se enlaza con el bot mediante PostgreSQL/Neon, no mediante archivos Python compartidos.

## Ejecución

```bash
pip install -r requirements.txt
gunicorn dashboard:app -c gunicorn_config.py
```

Configura `DATABASE_URL` y `DASHBOARD_SECRET`. Al iniciar, el dashboard aplica `dashboard_schema.sql` y crea las tablas necesarias.

La interfaz se sirve desde la misma URL que la API; deja vacía la URL de API en el login para usar el mismo origen.

Consulta `INTEGRACION-BOT.md` para enlazarlo con el proyecto separado del bot.
