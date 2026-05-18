"""List/search tools used by Hyper AI."""

import json
import logging
import os
import requests

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def execute_list_traders(db: Session, trader_id: int = None) -> str:
    """List all AI Traders with bindings, wallet status, and trading status.
    Pass trader_id to get a single trader's detail."""
    from database.models import (
        Account, HyperliquidWallet, BinanceWallet,
        AccountProgramBinding, AccountPromptBinding,
        TradingProgram, PromptTemplate
    )

    try:
        query = db.query(Account).filter(
            Account.is_active == "true",
            Account.account_type == "AI",
            Account.is_deleted != True
        )
        if trader_id:
            query = query.filter(Account.id == trader_id)
        accounts = query.all()
        if trader_id and not accounts:
            return json.dumps({"error": f"AI Trader {trader_id} not found"})

        traders = []
        for acc in accounts:
            # Wallet info
            hl_wallets = db.query(HyperliquidWallet).filter(
                HyperliquidWallet.account_id == acc.id
            ).all()
            bn_wallets = db.query(BinanceWallet).filter(
                BinanceWallet.account_id == acc.id
            ).all()

            wallet_info = []
            for w in hl_wallets:
                wallet_info.append({
                    "exchange": "hyperliquid",
                    "environment": w.environment
                })
            for w in bn_wallets:
                wallet_info.append({
                    "exchange": "binance",
                    "environment": w.environment
                })

            # Prompt binding
            prompt_binding = None
            pb = db.query(AccountPromptBinding).filter(
                AccountPromptBinding.account_id == acc.id,
                AccountPromptBinding.is_deleted != True
            ).first()
            if pb:
                tpl = db.get(PromptTemplate, pb.prompt_template_id)
                prompt_binding = {
                    "prompt_id": pb.prompt_template_id,
                    "prompt_name": tpl.name if tpl else "Unknown"
                }

            # Program bindings
            prog_bindings = db.query(AccountProgramBinding).filter(
                AccountProgramBinding.account_id == acc.id,
                AccountProgramBinding.is_deleted != True
            ).all()
            program_bindings = []
            for pgb in prog_bindings:
                prog = db.get(TradingProgram, pgb.program_id)
                pool_ids = json.loads(pgb.signal_pool_ids) if pgb.signal_pool_ids else []
                program_bindings.append({
                    "binding_id": pgb.id,
                    "program_id": pgb.program_id,
                    "program_name": prog.name if prog else "Unknown",
                    "exchange": pgb.exchange or "hyperliquid",
                    "signal_pool_ids": pool_ids,
                    "trigger_interval": pgb.trigger_interval,
                    "is_active": pgb.is_active
                })

            traders.append({
                "trader_id": acc.id,
                "name": acc.name,
                "model": acc.model,
                "auto_trading_enabled": acc.auto_trading_enabled == "true",
                "wallets": wallet_info,
                "prompt_binding": prompt_binding,
                "program_bindings": program_bindings
            })

        return json.dumps({"traders": traders, "count": len(traders)}, indent=2)

    except Exception as e:
        logger.error(f"[list_traders] Error: {e}")
        return json.dumps({"error": str(e)})


def execute_list_signal_pools(db: Session, pool_id: int = None) -> str:
    """List all signal pools. Pass pool_id for single pool detail."""
    from database.models import SignalPool, SignalDefinition

    try:
        query = db.query(SignalPool).filter(SignalPool.is_deleted != True)
        if pool_id:
            query = query.filter(SignalPool.id == pool_id)
        pools = query.all()
        if pool_id and not pools:
            return json.dumps({"error": f"Signal pool {pool_id} not found"})

        result = []
        for pool in pools:
            # Parse signal_ids
            signal_ids = []
            if pool.signal_ids:
                try:
                    raw = pool.signal_ids
                    signal_ids = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    signal_ids = []

            # Parse symbols
            symbols = []
            if pool.symbols:
                try:
                    raw = pool.symbols
                    symbols = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    symbols = []

            source_type = pool.source_type or "market_signals"
            source_config = {}
            if getattr(pool, "source_config", None):
                try:
                    raw = pool.source_config
                    source_config = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    source_config = {}

            # Get signal details from trigger_condition
            signals = []
            for sid in signal_ids:
                sig = db.query(SignalDefinition).filter(
                    SignalDefinition.id == sid,
                    SignalDefinition.is_deleted != True
                ).first()
                if sig:
                    cond = {}
                    if sig.trigger_condition:
                        try:
                            raw = sig.trigger_condition
                            cond = json.loads(raw) if isinstance(raw, str) else raw
                        except Exception:
                            cond = {"raw": sig.trigger_condition}
                    signals.append({
                        "signal_id": sig.id,
                        "signal_name": sig.signal_name,
                        "trigger_condition": cond,
                        "enabled": sig.enabled
                    })

            result.append({
                "pool_id": pool.id,
                "name": pool.pool_name,
                "symbols": symbols,
                "exchange": pool.exchange or "hyperliquid",
                "source_type": source_type,
                "logic": pool.logic or "OR",
                "enabled": pool.enabled,
                "signals": signals,
                "source_config": source_config if source_type == "wallet_tracking" else {},
            })

        return json.dumps({"signal_pools": result, "count": len(result)}, indent=2)

    except Exception as e:
        logger.error(f"[list_signal_pools] Error: {e}")
        return json.dumps({"error": str(e)})


def execute_analyze_tracked_address(db: Session, address: str) -> str:
    """Fetch protected Hyper Insight address detail for Hyper AI analysis."""
    from services.hyper_insight_wallet_service import hyper_insight_wallet_service

    normalized = (address or "").strip().lower()
    if not normalized:
        return json.dumps({"error": "address is required"})

    snapshot = hyper_insight_wallet_service.get_status_snapshot()
    synced_addresses = [str(item).strip().lower() for item in (snapshot.get("synced_addresses") or []) if str(item).strip()]
    synced_set = set(synced_addresses)

    access_token = _get_hyper_insight_access_token(db)
    if not access_token:
        return json.dumps({
            "error": "Please log in to Hyper Alpha Arena before using Hyper Insight analysis.",
            "next_steps": [
                "Log in to Hyper Alpha Arena with your linked account first.",
                "After login, open Signals > Wallet Tracking and make sure your tracked wallets have synced before asking for wallet analysis."
            ]
        }, ensure_ascii=False)

    if snapshot.get("status") != "connected":
        return json.dumps({
            "error": "Wallet Tracking is not connected yet in Hyper Alpha Arena.",
            "next_steps": [
                "Open Hyper Alpha Arena and use the left sidebar to enter Signals > Wallet Tracking.",
                "Enable sync and wait until the connection status becomes connected before requesting wallet analysis."
            ]
        }, ensure_ascii=False)

    if normalized not in synced_set:
        return json.dumps({
            "error": "This wallet is not currently in your synced wallet list.",
            "next_steps": [
                "Track the wallet on https://hyper.akooi.com/ if it is not already tracked there.",
                "Then return to Hyper Alpha Arena > Signals > Wallet Tracking and wait until the wallet appears in the synced wallet list."
            ]
        }, ensure_ascii=False)

    base_url = os.getenv("HYPER_INSIGHT_API_BASE_URL", "https://hyper.akooi.com").rstrip("/")
    url = f"{base_url}/api/s2s/addresses/{normalized}"
    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 404:
            return json.dumps({
                "error": "This wallet is temporarily unavailable for detailed analysis right now.",
                "next_steps": [
                    "Wallet Tracking is already connected and the wallet is already in your synced list.",
                    "This means the current failure is system-side rather than a wallet tracking problem. Please retry later."
                ]
            }, ensure_ascii=False)
        if response.status_code == 401:
            return json.dumps({
                "error": "Your Hyper Insight session in Hyper Alpha Arena is no longer valid.",
                "next_steps": [
                    "Refresh Hyper Alpha Arena, open Signals > Wallet Tracking, and enable sync again.",
                    "After the tracked wallet list is visible again, retry the wallet analysis request."
                ]
            }, ensure_ascii=False)
        if response.status_code == 403:
            return json.dumps({
                "error": "Tracked wallet analysis is temporarily unavailable right now.",
                "next_steps": [
                    "Wallet Tracking is connected and the wallet is already in your synced list.",
                    "This means the current failure is system-side rather than a wallet tracking problem. Please retry later."
                ]
            }, ensure_ascii=False)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            payload.setdefault(
                "analysis_limit_note",
                "Recent fills are limited to the latest window and do not represent the address's complete all-time trade history.",
            )
        return json.dumps(payload, indent=2, ensure_ascii=False)
    except requests.RequestException as exc:
        logger.error("[analyze_tracked_address] Error fetching %s: %s", normalized, exc)
        return json.dumps({
            "error": "Failed to fetch Hyper Insight address detail right now.",
            "next_steps": [
                "If Wallet Tracking is connected and the wallet is already in your synced list, then the current failure is system-side.",
                "Please retry later."
            ]
        }, ensure_ascii=False)


def execute_list_strategies(db: Session, strategy_id: int = None, strategy_type: str = None) -> str:
    """List all prompts and programs with binding status.
    Pass strategy_id + strategy_type to get full content of a specific strategy."""
    from database.models import (
        PromptTemplate, TradingProgram,
        AccountProgramBinding, AccountPromptBinding, Account
    )

    try:
        # Single strategy detail mode
        if strategy_id and strategy_type:
            if strategy_type == "prompt":
                tpl = db.query(PromptTemplate).filter(
                    PromptTemplate.id == strategy_id,
                    PromptTemplate.is_deleted == "false"
                ).first()
                if not tpl:
                    return json.dumps({"error": f"Prompt {strategy_id} not found"})
                bindings = db.query(AccountPromptBinding).filter(
                    AccountPromptBinding.prompt_template_id == tpl.id,
                    AccountPromptBinding.is_deleted != True
                ).all()
                bound_traders = []
                for b in bindings:
                    acc = db.get(Account, b.account_id)
                    if acc:
                        bound_traders.append({"trader_id": acc.id, "trader_name": acc.name})
                return json.dumps({
                    "prompt_id": tpl.id,
                    "name": tpl.name,
                    "description": getattr(tpl, "description", None),
                    "template_text": tpl.template_text,
                    "bound_traders": bound_traders
                }, indent=2)
            elif strategy_type == "program":
                prog = db.query(TradingProgram).filter(
                    TradingProgram.id == strategy_id,
                    TradingProgram.is_deleted != True
                ).first()
                if not prog:
                    return json.dumps({"error": f"Program {strategy_id} not found"})
                bindings = db.query(AccountProgramBinding).filter(
                    AccountProgramBinding.program_id == prog.id,
                    AccountProgramBinding.is_deleted != True
                ).all()
                bound_traders = []
                for b in bindings:
                    acc = db.get(Account, b.account_id)
                    if acc:
                        bound_traders.append({
                            "trader_id": acc.id, "trader_name": acc.name,
                            "is_active": b.is_active
                        })
                return json.dumps({
                    "program_id": prog.id,
                    "name": prog.name,
                    "description": prog.description,
                    "code": prog.code,
                    "bound_traders": bound_traders
                }, indent=2)

        # List all mode (original behavior)
        # Prompts
        templates = db.query(PromptTemplate).filter(
            PromptTemplate.is_deleted == "false"
        ).all()
        prompts = []
        for tpl in templates:
            bindings = db.query(AccountPromptBinding).filter(
                AccountPromptBinding.prompt_template_id == tpl.id,
                AccountPromptBinding.is_deleted != True
            ).all()
            bound_traders = []
            for b in bindings:
                acc = db.get(Account, b.account_id)
                if acc:
                    bound_traders.append({"trader_id": acc.id, "trader_name": acc.name})
            prompts.append({
                "prompt_id": tpl.id,
                "name": tpl.name,
                "description": getattr(tpl, "description", None),
                "bound_traders": bound_traders
            })

        # Programs
        programs_db = db.query(TradingProgram).filter(TradingProgram.is_deleted != True).all()
        programs = []
        for prog in programs_db:
            bindings = db.query(AccountProgramBinding).filter(
                AccountProgramBinding.program_id == prog.id,
                AccountProgramBinding.is_deleted != True
            ).all()
            bound_traders = []
            for b in bindings:
                acc = db.get(Account, b.account_id)
                if acc:
                    bound_traders.append({
                        "trader_id": acc.id,
                        "trader_name": acc.name,
                        "is_active": b.is_active
                    })
            programs.append({
                "program_id": prog.id,
                "name": prog.name,
                "description": prog.description,
                "bound_traders": bound_traders
            })

        return json.dumps({
            "prompts": prompts,
            "programs": programs,
            "prompt_count": len(prompts),
            "program_count": len(programs)
        }, indent=2)

    except Exception as e:
        logger.error(f"[list_strategies] Error: {e}")
        return json.dumps({"error": str(e)})


# =============================================================================
# Binding Tools: assemble components
# =============================================================================
