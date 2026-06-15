"""Daily win-rate stats for the event-contract panel (resets at local midnight)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func

from database.connection import SessionLocal
from database.models_event_contract import EventContractOrder
from .config_store import daily_reset_tz


def _day_bounds_utc(tz_name: Optional[str] = None) -> tuple[datetime, datetime]:
    """Return [start, end) of 'today' in the configured timezone, as UTC datetimes."""
    tz_name = tz_name or daily_reset_tz()
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def daily_stats(mode: str = "live", tz_name: Optional[str] = None) -> dict:
    """Today's order counts and win rate (settled-only win rate)."""
    tz_name = tz_name or daily_reset_tz()
    start_utc, end_utc = _day_bounds_utc(tz_name)
    db = SessionLocal()
    try:
        q = db.query(EventContractOrder).filter(
            EventContractOrder.mode == mode,
            EventContractOrder.entry_time >= start_utc,
            EventContractOrder.entry_time < end_utc,
        )
        total = q.count()
        wins = q.filter(EventContractOrder.result == "win").count()
        losses = q.filter(EventContractOrder.result == "loss").count()
        pending = q.filter(EventContractOrder.result == "pending").count()
    finally:
        db.close()
    settled = wins + losses
    win_rate = round(wins / settled, 4) if settled else 0.0
    return {
        "mode": mode,
        "tz": tz_name,
        "day_start_utc": start_utc.isoformat(),
        "total": total,
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "settled": settled,
        "win_rate": win_rate,
    }
