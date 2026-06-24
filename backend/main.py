"""FastAPI application entrypoint."""

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app_bootstrap.frontend_build import build_frontend
from app_bootstrap.route_registry import register_api_routes
from app_bootstrap.spa_routes import register_spa_routes
from app_bootstrap.static_files import mount_static_assets
from app_bootstrap.startup_events import register_lifecycle_events
from database.models_event_contract import EventContractOrder  # noqa: F401
from database.models_event_contract_config import EventContractConfig  # noqa: F401
from services.message_archive import register_message_archive_listeners
from version import __version__

load_dotenv()
register_message_archive_listeners()

app = FastAPI(
    title="Hyper Alpha Arena API",
    version=__version__,
    description="Cryptocurrency perpetual contract trading platform with AI-powered decision making",
)


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "message": "Trading API is running",
        "version": __version__,
    }


@app.post("/api/rebuild-frontend")
async def rebuild_frontend():
    try:
        build_frontend()
        return {"status": "success", "message": "Frontend rebuild triggered"}
    except Exception as exc:
        return {"status": "error", "message": f"Frontend rebuild failed: {exc}"}


_cors_env = os.getenv("CORS_ALLOWED_ORIGINS", "")
_cors_origins = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins if _cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_static_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


mount_static_assets(app)
register_lifecycle_events(app)
register_api_routes(app)
register_spa_routes(app)
