"""Preview execution route for program bindings."""

import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import AccountProgramBinding, SignalPool, TradingProgram
from routes.program_schemas import PreviewRunResponse

router = APIRouter()

@router.post("/bindings/{binding_id}/preview-run", response_model=PreviewRunResponse)
def preview_run_binding(binding_id: int, db: Session = Depends(get_db)):
    """
    Preview-run a program binding with real account data in sandbox environment.

    Uses the bound AI Trader's real account data (positions, balance, etc.)
    to test the strategy without actually executing trades.

    The endpoint provides execution environment with real account state.
    Strategy code internally calls data_provider methods to get market data as needed.

    Returns detailed execution info including:
    - Input data snapshot (account state, positions)
    - All data queries made (indicators, flow metrics)
    - Execution logs from log() calls
    - Final decision
    """
    import time
    import traceback
    from program_trader.executor import SandboxExecutor
    from program_trader.data_provider import DataProvider
    from program_trader.models import MarketData
    from services.hyperliquid_environment import get_hyperliquid_client, get_global_trading_mode
    from database.models import HyperliquidWallet

    start_time = time.time()

    # Get binding
    binding = db.query(AccountProgramBinding).filter(
        AccountProgramBinding.id == binding_id,
        AccountProgramBinding.is_deleted != True
    ).first()
    if not binding:
        raise HTTPException(status_code=404, detail="Binding not found")

    # Get exchange from binding (default to hyperliquid for backward compatibility)
    exchange = getattr(binding, 'exchange', None) or 'hyperliquid'

    # Get program
    program = db.query(TradingProgram).filter(
        TradingProgram.id == binding.program_id,
        TradingProgram.is_deleted != True
    ).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")

    # Get wallet for this AI Trader based on current global environment
    global_environment = get_global_trading_mode(db)
    wallet = db.query(HyperliquidWallet).filter(
        HyperliquidWallet.account_id == binding.account_id,
        HyperliquidWallet.is_active == "true",
        HyperliquidWallet.environment == global_environment
    ).first()

    if not wallet:
        return PreviewRunResponse(
            success=False,
            error=f"No active {global_environment} wallet found for this AI Trader",
            execution_time_ms=(time.time() - start_time) * 1000
        )

    # Determine trigger context from binding config
    trigger_symbol = "BTC"  # Default
    trigger_type = "scheduled" if binding.scheduled_trigger_enabled else "signal"

    # If signal pools configured, use first pool's first symbol
    if binding.signal_pool_ids:
        try:
            pool_ids = json.loads(binding.signal_pool_ids)
            if pool_ids:
                pool = db.query(SignalPool).filter(SignalPool.id == pool_ids[0], SignalPool.is_deleted != True).first()
                if pool and pool.symbols:
                    symbols = pool.symbols
                    if isinstance(symbols, str):
                        symbols = json.loads(symbols)
                    if symbols:
                        trigger_symbol = symbols[0]
        except:
            pass

    # Create trading client and data provider with query recording
    try:
        if exchange == "binance":
            # Use Binance trading client
            from services.binance_trading_client import BinanceTradingClient
            from database.models import BinanceWallet as BinanceWalletModel

            from utils.encryption import decrypt_private_key

            binance_wallet = db.query(BinanceWalletModel).filter(
                BinanceWalletModel.account_id == binding.account_id,
                BinanceWalletModel.environment == global_environment,
                BinanceWalletModel.is_active == "true"
            ).first()

            if not binance_wallet or not binance_wallet.api_key_encrypted:
                return PreviewRunResponse(
                    success=False,
                    error=f"Binance {global_environment} wallet not configured for this AI Trader",
                    execution_time_ms=(time.time() - start_time) * 1000
                )

            # Decrypt API keys
            api_key = decrypt_private_key(binance_wallet.api_key_encrypted)
            secret_key = decrypt_private_key(binance_wallet.secret_key_encrypted)

            trading_client = BinanceTradingClient(
                api_key=api_key,
                secret_key=secret_key,
                environment=binance_wallet.environment or "testnet"
            )
            environment = binance_wallet.environment or "testnet"
        else:
            # Default to Hyperliquid
            trading_client = get_hyperliquid_client(
                db,
                binding.account_id,
                override_environment=wallet.environment
            )
            environment = wallet.environment

        data_provider = DataProvider(
            db,
            account_id=binding.account_id,
            environment=environment,
            trading_client=trading_client,
            record_queries=True,  # Enable query logging
            exchange=exchange  # Pass exchange to DataProvider
        )
    except Exception as e:
        return PreviewRunResponse(
            success=False,
            error=f"Failed to initialize trading client: {str(e)}",
            execution_time_ms=(time.time() - start_time) * 1000
        )

    # Build MarketData with real account data
    try:
        account_info = data_provider.get_account_info()
        positions = data_provider.get_positions()
        recent_trades = data_provider.get_recent_trades()
        open_orders = data_provider.get_open_orders()

        market_data = MarketData(
            available_balance=account_info.get("available_balance", 0.0),
            total_equity=account_info.get("total_equity", 0.0),
            used_margin=account_info.get("used_margin", 0.0),
            margin_usage_percent=account_info.get("margin_usage_percent", 0.0),
            maintenance_margin=account_info.get("maintenance_margin", 0.0),
            positions=positions,
            recent_trades=recent_trades,
            open_orders=open_orders,
            trigger_symbol=trigger_symbol,
            trigger_type=trigger_type,
            _data_provider=data_provider,
        )

        # Build input data snapshot for response
        input_data = {
            "trigger_symbol": trigger_symbol,
            "trigger_type": trigger_type,
            "environment": environment,
            "exchange": exchange,
            "signal_pool_name": "",  # Preview run doesn't have signal context
            "pool_logic": "OR",
            "triggered_signals": [],
            "trigger_market_regime": None,
            "max_leverage": 20,  # Default max
            "default_leverage": 3,  # Default
            "available_balance": account_info.get("available_balance", 0.0),
            "total_equity": account_info.get("total_equity", 0.0),
            "used_margin": account_info.get("used_margin", 0.0),
            "margin_usage_percent": account_info.get("margin_usage_percent", 0.0),
            "positions": {k: {"side": v.side, "size": v.size, "entry_price": v.entry_price,
                            "unrealized_pnl": v.unrealized_pnl, "leverage": getattr(v, 'leverage', None)} for k, v in positions.items()},
            "positions_count": len(positions),
            "open_orders": [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "side": o.side,
                    "direction": o.direction,
                    "order_type": o.order_type,
                    "size": o.size,
                    "price": o.price,
                    "trigger_price": o.trigger_price,
                    "reduce_only": o.reduce_only,
                    "timestamp": o.timestamp,
                }
                for o in open_orders
            ],
            "open_orders_count": len(open_orders),
            "recent_trades_count": len(recent_trades),
        }
    except Exception as e:
        return PreviewRunResponse(
            success=False,
            error=f"Failed to load account data: {str(e)}",
            execution_time_ms=(time.time() - start_time) * 1000
        )

    # Execute in sandbox
    try:
        # Get params override if any
        params = {}
        if binding.params_override:
            try:
                params = json.loads(binding.params_override)
            except:
                pass

        executor = SandboxExecutor(timeout_seconds=5)
        result = executor.execute(program.code, market_data, params=params)

        execution_time = (time.time() - start_time) * 1000

        if result.success and result.decision:
            return PreviewRunResponse(
                success=True,
                input_data=input_data,
                data_queries=data_provider.get_query_log(),
                execution_logs=result.logs if hasattr(result, 'logs') else [],
                decision=result.decision.to_dict(),
                execution_time_ms=execution_time
            )
        else:
            return PreviewRunResponse(
                success=False,
                error=result.error or "Unknown execution error",
                input_data=input_data,
                data_queries=data_provider.get_query_log(),
                execution_logs=result.logs if hasattr(result, 'logs') else [],
                execution_time_ms=execution_time
            )
    except Exception as e:
        return PreviewRunResponse(
            success=False,
            error=f"Execution failed: {str(e)}",
            input_data=input_data,
            data_queries=data_provider.get_query_log(),
            execution_time_ms=(time.time() - start_time) * 1000
        )
