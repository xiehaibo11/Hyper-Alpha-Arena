"""Live-server entrypoint for deployment-only route extensions."""

from __future__ import annotations

import logging

from main import app

logger = logging.getLogger(__name__)


def include_live_routes() -> None:
    try:
        from api.okx_routes import router as okx_router
        from api.manual_trading_routes import router as manual_trading_router
        from api.signal_live_routes import router as signal_live_router
        from api.vpn_subscription_routes import router as vpn_subscription_router
        from api.binance_position_mode_routes import router as binance_position_mode_router
        from api.account_profile_defaults_routes import router as account_profile_defaults_router
        from services.ai_decision_skill_context import install_ai_decision_skill_guardrails_patch

        install_ai_decision_skill_guardrails_patch()
        app.include_router(okx_router)
        app.include_router(manual_trading_router)
        app.include_router(signal_live_router)
        app.include_router(vpn_subscription_router)
        replace_route("/api/binance/accounts/{account_id}/position-mode", {"GET"})
        app.include_router(binance_position_mode_router)
        replace_route("/api/account/test-llm", {"POST"})
        replace_route("/api/account/", {"POST"})
        replace_route("/api/account/list", {"GET"})
        app.include_router(account_profile_defaults_router)
        move_spa_fallback_last()
        logger.info("[LiveRoutes] OKX, manual trading, signal live, VPN, and account profile routes registered")
    except Exception as exc:
        logger.error("[LiveRoutes] Failed to register OKX routes: %s", exc, exc_info=True)
        raise


def replace_route(path: str, methods: set[str]) -> None:
    app.router.routes[:] = [
        route for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and methods.issubset(getattr(route, "methods", set()))
        )
    ]


def move_spa_fallback_last() -> None:
    fallback_routes = [route for route in app.router.routes if getattr(route, "path", None) == "/{full_path:path}"]
    if not fallback_routes:
        return
    app.router.routes[:] = [
        route for route in app.router.routes if getattr(route, "path", None) != "/{full_path:path}"
    ] + fallback_routes


include_live_routes()
