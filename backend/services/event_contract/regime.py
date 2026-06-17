"""Regime filter — only trade where the CVD-fade edge actually exists.

Derived from conditional win-rate bucketing on Binance history (2026-06-17,
614 trades): the aggregate ~59.8% edge is NOT uniform across states —
- UTC hours 12–15 are a dead zone (~51% win rate, net-negative) → skip.
- Extreme |cvd_z| (> ~4.5) weakens the edge (sweet spot is moderate z) → skip.

Filtering the dead-zone hours alone lifts win rate 59.8% → 62.3% with HIGHER net
PnL (losing trades removed) and improves out-of-sample (second-half) win rate.
The deep-research finding: short-horizon predictability is regime-dependent, so
gating *when* we trade beats hunting for a stronger single signal.

Pure-function, never raises — a False just means "no trade this minute".
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

# UTC hours with no validated edge (dead zone). Configurable via params.
DEAD_HOURS = {12, 13, 14, 15}
_MAX_ABS_Z = 4.5


def passes_regime(minute: int, feat_window: pd.DataFrame, params: dict | None = None) -> bool:
    """True if the current state is one where CVD-fade has an edge."""
    params = params or {}
    try:
        dead = set(params.get("dead_hours", DEAD_HOURS))
        hour = datetime.fromtimestamp(int(minute), tz=timezone.utc).hour
        if hour in dead:
            return False
        # Optional |cvd_z| cap (opt-in via params['max_abs_z']). Off by default:
        # the dead-hours gate alone gives the best win-rate AND net + trade count;
        # capping z barely moves win rate but halves the number of trades.
        max_abs_z = params.get("max_abs_z")
        if max_abs_z and feat_window is not None and not feat_window.empty:
            w = int(params.get("window", 45))
            cvd = feat_window["cvd"]
            if len(cvd) >= w + 1:
                tail = cvd.iloc[-w:]
                std = tail.std()
                if std and not pd.isna(std):
                    z = abs((cvd.iloc[-1] - tail.mean()) / std)
                    if pd.notna(z) and z > float(max_abs_z):
                        return False
    except Exception:
        return True  # never block on an error — fall through to "trade"
    return True
