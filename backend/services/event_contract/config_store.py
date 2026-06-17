"""DB-backed, cached config for the event-contract product.

Effective config = defaults (config.py) merged with the single overrides row in
event_contract_config. Pure `merge_config`/`params_for_cfg` are unit-tested
without a DB; the cached `get_config`/`save_config` wrap the DB row.
"""
from __future__ import annotations

import json
import threading

from . import config as _defaults

_CACHE: dict | None = None
_LOCK = threading.Lock()

_SCALAR_KEYS = ("symbols", "expiries", "payout", "default_signal", "daily_reset_tz",
                "adaptive")


def _default_config() -> dict:
    return {
        "symbols": list(_defaults.SYMBOLS),
        "expiries": list(_defaults.EXPIRIES),
        "payout": _defaults.PAYOUT,
        "default_signal": _defaults.DEFAULT_SIGNAL,
        "daily_reset_tz": _defaults.DAILY_RESET_TZ,
        # opt-in: when true and default_signal is agent_consensus, the live
        # simulator runs the multi-agent engine through the memory loop.
        "adaptive": False,
        "signal_params": {f"{s}:{e}": dict(p) for (s, e), p in _defaults.SIGNAL_PARAMS.items()},
    }


def merge_config(overrides: dict | None) -> dict:
    cfg = _default_config()
    if overrides:
        for k in _SCALAR_KEYS:
            if overrides.get(k) is not None:
                cfg[k] = overrides[k]
        if overrides.get("signal_params"):
            cfg["signal_params"] = {**cfg["signal_params"], **overrides["signal_params"]}
    return cfg


def params_for_cfg(cfg: dict, symbol: str, expiry: int) -> dict:
    return cfg["signal_params"].get(f"{symbol}:{expiry}", {"window": 30, "thr": 1.5})


def _load_overrides() -> dict | None:
    from database.connection import SessionLocal
    from database.models_event_contract_config import EventContractConfig
    db = SessionLocal()
    try:
        row = db.query(EventContractConfig).order_by(EventContractConfig.id.asc()).first()
        if not row or not row.data:
            return None
        return json.loads(row.data)
    except Exception:
        return None
    finally:
        db.close()


def get_config(force: bool = False) -> dict:
    global _CACHE
    if _CACHE is None or force:
        with _LOCK:
            _CACHE = merge_config(_load_overrides())
    return _CACHE


def save_config(patch: dict) -> dict:
    from database.connection import SessionLocal
    from database.models_event_contract_config import EventContractConfig
    db = SessionLocal()
    try:
        row = db.query(EventContractConfig).order_by(EventContractConfig.id.asc()).first()
        current = json.loads(row.data) if (row and row.data) else {}
        merged_overrides = {**current, **{k: v for k, v in patch.items() if v is not None}}
        if patch.get("signal_params"):
            merged_overrides["signal_params"] = {
                **current.get("signal_params", {}), **patch["signal_params"],
            }
        payload = json.dumps(merged_overrides)
        if row:
            row.data = payload
        else:
            db.add(EventContractConfig(data=payload))
        db.commit()
    finally:
        db.close()
    return get_config(force=True)


# Convenience accessors (dynamic at call time)
def symbols() -> list:
    return get_config()["symbols"]


def expiries() -> list:
    return get_config()["expiries"]


def payout() -> float:
    return get_config()["payout"]


def default_signal() -> str:
    return get_config()["default_signal"]


def daily_reset_tz() -> str:
    return get_config()["daily_reset_tz"]


def adaptive() -> bool:
    return bool(get_config().get("adaptive", False))


def params_for(symbol: str, expiry: int) -> dict:
    return params_for_cfg(get_config(), symbol, expiry)
