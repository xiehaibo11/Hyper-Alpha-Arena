"""API route registration for the FastAPI application."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from database.connection import SessionLocal


def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def register_api_routes(app: FastAPI) -> None:
    from api.account_routes import router as account_router
    from api.ai_stream_routes import router as ai_stream_router
    from api.analytics_routes import router as analytics_router
    from api.arena_routes import router as arena_router
    from api.binance_routes import router as binance_router
    from api.bot_routes import router as bot_router
    from api.config_routes import router as config_router
    from api.crypto_routes import router as crypto_router
    from api.event_contract_routes import router as event_contract_router
    from api.factor_routes import router as factor_router
    from api.hyper_ai_routes import router as hyper_ai_router
    from api.hyperliquid_action_routes import router as hyperliquid_action_router
    from api.hyperliquid_routes import router as hyperliquid_router
    from api.kline_analysis_routes import router as kline_analysis_router
    from api.kline_routes import router as kline_router
    from api.market_data_routes import router as market_data_router
    from api.market_flow_routes import router as market_flow_router
    from api.market_intelligence_routes import router as market_intelligence_router
    from api.market_regime_routes import router as market_regime_router
    from api.news_routes import router as news_router
    from api.okx_routes import router as okx_router
    from api.order_routes import router as order_router
    from api.prompt_backtest_routes import router as prompt_backtest_router
    from api.prompt_routes import router as prompt_router
    from api.ranking_routes import router as ranking_router
    from api.sampling_routes import router as sampling_router
    from api.signal_routes import router as signal_router
    from api.system_log_routes import router as system_log_router
    from api.system_routes import router as system_router
    from api.trader_data_routes import router as trader_data_router
    from api.user_routes import router as user_router
    from routes.program_routes import router as program_router

    routers = [
        market_data_router,
        order_router,
        account_router,
        config_router,
        ranking_router,
        crypto_router,
        arena_router,
        system_log_router,
        prompt_router,
        sampling_router,
        hyperliquid_action_router,
        hyperliquid_router,
        user_router,
        kline_router,
        kline_analysis_router,
        market_flow_router,
        signal_router,
        market_regime_router,
        analytics_router,
        trader_data_router,
        prompt_backtest_router,
        program_router,
        system_router,
        binance_router,
        okx_router,
        ai_stream_router,
        hyper_ai_router,
        bot_router,
        factor_router,
        news_router,
        market_intelligence_router,
        event_contract_router,
    ]
    for router in routers:
        app.include_router(router)

    _register_strategy_aliases(app)
    _register_websocket(app)


def _register_strategy_aliases(app: FastAPI) -> None:
    @app.get("/api/accounts/{account_id}/strategy")
    async def get_account_strategy_alias(account_id: int, db: Session = Depends(_get_db)):
        from api.account_routes import get_account_strategy

        return await get_account_strategy(account_id, db)

    @app.put("/api/accounts/{account_id}/strategy")
    async def update_account_strategy_alias(
        account_id: int,
        payload: dict,
        db: Session = Depends(_get_db),
    ):
        from api.account_routes import update_account_strategy
        from pydantic import ValidationError
        from schemas.account import StrategyConfigUpdate

        try:
            strategy_update = StrategyConfigUpdate(**payload)
            return await update_account_strategy(account_id, strategy_update, db)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/strategy/status")
    async def get_strategy_manager_status():
        from services.trading_strategy import get_strategy_status

        return get_strategy_status()


def _register_websocket(app: FastAPI) -> None:
    from api.ws import websocket_endpoint

    app.websocket("/ws")(websocket_endpoint)
