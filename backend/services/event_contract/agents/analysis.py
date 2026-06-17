"""高级 K 线分析 + 陷阱识别引擎（左侧分析面板的内容来源）。

借鉴 TradingAgents 市场分析师的指标体系与多空辩论框架：在 OHLCV 上算出趋势/动量/
波动/量能四类指标，给出做多/做空理由（bull/bear），并按知识库里的"坑"探测当前是否
踩中陷阱（RSI 极值、布林贴轨、MACD 震荡假信号、短均线锯齿、放量扭曲、流动性差、多空
打架）。输出结构化报告供前端渲染。

只用 OHLCV，因此与任意周期/任意交易所的 K 线通用；与订单流共识引擎（agents/）互补。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .knowledge import TRAP_LIBRARY


@dataclass
class AnalysisReport:
    price: float
    bias: str                       # 'long' | 'short' | 'neutral'
    confidence: float               # 0..1
    trend: dict = field(default_factory=dict)
    momentum: dict = field(default_factory=dict)
    volatility: dict = field(default_factory=dict)
    volume: dict = field(default_factory=dict)
    long_reasons: list[str] = field(default_factory=list)
    short_reasons: list[str] = field(default_factory=list)
    traps: list[dict] = field(default_factory=list)
    summary: str = ""

    def as_dict(self) -> dict:
        return {
            "price": self.price, "bias": self.bias,
            "confidence": round(self.confidence, 3),
            "trend": self.trend, "momentum": self.momentum,
            "volatility": self.volatility, "volume": self.volume,
            "long_reasons": self.long_reasons, "short_reasons": self.short_reasons,
            "traps": self.traps, "summary": self.summary,
        }


# --- 指标 -------------------------------------------------------------------

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    gain = d.clip(lower=0).rolling(n).mean()
    loss = (-d.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _last(s: pd.Series, default=float("nan")) -> float:
    return float(s.iloc[-1]) if len(s) and not pd.isna(s.iloc[-1]) else default


def _trap(tid: str, **extra) -> dict:
    t = TRAP_LIBRARY[tid]
    return {"id": tid, "title": t["title"], "detail": t["detail"],
            "severity": t["severity"], **extra}


def analyze(df: pd.DataFrame) -> AnalysisReport:
    """在 OHLCV 上做完整分析（df 升序，列：open/high/low/close/volume）。"""
    c = df["close"].astype(float)
    h, low_, v = df["high"].astype(float), df["low"].astype(float), df["volume"].astype(float)
    price = _last(c)

    ema10, sma50, sma200 = _ema(c, 10), c.rolling(50).mean(), c.rolling(200).mean()
    macd_line = _ema(c, 12) - _ema(c, 26)
    macd_sig = _ema(macd_line, 9)
    macd_hist = macd_line - macd_sig
    rsi = _rsi(c, 14)
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    bb_up, bb_lo = mid + 2 * sd, mid - 2 * sd
    tr = pd.concat([h - low_, (h - c.shift()).abs(), (low_ - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    vwma = (c * v).rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)

    # 趋势：均线排列 + EMA 斜率
    up = _last(sma50) > _last(sma200) if not pd.isna(_last(sma200)) else _last(c) > _last(sma50)
    ema_slope = _last(ema10) - float(ema10.iloc[-4]) if len(ema10) >= 4 else 0.0
    trend_dir = "up" if (up and ema_slope >= 0) else ("down" if (not up and ema_slope <= 0) else "mixed")
    strong_trend = abs(_last(sma50) - _last(sma200)) / (price or 1) > 0.004 if not pd.isna(_last(sma200)) else False

    rsi_v = _last(rsi)
    macd_cross = "bull" if _last(macd_line) > _last(macd_sig) else "bear"
    bbw = (_last(bb_up) - _last(bb_lo)) / (price or 1) if not pd.isna(_last(bb_up)) else float("nan")
    vol_z = ((_last(v) - v.rolling(20).mean().iloc[-1]) / (v.rolling(20).std().iloc[-1] or np.nan)
             if len(v) >= 21 else float("nan"))

    report = AnalysisReport(
        price=price, bias="neutral", confidence=0.0,
        trend={"direction": trend_dir, "strong": bool(strong_trend),
               "ema10": _last(ema10), "sma50": _last(sma50), "sma200": _last(sma200)},
        momentum={"rsi": rsi_v, "macd_cross": macd_cross, "macd_hist": _last(macd_hist)},
        volatility={"atr": _last(atr), "bb_upper": _last(bb_up), "bb_lower": _last(bb_lo),
                    "bb_width": bbw},
        volume={"vwma": _last(vwma), "vol_z": vol_z, "price_vs_vwma":
                ("above" if price > _last(vwma) else "below") if not pd.isna(_last(vwma)) else "n/a"},
    )

    # 多空理由（bull/bear 框架）
    L, S = report.long_reasons, report.short_reasons
    if trend_dir == "up":
        L.append("趋势向上（SMA50>SMA200 且 EMA10 上行），顺势做多")
    elif trend_dir == "down":
        S.append("趋势向下（SMA50<SMA200 且 EMA10 下行），顺势做空")
    if not pd.isna(rsi_v):
        if rsi_v <= 30:
            L.append(f"RSI={rsi_v:.0f} 超卖，有反弹动能")
        elif rsi_v >= 70:
            S.append(f"RSI={rsi_v:.0f} 超买，有回落动能")
    (L if macd_cross == "bull" else S).append(f"MACD {('金叉' if macd_cross=='bull' else '死叉')}动量{('偏多' if macd_cross=='bull' else '偏空')}")
    if not pd.isna(_last(bb_lo)) and price <= _last(bb_lo):
        L.append("触及布林下轨，统计上偏超卖")
    if not pd.isna(_last(bb_up)) and price >= _last(bb_up):
        S.append("触及布林上轨，统计上偏超买")

    # 陷阱探测（坑）
    traps = report.traps
    if not pd.isna(rsi_v) and strong_trend and (rsi_v >= 70 or rsi_v <= 30):
        traps.append(_trap("rsi_trend_trap", rsi=round(rsi_v, 1)))
    if not pd.isna(_last(bb_up)) and strong_trend and (price >= _last(bb_up) or price <= _last(bb_lo)):
        traps.append(_trap("boll_ride_trap"))
    if not pd.isna(bbw) and bbw < 0.006 and trend_dir == "mixed":
        traps.append(_trap("macd_range_trap"))
    if trend_dir == "mixed" and len(c) >= 6:
        crosses = ((ema10.tail(6) > c.tail(6)).astype(int).diff().abs().sum())
        if crosses >= 3:
            traps.append(_trap("ema_chop_trap"))
    if not pd.isna(vol_z) and vol_z >= 3:
        traps.append(_trap("volume_spike_trap", vol_z=round(float(vol_z), 1)))
    if not pd.isna(vol_z) and vol_z <= -1.2:
        traps.append(_trap("low_liquidity_trap"))
    if L and S and abs(len(L) - len(S)) <= 0:
        traps.append(_trap("conflict_trap"))

    # 综合方向与置信度
    net = len(L) - len(S)
    report.bias = "long" if net > 0 else ("short" if net < 0 else "neutral")
    high_sev = sum(1 for t in traps if t["severity"] == "high")
    base = min(1.0, abs(net) / 3.0)
    report.confidence = round(max(0.0, base - 0.25 * high_sev), 3)
    if high_sev and report.bias != "neutral":
        report.bias = "neutral"  # 踩到高危陷阱 -> 改为观望
    report.summary = _summary(report)
    return report


def _summary(r: AnalysisReport) -> str:
    d = {"long": "做多", "short": "做空", "neutral": "观望"}[r.bias]
    t = {"up": "上升", "down": "下降", "mixed": "震荡"}[r.trend["direction"]]
    parts = [f"趋势{t}", f"倾向{d}（置信 {r.confidence:.0%}）"]
    if r.traps:
        parts.append("注意" + "、".join(x["title"] for x in r.traps))
    return "；".join(parts) + "。"
