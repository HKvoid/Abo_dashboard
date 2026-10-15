"""
gunicorn_config.py
Render usa Gunicorn por defecto. Este archivo inicializa el loop de asyncio
y el pool de Neon antes de que cualquier worker atienda peticiones.
"""
import asyncio
import threading
import os

bind    = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers = 1          # 1 worker: comparte el mismo loop asyncio
threads = 4          # 4 threads por worker para concurrencia en Flask
timeout = 60
loglevel = "info"


def on_starting(server):
    """Hook de Gunicorn: se ejecuta UNA vez al arrancar, antes de los workers."""
    import dashboard
    loop = asyncio.new_event_loop()
    dashboard._loop = loop

    t = threading.Thread(target=_run_loop, args=(loop,), daemon=True)
    t.start()

    asyncio.run_coroutine_threadsafe(dashboard._init_pool(), loop).result(timeout=15)
    print("[Abo Dashboard] Pool de Neon listo ✅")


def _run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()
