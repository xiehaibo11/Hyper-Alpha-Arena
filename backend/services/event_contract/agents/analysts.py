"""Analyst layer of the multi-agent signal engine.

Each analyst is a pure function `(feat_df, params) -> AnalystReport`, mirroring
TradingAgents' analyst factories. Here the analysts read 1m order-flow features
(cvd, buy_ratio, large_imb, volume).

The proven edge is a *fade* (contrarian): an exhausted aggressive-flow extreme
tends to revert. So the directional analysts each express that fade thesis
through an independent measurement — cumulative delta (cvd), taker buy-ratio,
and large-order (whale) imbalance. When several independent measurements agree
on fading the same side, conviction is high; when they split, the manager
abstains. The non-directional regime analysts (volume, consistency) gate that
conviction up or down. Selective abstention on weak/conflicted setups is what
lifts realised win rate over the single `of_cvd_fade` rule.
"""
from __future__ import annotations

import pandas as pd

from .state import AnalystReport, Direction


def _zscore(series: pd.Series, n: int) -> float:
    """Latest value's z-score over a rolling window; NaN if undefined."""
    if len(series) < n + 1:
        return float("nan")
    mean = series.rolling(n).mean().iloc[-1]
    std = series.rolling(n).std().iloc[-1]
    if not std or pd.isna(std):
        return float("nan")
    return float((series.iloc[-1] - mean) / std)


def _conf(z: float, thr: float) -> float:
    """Map |z| above threshold to a 0..1 confidence (saturating at 2*thr)."""
    if pd.isna(z):
        return 0.0
    excess = (abs(z) - thr) / max(thr, 1e-9)
    return float(max(0.0, min(1.0, excess)))


def _fade(z: float, thr: float) -> Direction:
    """Fade an extreme: high z -> short, low z -> long."""
    if pd.isna(z):
        return None
    if z >= thr:
        return "short"
    if z <= -thr:
        return "long"
    return None


# --- directional analysts (all express the fade thesis) --------------------

def cvd_fade_analyst(f: pd.DataFrame, p: dict) -> AnalystReport:
    """Primary edge: fade exhausted aggressive taker flow (high CVD z -> short)."""
    n, thr = p.get("window", 30), p.get("thr", 1.5)
    z = _zscore(f["cvd"], n)
    return AnalystReport("cvd_fade", _fade(z, thr), _conf(z, thr),
                         f"cvd z={z:.2f} thr={thr}")


def taker_fade_analyst(f: pd.DataFrame, p: dict) -> AnalystReport:
    """Fade an extreme taker buy-ratio (independent confirmation of exhaustion)."""
    hi, lo = p.get("hi", 0.62), p.get("lo", 0.38)
    r = f["buy_ratio"].iloc[-1]
    direction: Direction = None
    conf = 0.0
    if not pd.isna(r):
        if r >= hi:
            direction, conf = "short", min(1.0, (r - hi) / max(1e-9, 1 - hi))
        elif r <= lo:
            direction, conf = "long", min(1.0, (lo - r) / max(1e-9, lo))
    return AnalystReport("taker_fade", direction, conf,
                         f"buy_ratio={r:.3f}" if not pd.isna(r) else "buy_ratio=nan")


def whale_fade_analyst(f: pd.DataFrame, p: dict) -> AnalystReport:
    """Fade an extreme large-order imbalance (whale exhaustion)."""
    n = p.get("window", 30)
    thr = p.get("whale_thr", p.get("thr", 1.5))
    z = _zscore(f["large_imb"], n)
    return AnalystReport("whale_fade", _fade(z, thr), _conf(z, thr),
                         f"large_imb z={z:.2f}")


# --- regime analysts (no direction; gate conviction around 1.0) ------------

def volume_regime_analyst(f: pd.DataFrame, p: dict) -> AnalystReport:
    """Elevated volume = more trustworthy flow extreme; thin tape = discount."""
    n = p.get("window", 30)
    z = _zscore(f["volume"], n)
    if pd.isna(z):
        return AnalystReport("volume_regime", None, 1.0, "volume=nan")
    weight = max(0.5, min(1.3, 0.9 + z / 5.0))
    return AnalystReport("volume_regime", None, weight, f"vol z={z:.2f}")


def consistency_analyst(f: pd.DataFrame, p: dict) -> AnalystReport:
    """Clean, steadily-building cvd = trustworthy; choppy = discount."""
    look = p.get("consistency_look", 3)
    if len(f) < look + 1:
        return AnalystReport("consistency", None, 1.0, "insufficient")
    recent = f["cvd"].diff().tail(look)
    if (recent > 0).all() or (recent < 0).all():
        return AnalystReport("consistency", None, 1.1, "monotonic cvd")
    return AnalystReport("consistency", None, 0.9, "choppy cvd")


# The first directional analyst is treated as the "primary" edge by the manager.
ANALYSTS = [
    cvd_fade_analyst,
    taker_fade_analyst,
    whale_fade_analyst,
    volume_regime_analyst,
    consistency_analyst,
]

PRIMARY_ANALYST = "cvd_fade"


def run_analysts(f: pd.DataFrame, p: dict) -> list[AnalystReport]:
    """Execute every analyst over the feature window."""
    return [a(f, p) for a in ANALYSTS]
