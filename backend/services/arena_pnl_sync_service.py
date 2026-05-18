"""
Arena PnL synchronization service.

The route layer delegates here so exchange fill fetching and sync bookkeeping
stay testable and independent from FastAPI.
"""

import logging
from collections import defaultdict
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.models import AIDecisionLog, BinanceWallet, HyperliquidWallet, ProgramExecutionLog
from database.snapshot_connection import SnapshotSessionLocal
from services.arena_pnl_fill_processor import process_fills_for_environment
from services.hyperliquid_environment import get_hyperliquid_client

logger = logging.getLogger(__name__)


def check_pnl_sync_status(db: Session, trading_mode: Optional[str] = None) -> dict:
    """
    Check if there are trades that need PnL synchronization.

    Returns the count of unsynchronized trades for both AI Decision and Program.
    Only counts trades that have order IDs.
    """
    ai_query = db.query(AIDecisionLog).filter(
        AIDecisionLog.operation.in_(["buy", "sell", "close"]),
        AIDecisionLog.executed == "true",
        AIDecisionLog.pnl_updated_at == None,
        or_(
            AIDecisionLog.hyperliquid_order_id != None,
            AIDecisionLog.tp_order_id != None,
            AIDecisionLog.sl_order_id != None,
        ),
    )

    if trading_mode:
        if trading_mode == "paper":
            ai_query = ai_query.filter(AIDecisionLog.hyperliquid_environment == None)
        else:
            ai_query = ai_query.filter(AIDecisionLog.hyperliquid_environment == trading_mode)
    else:
        ai_query = ai_query.filter(AIDecisionLog.hyperliquid_environment.isnot(None))

    ai_unsync_count = ai_query.count()

    prog_query = db.query(ProgramExecutionLog).filter(
        ProgramExecutionLog.success == True,
        ProgramExecutionLog.decision_action.in_(["buy", "sell", "close"]),
        ProgramExecutionLog.pnl_updated_at == None,
        or_(
            ProgramExecutionLog.hyperliquid_order_id != None,
            ProgramExecutionLog.tp_order_id != None,
            ProgramExecutionLog.sl_order_id != None,
        ),
    )

    if trading_mode:
        if trading_mode == "paper":
            prog_query = prog_query.filter(ProgramExecutionLog.environment == None)
        else:
            prog_query = prog_query.filter(ProgramExecutionLog.environment == trading_mode)
    else:
        prog_query = prog_query.filter(ProgramExecutionLog.environment.isnot(None))

    prog_unsync_count = prog_query.count()
    total_unsync = ai_unsync_count + prog_unsync_count

    return {
        "needs_sync": total_unsync > 0,
        "unsync_count": total_unsync,
        "ai_unsync_count": ai_unsync_count,
        "program_unsync_count": prog_unsync_count,
    }


def update_pnl_data(db: Session) -> dict:
    """
    Update realized PnL and fee data for trades by fetching exchange fills.

    This mutates both the app database and snapshot database, so callers should
    reserve it for explicit sync operations.
    """
    result = {
        "success": True,
        "hyperliquid": {},
        "binance": {},
        "errors": [],
    }

    snapshot_db = SnapshotSessionLocal()

    try:
        hl_wallets = db.query(HyperliquidWallet).all()
        if hl_wallets:
            hl_wallet_configs = {}
            fetched_historical_addresses = set()
            for wallet in hl_wallets:
                key = (wallet.account_id, wallet.environment)
                if key not in hl_wallet_configs:
                    hl_wallet_configs[key] = wallet

            all_hl_fills_by_env = defaultdict(list)
            for (account_id, environment), wallet in hl_wallet_configs.items():
                try:
                    client = get_hyperliquid_client(db, account_id, override_environment=environment)
                    fills = client._get_user_fills(db)
                    all_hl_fills_by_env[environment].extend(fills)
                    logger.info(f"[Hyperliquid] Fetched {len(fills)} fills for account {account_id} on {environment}")

                    current_query_addresses = {client.query_address.lower()}
                    if getattr(client, "wallet_address", None):
                        current_query_addresses.add(client.wallet_address.lower())

                    historical_addresses = set()

                    ai_rows = db.query(AIDecisionLog.wallet_address).filter(
                        AIDecisionLog.account_id == account_id,
                        AIDecisionLog.hyperliquid_environment == environment,
                        AIDecisionLog.executed == "true",
                        AIDecisionLog.pnl_updated_at == None,
                        AIDecisionLog.wallet_address.isnot(None),
                        or_(
                            AIDecisionLog.hyperliquid_order_id != None,
                            AIDecisionLog.tp_order_id != None,
                            AIDecisionLog.sl_order_id != None,
                        ),
                    ).distinct().all()
                    historical_addresses.update(
                        addr.lower()
                        for (addr,) in ai_rows
                        if addr and addr.lower() not in current_query_addresses
                    )

                    prog_rows = db.query(ProgramExecutionLog.wallet_address).filter(
                        ProgramExecutionLog.account_id == account_id,
                        ProgramExecutionLog.environment == environment,
                        ProgramExecutionLog.success == True,
                        ProgramExecutionLog.pnl_updated_at == None,
                        ProgramExecutionLog.wallet_address.isnot(None),
                        or_(
                            ProgramExecutionLog.hyperliquid_order_id != None,
                            ProgramExecutionLog.tp_order_id != None,
                            ProgramExecutionLog.sl_order_id != None,
                        ),
                    ).distinct().all()
                    historical_addresses.update(
                        addr.lower()
                        for (addr,) in prog_rows
                        if addr and addr.lower() not in current_query_addresses
                    )

                    for historical_address in sorted(historical_addresses):
                        historical_key = (environment, historical_address)
                        if historical_key in fetched_historical_addresses:
                            continue
                        try:
                            historical_fills = client.sdk_info.user_fills(historical_address)
                            all_hl_fills_by_env[environment].extend(historical_fills)
                            fetched_historical_addresses.add(historical_key)
                            logger.info(
                                f"[Hyperliquid] Fetched {len(historical_fills)} historical fills "
                                f"for address {historical_address} on {environment}"
                            )
                        except Exception as historical_err:
                            logger.warning(
                                f"[Hyperliquid] Failed to fetch historical fills for address "
                                f"{historical_address} on {environment}: {historical_err}"
                            )
                except Exception as e:
                    error_msg = f"[Hyperliquid] Failed to fetch fills for account {account_id} on {environment}: {e}"
                    logger.warning(error_msg)
                    result["errors"].append(error_msg)

            for environment, fills in all_hl_fills_by_env.items():
                env_result = process_fills_for_environment(
                    db, snapshot_db, environment, fills, hl_wallet_configs, exchange="hyperliquid"
                )
                result["hyperliquid"][environment] = env_result

        bn_wallets = db.query(BinanceWallet).filter(BinanceWallet.is_active == "true").all()
        if bn_wallets:
            from services.binance_trading_client import BinanceTradingClient
            from utils.encryption import decrypt_private_key

            bn_wallet_configs = {}
            for wallet in bn_wallets:
                key = (wallet.account_id, wallet.environment)
                if key not in bn_wallet_configs:
                    bn_wallet_configs[key] = wallet

            all_bn_fills_by_env = defaultdict(list)
            for (account_id, environment), wallet in bn_wallet_configs.items():
                try:
                    api_key = decrypt_private_key(wallet.api_key_encrypted)
                    secret_key = decrypt_private_key(wallet.secret_key_encrypted)
                    client = BinanceTradingClient(api_key, secret_key, environment)
                    fills = client.get_user_fills()
                    all_bn_fills_by_env[environment].extend(fills)
                    logger.info(f"[Binance] Fetched {len(fills)} fills for account {account_id} on {environment}")
                except Exception as e:
                    error_msg = f"[Binance] Failed to fetch fills for account {account_id} on {environment}: {e}"
                    logger.warning(error_msg)
                    result["errors"].append(error_msg)

            for environment, fills in all_bn_fills_by_env.items():
                env_result = process_fills_for_environment(
                    db, snapshot_db, environment, fills, bn_wallet_configs, exchange="binance"
                )
                result["binance"][environment] = env_result

        snapshot_db.commit()
        db.commit()

    except Exception as e:
        logger.error(f"Error updating PnL data: {e}", exc_info=True)
        result["success"] = False
        result["errors"].append(str(e))
        snapshot_db.rollback()
        db.rollback()
    finally:
        snapshot_db.close()

    return result
