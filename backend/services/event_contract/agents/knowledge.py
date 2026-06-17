"""交易知识库 —— 借鉴自 TradingAgents 各 agent 提示词里的交易智慧。

把"高级交易"里每个指标的【用法】和【坑/陷阱】固化成数据，给左侧分析面板用。
每个指标都带一个 trap（不能踩的坑），这是 TradingAgents 提示词里反复强调的：
指标会骗人，强趋势里超买不一定跌、贴布林带不一定反转、震荡市 MACD 全是假信号。

INDICATOR_CATALOG: 指标说明 + 坑（中文为主）。
TRAP_LIBRARY: 陷阱图条目（由 analysis.py 的探测器按行情触发）。
"""
from __future__ import annotations

# --- 指标库（含每个指标的"坑"）------------------------------------------------

INDICATOR_CATALOG: list[dict] = [
    {"key": "ema10", "name": "EMA10 快速均线", "cat": "trend",
     "measures": "短期动量",
     "usage": "捕捉动量快速变化、潜在入场点",
     "trap": "震荡市里噪音大、易被反复打脸；要配合 50/200 均线过滤假信号"},
    {"key": "sma50", "name": "SMA50 中期均线", "cat": "trend",
     "measures": "中期趋势方向",
     "usage": "判断趋势方向、充当动态支撑/阻力",
     "trap": "滞后于价格；别单独用它做即时入场"},
    {"key": "sma200", "name": "SMA200 长期均线", "cat": "trend",
     "measures": "长期趋势基准",
     "usage": "确认大方向、识别金叉/死叉",
     "trap": "反应很慢，只适合定方向，不适合频繁交易入场"},
    {"key": "macd", "name": "MACD", "cat": "momentum",
     "measures": "动量（双 EMA 差值）",
     "usage": "看金叉/死叉与背离，判断趋势转折",
     "trap": "震荡/低波动市里假信号极多，必须用别的指标确认"},
    {"key": "rsi", "name": "RSI 相对强弱", "cat": "momentum",
     "measures": "动量、超买超卖",
     "usage": "70/30 阈值 + 背离判断反转",
     "trap": "★强趋势中 RSI 会长期钉在极值——超买不等于要跌、超卖不等于要涨，别逆势抄底摸顶"},
    {"key": "boll", "name": "布林带", "cat": "volatility",
     "measures": "波动率通道（20SMA±2σ）",
     "usage": "上/下轨判断超买超卖、突破区间",
     "trap": "★强趋势里价格会贴着上/下轨走——贴轨不是反转信号，逆势进去就是陷阱"},
    {"key": "atr", "name": "ATR 真实波幅", "cat": "volatility",
     "measures": "波动幅度大小",
     "usage": "设止损距离、按波动调仓位",
     "trap": "只测波动不测方向；ATR 高只说明风险大，不代表会涨或跌"},
    {"key": "vwma", "name": "VWMA 量加权均线", "cat": "volume",
     "measures": "结合成交量的价格动量",
     "usage": "用成交量确认趋势真假",
     "trap": "放量异动会短暂扭曲 VWMA，需用下一根确认"},
]

# --- 陷阱图条目（探测器命中时显示）--------------------------------------------

TRAP_LIBRARY: dict[str, dict] = {
    "rsi_trend_trap": {
        "title": "RSI 极值陷阱",
        "detail": "强趋势中 RSI 长期超买/超卖，逆势抄底/摸顶大概率被埋。顺趋势或观望。",
        "severity": "high"},
    "boll_ride_trap": {
        "title": "布林带贴轨陷阱",
        "detail": "价格紧贴上/下轨且趋势强，贴轨是趋势延续而非反转，别逆势开单。",
        "severity": "high"},
    "macd_range_trap": {
        "title": "MACD 震荡假信号",
        "detail": "低波动/横盘里 MACD 交叉多为噪音，单凭交叉入场会被反复打脸。",
        "severity": "medium"},
    "ema_chop_trap": {
        "title": "短均线锯齿陷阱",
        "detail": "横盘里 EMA10 反复穿越价格，频繁信号都是假的，需更长均线过滤。",
        "severity": "medium"},
    "volume_spike_trap": {
        "title": "放量异动扭曲",
        "detail": "成交量瞬间暴增扭曲了量价指标，等下一根确认再动手。",
        "severity": "low"},
    "low_liquidity_trap": {
        "title": "低流动性陷阱",
        "detail": "近端成交极清淡，任何信号都不可靠，置信度按低处理。",
        "severity": "medium"},
    "conflict_trap": {
        "title": "多空信号打架",
        "detail": "趋势与动量/量能互相矛盾，证据不一致时应弃单，等方向明朗。",
        "severity": "high"},
}
