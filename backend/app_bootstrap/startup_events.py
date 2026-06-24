"""FastAPI startup and shutdown event registration."""

from __future__ import annotations

import threading
import time

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app_bootstrap.frontend_build import start_frontend_watcher_if_enabled
from app_bootstrap.runtime_monitor import start_runtime_monitor, stop_runtime_monitor
from config.settings import DEFAULT_TRADING_CONFIGS
from database.connection import Base, SessionLocal, engine
from database.models import SystemConfig, TradingConfig, User


def _initialize_database() -> None:
    Base.metadata.create_all(bind=engine)

    try:
        from database.init_snapshot_db import init_snapshot_database

        init_snapshot_database()
    except Exception as exc:
        print(f"[startup] Snapshot database initialization error (non-fatal): {exc}")

    try:
        from database.migration_manager import run_all_migrations

        run_all_migrations()
    except Exception as exc:
        print(f"[startup] Migration error (non-fatal): {exc}")

    try:
        from database.schema_validator import validate_and_sync_schema

        validate_and_sync_schema()
    except Exception as exc:
        print(f"[startup] Schema validation error (non-fatal): {exc}")


def _ensure_ai_decision_snapshot_columns(db: Session) -> None:
    try:
        result = db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'ai_decision_logs'
        """))
        columns = {row[0] for row in result}

        if "prompt_snapshot" not in columns:
            db.execute(text("ALTER TABLE ai_decision_logs ADD COLUMN prompt_snapshot TEXT"))
        if "reasoning_snapshot" not in columns:
            db.execute(text("ALTER TABLE ai_decision_logs ADD COLUMN reasoning_snapshot TEXT"))
        if "decision_snapshot" not in columns:
            db.execute(text("ALTER TABLE ai_decision_logs ADD COLUMN decision_snapshot TEXT"))
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[startup] Failed to ensure AI decision log snapshot columns: {exc}")


def _ensure_sampling_depth_column(db: Session) -> None:
    try:
        result = db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'global_sampling_configs'
        """))
        columns = {row[0] for row in result}

        if "sampling_depth" not in columns:
            db.execute(text(
                "ALTER TABLE global_sampling_configs "
                "ADD COLUMN sampling_depth INTEGER NOT NULL DEFAULT 10"
            ))
            print("[startup] Added sampling_depth column to global_sampling_configs")
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[startup] Failed to ensure global_sampling_configs.sampling_depth: {exc}")


def _ensure_crypto_kline_exchange_column(db: Session) -> None:
    try:
        result = db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'crypto_klines'
        """))
        columns = {row[0] for row in result}

        if "exchange" not in columns:
            print("[startup] Adding exchange column to crypto_klines table...")
            db.execute(text("""
                ALTER TABLE crypto_klines
                ADD COLUMN exchange VARCHAR(20) NOT NULL DEFAULT 'hyperliquid'
            """))
            db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_crypto_klines_exchange
                ON crypto_klines(exchange)
            """))
            db.execute(text("""
                ALTER TABLE crypto_klines
                DROP CONSTRAINT IF EXISTS crypto_klines_symbol_market_period_timestamp_key
            """))
            print("[startup] Successfully added exchange column to crypto_klines")
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[startup] Failed to ensure crypto_klines.exchange: {exc}")


def _ensure_crypto_kline_environment_column(db: Session) -> None:
    try:
        result = db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'crypto_klines'
        """))
        columns = {row[0] for row in result}

        if "environment" not in columns:
            print("[startup] Adding environment column to crypto_klines table...")
            db.execute(text("""
                ALTER TABLE crypto_klines
                ADD COLUMN environment VARCHAR(20) NOT NULL DEFAULT 'mainnet'
            """))
            db.execute(text("""
                UPDATE crypto_klines SET environment = 'mainnet'
                WHERE environment IS NULL
            """))
            db.execute(text("""
                ALTER TABLE crypto_klines
                DROP CONSTRAINT IF EXISTS crypto_klines_exchange_symbol_market_period_timestamp_key
            """))
            db.execute(text("""
                ALTER TABLE crypto_klines
                DROP CONSTRAINT IF EXISTS uq_crypto_klines_unique
            """))
            db.execute(text("""
                ALTER TABLE crypto_klines
                ADD CONSTRAINT crypto_klines_exchange_symbol_market_period_timestamp_environment_key
                UNIQUE (exchange, symbol, market, period, timestamp, environment)
            """))
            db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_crypto_klines_environment
                ON crypto_klines(environment)
            """))
            db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_crypto_klines_symbol_period_env
                ON crypto_klines(symbol, period, environment)
            """))
            print("[startup] Successfully added environment column to crypto_klines")
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[startup] Failed to ensure crypto_klines.environment: {exc}")


def _seed_trading_configs_and_default_user() -> None:
    db = SessionLocal()
    try:
        _ensure_ai_decision_snapshot_columns(db)
        _ensure_sampling_depth_column(db)
        _ensure_crypto_kline_exchange_column(db)
        _ensure_crypto_kline_environment_column(db)

        if db.query(TradingConfig).count() == 0:
            for cfg in DEFAULT_TRADING_CONFIGS.values():
                db.add(TradingConfig(
                    version="v1",
                    market=cfg.market,
                    min_commission=cfg.min_commission,
                    commission_rate=cfg.commission_rate,
                    exchange_rate=cfg.exchange_rate,
                    min_order_quantity=cfg.min_order_quantity,
                    lot_size=cfg.lot_size,
                ))
            db.commit()

        default_user = db.query(User).filter(User.username == "default").first()
        if not default_user:
            default_user = User(
                username="default",
                email=None,
                password_hash=None,
                is_active="true",
            )
            db.add(default_user)
            db.commit()
            db.refresh(default_user)
    finally:
        db.close()


def _ensure_hyperliquid_trading_mode() -> None:
    db = SessionLocal()
    try:
        config = db.query(SystemConfig).filter(
            SystemConfig.key == "hyperliquid_trading_mode"
        ).first()

        if not config:
            db.add(SystemConfig(
                key="hyperliquid_trading_mode",
                value="testnet",
                description=(
                    "Global Hyperliquid trading environment: 'testnet' or 'mainnet'. "
                    "Controls which network all AI Traders connect to."
                ),
            ))
            db.commit()
            print("✓ [Upgrade] Initialized global hyperliquid_trading_mode to 'testnet'")
        else:
            print(f"✓ [Upgrade] Global hyperliquid_trading_mode already configured: {config.value}")

        null_count = db.execute(text("""
            SELECT COUNT(*) FROM ai_decision_logs WHERE hyperliquid_environment IS NULL
        """)).scalar()

        if null_count > 0:
            print(f"⚠ [Upgrade] Found {null_count} ai_decision_logs with NULL hyperliquid_environment, fixing...")
            db.execute(text("""
                UPDATE ai_decision_logs
                SET hyperliquid_environment = 'testnet'
                WHERE hyperliquid_environment IS NULL
            """))
            db.commit()
            print(f"✓ [Upgrade] Updated {null_count} records from NULL to 'testnet' (ModelChat fix)")
        else:
            print("✓ [Upgrade] No NULL hyperliquid_environment records found, data is clean")
    except Exception as exc:
        db.rollback()
        print(f"✗ [Upgrade] Hyperliquid environment upgrade failed: {exc}")
    finally:
        db.close()


def _seed_prompt_templates() -> None:
    db = SessionLocal()
    try:
        from services.prompt_initializer import seed_prompt_templates

        seed_prompt_templates(db)
    finally:
        db.close()


def _configure_sampling_pool() -> None:
    try:
        from database.models import GlobalSamplingConfig
        from services.hyperliquid_symbol_service import get_selected_symbols
        from services.sampling_pool import sampling_pool
        from services.trading_commands import AI_TRADING_SYMBOLS

        db = SessionLocal()
        try:
            symbols = get_selected_symbols() or AI_TRADING_SYMBOLS
            global_config = db.query(GlobalSamplingConfig).first()
            if global_config and global_config.sampling_depth:
                for symbol in symbols:
                    sampling_pool.set_max_samples(symbol, global_config.sampling_depth)
                print(f"✓ Sampling pool configured: depth={global_config.sampling_depth} for {len(symbols)} symbols")
            else:
                print(f"⚠ No global sampling config found, using default depth={sampling_pool.default_max_samples} for {len(symbols)} symbols")
        finally:
            db.close()
    except Exception as exc:
        print(f"✗ Failed to load global sampling config: {exc}")


def _cleanup_backfill_tasks() -> None:
    try:
        from database.models import KlineCollectionTask

        db = SessionLocal()
        try:
            deleted_count = db.query(KlineCollectionTask).filter(
                KlineCollectionTask.status.in_(["running", "pending"])
            ).delete(synchronize_session=False)
            db.commit()
            if deleted_count > 0:
                print(f"✓ Cleaned up {deleted_count} leftover backfill tasks")
        finally:
            db.close()
    except Exception as exc:
        print(f"⚠ Failed to clean up backfill tasks: {exc}")


def _warmup_numba_async() -> None:
    def warmup_numba() -> None:
        try:
            from database.connection import SessionLocal
            from services.technical_indicators import calculate_indicator

            db = SessionLocal()
            try:
                print("[startup] Warming up numba JIT compilation...")
                calculate_indicator(db, "BTC", "BOLL", "1h", int(time.time() * 1000))
                print("[startup] Numba warmup completed")
            finally:
                db.close()
        except Exception as exc:
            print(f"[startup] Numba warmup failed (non-fatal): {exc}")

    threading.Thread(target=warmup_numba, daemon=True).start()


def _initialize_application_services() -> None:
    from services.startup import initialize_services
    from services.system_logger import setup_system_logger

    setup_system_logger()
    _configure_sampling_pool()
    _cleanup_backfill_tasks()
    print("About to initialize services...")
    initialize_services()
    print("Services initialization completed")
    _warmup_numba_async()


def register_lifecycle_events(app: FastAPI) -> None:
    @app.on_event("startup")
    def on_startup() -> None:
        if start_frontend_watcher_if_enabled():
            print("Frontend file watcher started")

        start_runtime_monitor()
        print("Runtime monitor started")

        _initialize_database()
        _seed_trading_configs_and_default_user()
        _ensure_hyperliquid_trading_mode()
        _seed_prompt_templates()
        _initialize_application_services()

    @app.on_event("startup")
    async def restore_telegram_webhook_and_adapter() -> None:
        try:
            from database.models import BotConfig
            from services.bot_adapter import register_adapter
            from services.bot_service import get_decrypted_bot_token
            from services.telegram_bot_service import get_telegram_adapter, restore_telegram_webhook

            await restore_telegram_webhook()

            db = SessionLocal()
            try:
                config = db.query(BotConfig).filter(
                    BotConfig.platform == "telegram",
                    BotConfig.status == "connected",
                ).first()
                if not config:
                    return

                token = get_decrypted_bot_token(db, "telegram")
                if not token:
                    return

                adapter = get_telegram_adapter()
                await adapter.start(token)
                register_adapter(adapter)
                print("[startup] Telegram adapter registered")
            finally:
                db.close()
        except Exception as exc:
            print(f"[startup] Telegram webhook restore failed (non-fatal): {exc}")

    @app.on_event("startup")
    async def restore_discord_gateway() -> None:
        try:
            from api.bot_routes import _process_discord_message_internal
            from database.models import BotConfig
            from services.bot_adapter import register_adapter
            from services.bot_service import get_decrypted_bot_token
            from services.discord_bot_service import get_discord_adapter, start_discord_gateway
            import asyncio

            db = SessionLocal()
            try:
                config = db.query(BotConfig).filter(
                    BotConfig.platform == "discord",
                    BotConfig.status == "connected",
                ).first()
                if not config:
                    return

                token = get_decrypted_bot_token(db, "discord")
                if not token:
                    return

                adapter = get_discord_adapter()
                await adapter.start(token)
                register_adapter(adapter)
                print("[startup] Discord adapter registered")

                async def handle_discord_message(
                    user_id: int,
                    username: str,
                    display_name: str,
                    text: str,
                ) -> str:
                    return await _process_discord_message_internal(user_id, username, display_name, text)

                asyncio.create_task(start_discord_gateway(token, handle_discord_message))
                print(f"[startup] Discord Gateway restore initiated for @{config.bot_username}")
            finally:
                db.close()
        except Exception as exc:
            print(f"[startup] Discord Gateway restore failed (non-fatal): {exc}")

    @app.on_event("startup")
    async def startup_hyper_insight_wallet_runtime() -> None:
        try:
            from services.hyper_insight_wallet_service import hyper_insight_wallet_service

            await hyper_insight_wallet_service.startup()
            print("[startup] Hyper Insight wallet runtime initialized")
        except Exception as exc:
            print(f"[startup] Hyper Insight wallet runtime failed (non-fatal): {exc}")

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        stop_runtime_monitor()
        from services.startup import shutdown_services

        shutdown_services()

    @app.on_event("shutdown")
    async def shutdown_discord_gateway() -> None:
        try:
            from services.discord_bot_service import stop_discord_gateway

            await stop_discord_gateway()
        except Exception as exc:
            print(f"[shutdown] Discord Gateway stop failed (non-fatal): {exc}")

    @app.on_event("shutdown")
    async def shutdown_hyper_insight_wallet_runtime() -> None:
        try:
            from services.hyper_insight_wallet_service import hyper_insight_wallet_service

            await hyper_insight_wallet_service.shutdown()
        except Exception as exc:
            print(f"[shutdown] Hyper Insight wallet runtime stop failed (non-fatal): {exc}")
