"""
gunicorn_config.py — Inicializa asyncio + pool Neon antes de que Gunicorn levante workers.
"""
import asyncio
import threading
import os

bind     = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers  = 1
threads  = 4
timeout  = 60
loglevel = "info"


def _run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


def on_starting(server):
    """Hook de Gunicorn: se ejecuta UNA vez al arrancar, antes de los workers."""
    import dashboard
    loop = asyncio.new_event_loop()
    dashboard._loop = loop          # asigna directamente, sin global

    t = threading.Thread(target=_run_loop, args=(loop,), daemon=True)
    t.start()

    asyncio.run_coroutine_threadsafe(dashboard._init_pool(), loop).result(timeout=15)
    print("[Abo Dashboard] Pool de Neon listo ✅")
