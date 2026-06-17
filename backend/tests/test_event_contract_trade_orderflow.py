"""Unit tests for trade-aggregation order-flow (Crypto.com / Gate CVD).

All stubbed — no network, no DB. We exercise:
- aggregate_trades minute bucketing (buy -> buy side, sell -> sell side),
- supports_trade_orderflow dispatch,
- adapter fetch_trades parsing via monkeypatched requests.get.
"""
from __future__ import annotations

from services.event_contract.trade_orderflow import (
    aggregate_trades,
    supports_trade_orderflow,
)


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_aggregate_trades_minute_buckets():
    m0 = 0          # minute 0 -> bucket ts 0
    m1 = 60_000     # minute 1 -> bucket ts 60000
    trades = [
        {"ts_ms": 1_000, "price": 100.0, "size": 2.0, "side": "buy", "notional": 200.0},
        {"ts_ms": 30_000, "price": 110.0, "size": 1.0, "side": "sell", "notional": 110.0},
        {"ts_ms": 61_000, "price": 120.0, "size": 3.0, "side": "buy", "notional": 360.0},
        {"ts_ms": 90_000, "price": 90.0, "size": 4.0, "side": "sell", "notional": 360.0},
    ]
    out = aggregate_trades(trades)
    assert set(out.keys()) == {m0, m1}

    b0 = out[m0]
    assert b0["tbv"] == 2.0 and b0["tsv"] == 1.0
    assert b0["tbc"] == 1 and b0["tsc"] == 1
    assert b0["tbn"] == 200.0 and b0["tsn"] == 110.0
    assert b0["high"] == 110.0 and b0["low"] == 100.0

    b1 = out[m1]
    assert b1["tbv"] == 3.0 and b1["tsv"] == 4.0
    assert b1["high"] == 120.0 and b1["low"] == 90.0


def test_aggregate_trades_empty():
    assert aggregate_trades([]) == {}


def test_supports_trade_orderflow():
    assert supports_trade_orderflow("gate") is True
    assert supports_trade_orderflow("gateio") is True
    assert supports_trade_orderflow("crypto_com") is True
    assert supports_trade_orderflow("cryptocom") is True
    assert supports_trade_orderflow("binance") is False
    assert supports_trade_orderflow("") is False
    assert supports_trade_orderflow(None) is False


def test_crypto_com_fetch_trades(monkeypatch):
    from services.exchanges import crypto_com_adapter as mod

    payload = {"result": {"data": [
        {"t": 1700000000000, "q": "0.5", "p": "40000", "s": "BUY", "i": "BTCUSD-PERP"},
        {"t": 1700000001000, "q": "0.2", "p": "40010", "s": "SELL", "i": "BTCUSD-PERP"},
    ]}}
    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: _Resp(payload))

    out = mod.CryptoComAdapter().fetch_trades("BTC", limit=10)
    assert len(out) == 2
    t0 = out[0]
    assert t0["ts_ms"] == 1700000000000
    assert t0["price"] == 40000.0
    assert t0["size"] == 0.5
    assert t0["side"] == "buy"
    assert t0["notional"] == 0.5 * 40000.0
    assert out[1]["side"] == "sell"


def test_gate_fetch_trades(monkeypatch):
    from services.exchanges import gate_adapter as mod

    # Gate BTC multiplier = 0.0001; signed size: >0 taker buy, <0 taker sell.
    payload = [
        {"create_time_ms": "1700000000.123", "size": 100, "price": "40000"},
        {"create_time_ms": "1700000001.000", "size": -50, "price": "40010"},
    ]
    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: _Resp(payload))

    out = mod.GateAdapter().fetch_trades("BTC", limit=10)
    assert len(out) == 2

    t0 = out[0]
    assert t0["side"] == "buy"
    assert abs(t0["size"] - 100 * 0.0001) < 1e-12  # 0.01 coin
    assert t0["price"] == 40000.0
    assert abs(t0["notional"] - (100 * 0.0001) * 40000.0) < 1e-9
    assert t0["ts_ms"] == int(1700000000.123 * 1000)

    t1 = out[1]
    assert t1["side"] == "sell"
    assert abs(t1["size"] - 50 * 0.0001) < 1e-12


def test_adapter_fetch_trades_error_returns_empty(monkeypatch):
    from services.exchanges import gate_adapter as mod

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(mod.requests, "get", boom)
    assert mod.GateAdapter().fetch_trades("BTC") == []
