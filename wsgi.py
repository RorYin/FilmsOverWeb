"""
WSGI entrypoint for WSGI hosting environments (e.g., PythonAnywhere, cPanel, Gunicorn WSGI).
Adapts the ASGI FastAPI application using a2wsgi ASGIMiddleware.
"""
from a2wsgi import ASGIMiddleware
from app.main import app

# 'application' is the WSGI callable expected by PythonAnywhere
application = ASGIMiddleware(app)
