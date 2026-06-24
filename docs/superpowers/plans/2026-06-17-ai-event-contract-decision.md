# AI 事件合约决策 — 实现计划(计划一:后端核心)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 AI(LLM)成为事件合约的决策大脑 —— 每分钟对空闲格出 long/short/none,经现有模拟器开单;并把永续 AI 决策循环停用。

**Architecture:** 复用事件合约现有管线(`simulator.run_cycle` → `_last_closed_signal` → 开单/结算)。新增 `event_contract/ai_decision.py`(上下文组装 + OpenAI 兼容 LLM 调用 + 解析,失败返 None 不阻塞),在 `_last_closed_signal` 加 `ai_llm` 特殊分支。永续大脑用配置开关停止调度。

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / pandas / requests;LLM 走 `EVENT_CONTRACT_LLM_*` 环境变量(OpenAI 兼容 `/chat/completions`),复用 `agents/llm_judge.py` 同款调用模式。

**范围说明:** 本计划只覆盖后端"AI 事件合约决策 + 永续停用"。`execution_mode=live` 平台无关执行(Task 6)做架构骨架。全部页面调用+监控转事件合约 = 单独"计划二"。

---

### Task 1: AI 决策上下文组装器

**Files:**
- Create: `backend/services/event_contract/ai_decision.py`
- Test: `backend/tests/test_event_contract_ai_decision.py`

- [ ] **Step 1: 写失败测试 — 上下文组装产出关键字段且不抛异常**

```python
# backend/tests/test_event_contract_ai_decision.py
import pandas as pd
from services.event_contract.ai_decision import build_context


def _kl(n=60):
    base = 65000.0
    rows = [{"timestamp": 1_700_000_000 + i*60, "open": base+i, "high": base+i+5,
             "low": base+i-5, "close": base+i+1, "volume": 10.0} for i in range(n)]
    return pd.DataFrame(rows)


def _of(n=60):
    rows = [{"minute": 1_700_000_000 + i*60, "cvd": (-1)**i * (i % 7),
             "buy_ratio": 0.5, "large_imb": 0.0, "volume": 10.0} for i in range(n)]
    return pd.DataFrame(rows)


def test_build_context_has_core_fields():
    ctx = build_context("BTC", 5, _kl(), _of())
    assert ctx["symbol"] == "BTC"
    assert ctx["expiry_minutes"] == 5
    assert "price" in ctx and ctx["price"] > 0
    assert "cvd_z" in ctx           # order-flow z-score
    assert "recent_closes" in ctx and len(ctx["recent_closes"]) <= 30
    assert isinstance(ctx.get("traps"), list)  # analysis trap list (may be empty)


def test_build_context_handles_empty():
    ctx = build_context("ETH", 10, pd.DataFrame(), pd.DataFrame())
    assert ctx["available"] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_event_contract_ai_decision.py -k build_context -v`
Expected: FAIL — `ImportError: cannot import name 'build_context'`

- [ ] **Step 3: 实现 build_context**

```python
# backend/services/event_contract/ai_decision.py
"""AI (LLM) event-contract decision brain.

For a free cell (symbol, expiry) it assembles a compact market context, asks an
OpenAI-compatible LLM whether price will be higher/lower after `expiry` minutes,
and returns 'long' | 'short' | None. Every failure path returns None so the
per-minute live loop is never blocked. Mirrors agents/llm_judge.py's call style.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def build_context(symbol: str, expiry: int, kl: pd.DataFrame, feat: pd.DataFrame) -> dict:
    """Compact, JSON-serialisable context for the LLM. Never raises."""
    if kl is None or kl.empty or feat is None or feat.empty:
        return {"symbol": symbol, "expiry_minutes": expiry, "available": False}
    try:
        closes = [round(float(c), 2) for c in kl["close"].tail(30).tolist()]
        price = float(kl["close"].iloc[-1])
        cvd = feat["cvd"]
        n = min(45, len(cvd) - 1)
        mean = cvd.rolling(n).mean().iloc[-1] if n > 1 else 0.0
        std = cvd.rolling(n).std().iloc[-1] if n > 1 else np.nan
        cvd_z = float((cvd.iloc[-1] - mean) / std) if std and not pd.isna(std) else 0.0
        buy_ratio = float(feat["buy_ratio"].iloc[-1]) if not pd.isna(feat["buy_ratio"].iloc[-1]) else 0.5
        traps: list = []
        try:
            from .agents.analysis import analyze
            rep = analyze(kl)
            d = rep.as_dict()
            traps = [t.get("name") for t in d.get("traps", [])]
            bias = d.get("bias")
        except Exception:
            bias = None
        return {
            "symbol": symbol, "expiry_minutes": expiry, "available": True,
            "price": price, "recent_closes": closes,
            "cvd_z": round(cvd_z, 3), "buy_ratio": round(buy_ratio, 3),
            "bias": bias, "traps": traps,
        }
    except Exception as e:  # context must never crash the loop
        logger.debug("[event_contract] build_context failed: %s", e)
        return {"symbol": symbol, "expiry_minutes": expiry, "available": False}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_event_contract_ai_decision.py -k build_context -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/services/event_contract/ai_decision.py backend/tests/test_event_contract_ai_decision.py
git commit -m "feat(event-contract): AI decision context builder"
```

---

### Task 2: LLM 调用 + decide()(失败返 None)

**Files:**
- Modify: `backend/services/event_contract/ai_decision.py`
- Test: `backend/tests/test_event_contract_ai_decision.py`

- [ ] **Step 1: 写失败测试 — 用 monkeypatch 桩掉 LLM,验证方向解析与健壮性**

```python
# append to backend/tests/test_event_contract_ai_decision.py
from services.event_contract import ai_decision


def test_decide_parses_long(monkeypatch):
    monkeypatch.setattr(ai_decision, "_load_data", lambda ex, sym: (_kl(), _of()))
    monkeypatch.setattr(ai_decision, "_call_llm", lambda ctx: {"direction": "long", "confidence": 0.7, "reason": "uptrend"})
    out = ai_decision.decide("BTC", 5, "binance")
    assert out["direction"] == "long" and out["confidence"] == 0.7


def test_decide_none_on_llm_failure(monkeypatch):
    monkeypatch.setattr(ai_decision, "_load_data", lambda ex, sym: (_kl(), _of()))
    def boom(ctx): raise RuntimeError("network")
    monkeypatch.setattr(ai_decision, "_call_llm", boom)
    out = ai_decision.decide("BTC", 5, "binance")
    assert out["direction"] is None


def test_decide_none_when_no_data(monkeypatch):
    monkeypatch.setattr(ai_decision, "_load_data", lambda ex, sym: (pd.DataFrame(), pd.DataFrame()))
    out = ai_decision.decide("BTC", 5, "binance")
    assert out["direction"] is None


def test_decide_rejects_bad_direction(monkeypatch):
    monkeypatch.setattr(ai_decision, "_load_data", lambda ex, sym: (_kl(), _of()))
    monkeypatch.setattr(ai_decision, "_call_llm", lambda ctx: {"direction": "sideways"})
    out = ai_decision.decide("BTC", 5, "binance")
    assert out["direction"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_event_contract_ai_decision.py -k decide -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_load_data'`

- [ ] **Step 3: 实现 _load_data / _call_llm / decide**

```python
# append to backend/services/event_contract/ai_decision.py

_SYSTEM = (
    "You trade a binary up/down event contract. At the current price you open a "
    "position; it settles after `expiry_minutes`. If price is ABOVE entry you win "
    "a 'long', if BELOW you win a 'short'. Given the context, answer strict JSON "
    '{"direction":"long"|"short"|"none","confidence":0..1,"reason":"..."}. Prefer '
    "trend continuation; if a high-severity trap is present, prefer none. Answer "
    "none when the edge is unclear."
)


def _load_data(exchange: str, symbol: str):
    """Load recent 1m klines + order-flow features. Separated for test stubbing."""
    from .data import load_klines
    from .orderflow import load_orderflow
    return load_klines(exchange, symbol, limit=120), load_orderflow(exchange, symbol, limit=500)


def _call_llm(ctx: dict) -> dict:
    """OpenAI-compatible chat call. Mirrors agents/llm_judge.py. Raises on failure."""
    import requests
    base = os.getenv("EVENT_CONTRACT_LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("EVENT_CONTRACT_LLM_MODEL", "gpt-4o-mini")
    payload = {
        "model": model, "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(ctx)},
        ],
    }
    resp = requests.post(
        f"{base.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {os.getenv('EVENT_CONTRACT_LLM_API_KEY', '')}"},
        json=payload, timeout=8,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])


def decide(symbol: str, expiry: int, exchange: str) -> dict:
    """Return {'direction': 'long'|'short'|None, 'confidence': float, 'reason': str}."""
    fail = {"direction": None, "confidence": 0.0, "reason": ""}
    if not os.getenv("EVENT_CONTRACT_LLM_API_KEY"):
        return fail  # not configured -> no AI trade this tick
    try:
        kl, feat = _load_data(exchange, symbol)
        ctx = build_context(symbol, expiry, kl, feat)
        if not ctx.get("available"):
            return fail
        verdict = _call_llm(ctx)
        direction = verdict.get("direction")
        if direction not in ("long", "short"):
            return fail
        return {
            "direction": direction,
            "confidence": float(verdict.get("confidence", 0.0) or 0.0),
            "reason": str(verdict.get("reason", ""))[:200],
        }
    except Exception as e:
        logger.debug("[event_contract] ai_decision.decide failed: %s", e)
        return fail
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_event_contract_ai_decision.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/services/event_contract/ai_decision.py backend/tests/test_event_contract_ai_decision.py
git commit -m "feat(event-contract): AI LLM event-contract decide() with safe fallbacks"
```

---

### Task 3: 模拟器接入 `ai_llm` 分支

**Files:**
- Modify: `backend/services/event_contract/simulator.py` (`_last_closed_signal`, around the adaptive branch)
- Test: `backend/tests/test_event_contract_ai_sim.py`

- [ ] **Step 1: 写失败测试 — default_signal=ai_llm 时模拟器用 ai_decision 的方向**

```python
# backend/tests/test_event_contract_ai_sim.py
import pandas as pd
from services.event_contract import simulator, ai_decision
from services.event_contract import config_store as cs


def _of(n=80):
    return pd.DataFrame([{"minute": 1_700_000_000 + i*60, "cvd": i % 5,
                          "buy_ratio": 0.5, "large_imb": 0.0, "volume": 10.0} for i in range(n)])


def test_sim_uses_ai_llm_direction(monkeypatch):
    # force ai_llm mode
    monkeypatch.setattr(cs, "default_signal", lambda: "ai_llm")
    monkeypatch.setattr(cs, "params_for", lambda s, e: {"window": 45, "thr": 1.5})
    monkeypatch.setattr(cs, "adaptive", lambda: False)
    monkeypatch.setattr(simulator, "load_orderflow", lambda ex, sym, limit=500: _of())
    captured = {}
    def fake_decide(symbol, expiry, exchange):
        captured["called"] = (symbol, expiry, exchange)
        return {"direction": "short", "confidence": 0.6, "reason": "x"}
    monkeypatch.setattr(ai_decision, "decide", fake_decide)
    sig = simulator._last_closed_signal("BTC", 5, "binance")
    assert sig is not None and sig["direction"] == "short"
    assert captured["called"] == ("BTC", 5, "binance")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_event_contract_ai_sim.py -v`
Expected: FAIL — 当前 `_last_closed_signal` 无 ai_llm 分支,会调 `OF_SIGNALS['ai_llm']` 抛 KeyError。

- [ ] **Step 3: 在 `_last_closed_signal` 加 ai_llm 分支**

修改 `backend/services/event_contract/simulator.py` 的决策分支(现有 adaptive 分支处),改成:

```python
    if sig_name == "ai_llm":
        from . import ai_decision
        direction = ai_decision.decide(symbol, expiry, exchange).get("direction")
    elif cfg.adaptive() and sig_name == "agent_consensus":
        from .agents import adaptive_direction
        direction = adaptive_direction(window, params, symbol, expiry, exchange, cfg.payout())
    else:
        direction = OF_SIGNALS[sig_name](window, params)
```

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `cd backend && uv run pytest tests/test_event_contract_ai_sim.py tests/test_event_contract_config_store.py tests/test_event_contract_memory.py -v`
Expected: PASS(新测 1 + 既有回归全过)

- [ ] **Step 5: 提交**

```bash
git add backend/services/event_contract/simulator.py backend/tests/test_event_contract_ai_sim.py
git commit -m "feat(event-contract): simulator ai_llm decision branch"
```

---

### Task 4: 配置暴露 `ai_llm` + `ai_prefilter`

**Files:**
- Modify: `backend/services/event_contract/config_store.py` (`_SCALAR_KEYS`, `_default_config`)
- Modify: `backend/api/event_contract_routes.py` (`/strategies` 追加 ai_llm)
- Test: `backend/tests/test_event_contract_config_store.py`

- [ ] **Step 1: 写失败测试 — 默认含 ai_prefilter=False**

```python
# append to backend/tests/test_event_contract_config_store.py
def test_default_has_ai_prefilter():
    from services.event_contract.config_store import merge_config
    cfg = merge_config(None)
    assert cfg["ai_prefilter"] is False
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_event_contract_config_store.py -k ai_prefilter -v`
Expected: FAIL — KeyError 'ai_prefilter'

- [ ] **Step 3: 加配置项**

`config_store.py`:`_SCALAR_KEYS` 末尾加 `"ai_prefilter"`;`_default_config()` 的返回 dict 加 `"ai_prefilter": False,`。
`event_contract_routes.py` 的 `/strategies`:

```python
@router.get("/strategies")
def strategies():
    return {"ta": list_strategies(), "order_flow": list(OF_SIGNALS.keys()) + ["ai_llm"]}
```

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `cd backend && uv run pytest tests/test_event_contract_config_store.py -v`
Expected: PASS(含新测)

- [ ] **Step 5: 提交**

```bash
git add backend/services/event_contract/config_store.py backend/api/event_contract_routes.py backend/tests/test_event_contract_config_store.py
git commit -m "feat(event-contract): expose ai_llm signal + ai_prefilter config"
```

---

### Task 5: 永续大脑停用开关(不删)

**Files:**
- Modify: `backend/services/startup.py`(永续 AI 决策调度处)
- Modify: `backend/config/settings.py`(新增开关读取)或用 env `PERPETUAL_BRAIN_ENABLED`
- Test: `backend/tests/test_perpetual_brain_disabled.py`

- [ ] **Step 1: 写失败测试 — 默认不启用永续大脑**

```python
# backend/tests/test_perpetual_brain_disabled.py
import os
from services.startup import perpetual_brain_enabled


def test_perpetual_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PERPETUAL_BRAIN_ENABLED", raising=False)
    assert perpetual_brain_enabled() is False


def test_perpetual_can_reenable(monkeypatch):
    monkeypatch.setenv("PERPETUAL_BRAIN_ENABLED", "true")
    assert perpetual_brain_enabled() is True
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_perpetual_brain_disabled.py -v`
Expected: FAIL — ImportError perpetual_brain_enabled

- [ ] **Step 3: 加开关 + 在调度处 gate**

`startup.py` 顶部加:

```python
import os

def perpetual_brain_enabled() -> bool:
    return os.getenv("PERPETUAL_BRAIN_ENABLED", "false").strip().lower() in ("1", "true", "yes")
```

然后用 `grep -n "ai_decision\|StrategyTrigger\|scheduled" backend/services/startup.py` 找到永续 AI 决策的注册/调度处,用 `if perpetual_brain_enabled():` 包住(不删代码,仅条件化)。事件合约 simulator 调度(60s)**不受影响**,保持启用。

- [ ] **Step 4: 运行确认通过 + py_compile**

Run: `cd backend && uv run pytest tests/test_perpetual_brain_disabled.py -v && python3 -m py_compile services/startup.py`
Expected: PASS + 无语法错误

- [ ] **Step 5: 提交**

```bash
git add backend/services/startup.py backend/tests/test_perpetual_brain_disabled.py
git commit -m "feat: retire perpetual AI brain behind PERPETUAL_BRAIN_ENABLED (default off)"
```

---

### Task 6: 执行统一骨架(paper / live 平台无关)

**Files:**
- Modify: `backend/services/event_contract/execution.py`
- Test: `backend/tests/test_event_contract_execution_mode.py`

- [ ] **Step 1: 写失败测试 — execution_mode 选 paper/live,live 无凭证回退 paper**

```python
# backend/tests/test_event_contract_execution_mode.py
from services.event_contract import execution


def test_paper_backend_default(monkeypatch):
    monkeypatch.delenv("EVENT_CONTRACT_EXECUTION_MODE", raising=False)
    assert execution.get_execution_backend().mode == "paper"


def test_live_falls_back_without_credentials(monkeypatch):
    monkeypatch.setenv("EVENT_CONTRACT_EXECUTION_MODE", "live")
    # no platform configured -> effective paper
    b = execution.get_execution_backend()
    assert b.effective_mode == "paper"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_event_contract_execution_mode.py -v`
Expected: FAIL(属性/模式不存在)

- [ ] **Step 3: 在 execution.py 加模式分流(保留现有 paper settle 逻辑)**

读现有 `execution.py` 后,新增:`mode` 属性;`LiveExecutionBackend`(查 `platforms` 注册表是否有已配置凭证的平台,无则 `effective_mode='paper'` 并复用 paper 的 settle);`get_execution_backend()` 按 `EVENT_CONTRACT_EXECUTION_MODE`(默认 paper)返回。**真实平台 API 下单留 `open_order` 抽象方法,具体平台后续补**(本任务只做骨架与回退)。

- [ ] **Step 4: 运行确认通过 + 全量事件合约回归**

Run: `cd backend && uv run pytest tests/ -k event_contract -v`
Expected: PASS(全部事件合约测试)

- [ ] **Step 5: 提交**

```bash
git add backend/services/event_contract/execution.py backend/tests/test_event_contract_execution_mode.py
git commit -m "feat(event-contract): paper/live execution mode skeleton (platform-agnostic, safe fallback)"
```

---

### Task 7: 运行时冒烟 + 收尾验证

- [ ] **Step 1: 配置 LLM env + 启用 ai_llm,跑一次 cycle**

```bash
cd backend
export EVENT_CONTRACT_LLM_API_KEY=...        # 用户填
export EVENT_CONTRACT_LLM_BASE_URL=...        # OpenAI 兼容
export EVENT_CONTRACT_LLM_MODEL=...
uv run python -c "
from services.event_contract import config_store as cs
cs.save_config({'default_signal':'ai_llm'})
from services.event_contract.simulator import run_cycle
print(run_cycle('binance'))
"
```
Expected: 打印 `{opened: N, settled: M}`;空闲格调用了 LLM。

- [ ] **Step 2: 全量后端测试 + 前端 build**

Run: `cd backend && uv run pytest tests/ -k event_contract -v && cd ../frontend && pnpm build`
Expected: 全过;build 成功。

- [ ] **Step 3: 切回 of_cvd_fade 验证无回归**

```bash
cd backend && uv run python -c "from services.event_contract import config_store as cs; cs.save_config({'default_signal':'of_cvd_fade'}); print(cs.get_config()['default_signal'])"
```
Expected: 打印 of_cvd_fade,模拟器恢复机械信号。

- [ ] **Step 4: 提交收尾**

```bash
git add -A && git commit -m "chore(event-contract): AI decision phase-1 smoke verified"
```

---

## 计划二(后续,单独计划):全部页面调用 + 监控转事件合约
盘点 `frontend/app/lib/` 各 API 客户端 + 各页 hook 的永续数据来源(持仓/账户/PnL/WS 仓位推送),逐页替换为事件合约等价(`/api/event-contract/*`、`event_contract_orders`、每日胜率表、信号板;WS 订阅事件合约订单/结算)。范围大,独立成计划,待计划一落地后启动。
