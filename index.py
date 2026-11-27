"""Vercel entrypoint: exposes the FastAPI app."""
from app.main import app, init_app_data

# Initialise at import time too, in case the platform skips ASGI lifespan events
init_app_data()

__all__ = ["app"]
