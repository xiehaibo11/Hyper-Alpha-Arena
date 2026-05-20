"""Live-server entrypoint for deployment-only route extensions."""

from __future__ import annotations

import logging

from main import app

logger = logging.getLogger(__name__)


def include_live_routes() -> None:
    try:
        from api.okx_routes import router as okx_router

        app.include_router(okx_router)
        move_spa_fallback_last()
        logger.info("[LiveRoutes] OKX routes registered")
    except Exception as exc:
        logger.error("[LiveRoutes] Failed to register OKX routes: %s", exc, exc_info=True)
        raise


def move_spa_fallback_last() -> None:
    fallback_routes = [route for route in app.router.routes if getattr(route, "path", None) == "/{full_path:path}"]
    if not fallback_routes:
        return
    app.router.routes[:] = [
        route for route in app.router.routes if getattr(route, "path", None) != "/{full_path:path}"
    ] + fallback_routes


include_live_routes()
