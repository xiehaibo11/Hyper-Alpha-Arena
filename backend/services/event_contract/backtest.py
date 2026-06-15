"""Historical backtest for the event-contract signal system.

Replays 1m klines: at each closed candle a strategy may fire; we enter at the
NEXT candle's open and settle `expiry_minutes` later (open-to-open, looked up by
timestamp so data gaps are skipped). Reports win rate and flat-stake net P&L.
"""
from __future__ import annotations

from typing import Optional

from .data import CANDLE_SECONDS, load_klines
from .strategies import STRATEGIES, evaluate


def _empty(exchange, symbol, expiry_minutes, strategy, payout, candles=0, reason=""):
    return {
        "exchange": exchange, "symbol": symbol, "expiry_minutes": expiry_minutes,
        "strategy": strategy, "total": 0, "wins": 0, "losses": 0,
        "win_rate": 0.0, "net_pnl": 0.0, "payout": payout,
        "breakeven_win_rate": round(1.0 / (1.0 + payout), 4),
        "candles": candles, "equity_curve": [], "reason": reason,
    }


def run_backtest(
    exchange: str,
    symbol: str,
    expiry_minutes: int,
    strategy: str,
    params: Optional[dict] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    payout: float = 0.8,
    max_candles: int = 20000,
) -> dict:
    strat = STRATEGIES.get(strategy)
    if strat is None:
        return _empty(exchange, symbol, expiry_minutes, strategy, payout, reason="unknown strategy")

    df = load_klines(exchange, symbol, start_ts, end_ts, limit=max_candles)
    n = len(df)
    if n < strat.min_rows + expiry_minutes + 2:
        return _empty(exchange, symbol, expiry_minutes, strategy, payout, n, "insufficient data")

    ts_open = dict(zip(df["timestamp"].tolist(), df["open"].tolist()))
    timestamps = df["timestamp"].tolist()
    lookback = max(120, strat.min_rows + 10)
    expiry_s = expiry_minutes * 60

    total = wins = losses = 0
    cum = 0.0
    equity: list[tuple[int, float]] = []

    for i in range(strat.min_rows, n):
        window = df.iloc[max(0, i - lookback): i + 1]
        sig = evaluate(strategy, window, params)
        if not sig:
            continue
        entry_ts = timestamps[i] + CANDLE_SECONDS
        settle_ts = entry_ts + expiry_s
        ep = ts_open.get(entry_ts)
        sp = ts_open.get(settle_ts)
        if ep is None or sp is None:
            continue
        won = sp > ep if sig == "long" else sp < ep
        total += 1
        if won:
            wins += 1
            cum += payout
        else:
            losses += 1
            cum -= 1.0
        equity.append((settle_ts, round(cum, 4)))

    win_rate = round(wins / total, 4) if total else 0.0
    # sample equity curve down to ~150 points
    step = max(1, len(equity) // 150)
    curve = [{"t": t, "equity": e} for t, e in equity[::step]]

    return {
        "exchange": exchange, "symbol": symbol, "expiry_minutes": expiry_minutes,
        "strategy": strategy, "params": {**strat.default_params, **(params or {})},
        "total": total, "wins": wins, "losses": losses,
        "win_rate": win_rate, "net_pnl": round(cum, 4), "payout": payout,
        "breakeven_win_rate": round(1.0 / (1.0 + payout), 4),
        "candles": n,
        "start_ts": int(timestamps[0]), "end_ts": int(timestamps[-1]),
        "equity_curve": curve,
    }


def compare_strategies(
    exchange: str, symbol: str, expiry_minutes: int, **kwargs
) -> list[dict]:
    """Run every registered strategy and rank by win rate (for picking the best)."""
    results = [
        run_backtest(exchange, symbol, expiry_minutes, name, **kwargs)
        for name in STRATEGIES
    ]
    return sorted(results, key=lambda r: r["win_rate"], reverse=True)
