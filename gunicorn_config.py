"""
gunicorn_config.py
El pool asyncpg se inicializa lazy en el worker (before_request),
así que aquí solo configuramos workers/threads/puerto.
"""
import os

bind     = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers  = 1
threads  = 4
timeout  = 60
loglevel = "info"
