"""Factor prompt-context builders for AI decisions."""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _build_factor_context(
    factor_vars: List[tuple], environment: str, exchange: str
) -> Dict[str, str]:
    """
    Build factor context dict for prompt template variables.
    Each variable resolves to a text block with value + effectiveness.
    """
    from database.connection import SessionLocal
    from program_trader.data_provider import compute_factor_snapshot
    from services.market_data import get_kline_data

    context = {}
    db = SessionLocal()
    try:
        # Sync rule: Prompt factor variables must stay aligned with Program
        # live get_factor() and Program backtest get_factor().
        for symbol, period, factor_name, var_name in factor_vars:
            try:
                market = "binance" if exchange == "binance" else "CRYPTO"
                snapshot = compute_factor_snapshot(
                    db=db,
                    symbol=symbol,
                    factor_name=factor_name,
                    period=period,
                    exchange=exchange,
                    klines_loader=lambda requested_period, count: get_kline_data(
                        symbol,
                        market=market,
                        period=requested_period,
                        count=count,
                        environment=environment,
                        persist=False,
                    ) or [],
                    include_effectiveness=True,
                )

                if snapshot.get("error"):
                    context[var_name] = snapshot["error"]
                    continue

                desc = snapshot.get("description") or ""
                parts = [
                    f"name={factor_name}(id={snapshot.get('id')})",
                    f"period={period}",
                    f"expr={snapshot.get('expression')}",
                ]
                if desc:
                    parts.append(f"desc={desc}")
                value = snapshot.get("value")
                parts.append(f"value={value:.4f}" if value is not None else "value=N/A")
                if snapshot.get("ic") is not None:
                    parts.append(f"IC={float(snapshot['ic']):.4f}")
                if snapshot.get("icir") is not None:
                    parts.append(f"ICIR={float(snapshot['icir']):.2f}")
                if snapshot.get("win_rate") is not None:
                    parts.append(f"WinRate={float(snapshot['win_rate']):.1f}%")
                if snapshot.get("decay_half_life_hours") is not None:
                    dh = int(snapshot["decay_half_life_hours"])
                    parts.append("Persistent" if dh == -1 else f"Decay={dh}h")

                context[var_name] = " | ".join(parts)
            except Exception as e:
                logger.warning(f"Failed to compute factor {factor_name} for {symbol}/{period}: {e}")
                context[var_name] = f"Error computing factor"

    finally:
        db.close()

    return context
