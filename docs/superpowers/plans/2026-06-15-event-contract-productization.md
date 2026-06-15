# Event Contract Productization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the multi-feature Hyper Alpha Arena platform into a focused, white-labelable event-contract (binary up/down signal) product — keeping the Hyper AI chat entry — without deleting the underlying engine.

**Architecture:** Config-driven "focus mode" (Approach A). A frontend `productConfig` flag filters navigation/landing page and hides perpetual-trading controls; branding becomes env-driven; a new DB-backed `EventContractConfig` + `config_store` makes signal params client-editable via a config panel; a thin `execution.py` seam reserves real-order execution for Phase 2 (not built now).

**Tech Stack:** FastAPI + SQLAlchemy (Postgres/SQLite), Vite + React 18 + TypeScript + Tailwind, i18next. Backend deps via `uv`, frontend via `pnpm`. JSON persisted as TEXT columns (project convention).

**Spec:** `docs/superpowers/specs/2026-06-15-event-contract-productization-design.md`

---

## File Structure

**Backend (new):**
- `backend/database/models_event_contract_config.py` — `EventContractConfig` table (single-row JSON-in-TEXT overrides).
- `backend/database/migrations/seed_event_contract_config.py` — idempotent create + seed.
- `backend/services/event_contract/config_store.py` — defaults + DB overrides merge, cached accessors.
- `backend/services/event_contract/execution.py` — `ExecutionBackend` protocol + `PaperExecutionBackend` (Phase 2 seam).
- `backend/tests/test_event_contract_config_store.py` — unit tests for pure merge logic.

**Backend (modify):**
- `backend/main.py:14` — register new model import.
- `backend/database/migration_manager.py:25` — register migration in `MIGRATIONS`.
- `backend/services/event_contract/simulator.py` — read dynamic config via `config_store`.
- `backend/services/event_contract/stats.py:12` — read `daily_reset_tz` via `config_store`.
- `backend/api/event_contract_routes.py` — add `GET/PUT /config`, `GET /branding`; use `config_store`.

**Frontend (new):**
- `frontend/app/lib/productConfig.ts` — focus-mode flags from `VITE_PRODUCT_MODE`.
- `frontend/app/components/layout/navItems.ts` — nav array extracted from `Sidebar.tsx`.
- `frontend/app/components/event-contract/EventContractConfigPanel.tsx` — client config UI.

**Frontend (modify):**
- `frontend/app/lib/branding.ts` — env-driven `SITE_NAME/SITE_URL/SITE_LOGO`.
- `frontend/app/lib/eventContractApi.ts` — config + branding clients.
- `frontend/app/components/layout/Sidebar.tsx` — consume `navItems` + filter; hide exchange/mode blocks; use branding.
- `frontend/app/components/layout/Header.tsx` — use branding.
- `frontend/app/main.tsx:33` — default page from `productConfig`.
- `frontend/index.html` — title placeholder (kept simple).
- `frontend/app/components/event-contract/EventContractPage.tsx` — gear toggle → config panel.
- `frontend/app/locales/en.json`, `zh.json` — new strings.
- `.env.example` (repo root and/or `backend/`) — document new `VITE_*` vars.

---

## Task 1: EventContractConfig model

**Files:**
- Create: `backend/database/models_event_contract_config.py`
- Modify: `backend/main.py:14`

- [ ] **Step 1: Create the model**

`backend/database/models_event_contract_config.py`:
```python
"""Runtime-editable config for the event-contract product.

Single-row table holding client overrides as a JSON string (TEXT, matching the
project's JSON-as-TEXT convention). Defaults live in
services/event_contract/config.py; config_store.py merges defaults + this row.
"""
from sqlalchemy import Column, Integer, Text, DateTime
from sqlalchemy.sql import func

from .connection import Base


class EventContractConfig(Base):
    __tablename__ = "event_contract_config"

    id = Column(Integer, primary_key=True)
    # JSON string of override keys: symbols, expiries, payout, default_signal,
    # daily_reset_tz, signal_params ({"BTC:5": {"window":45,"thr":1.5}, ...})
    data = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 2: Register the model for create_all**

In `backend/main.py`, directly after line 14 (`from database.models_event_contract import EventContractOrder  # noqa: F401`), add:
```python
from database.models_event_contract_config import EventContractConfig  # noqa: F401
```

- [ ] **Step 3: Syntax check**

Run: `cd backend && python3 -m py_compile database/models_event_contract_config.py main.py`
Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add backend/database/models_event_contract_config.py backend/main.py
git commit -m "feat(event-contract): add EventContractConfig model"
```

---

## Task 2: Idempotent migration (create + seed config)

**Files:**
- Create: `backend/database/migrations/seed_event_contract_config.py`
- Modify: `backend/database/migration_manager.py` (`MIGRATIONS` list)

- [ ] **Step 1: Write the migration**

`backend/database/migrations/seed_event_contract_config.py`:
```python
#!/usr/bin/env python3
"""Migration: create event_contract_config table and seed one default row.

Idempotent: creates the table only if missing, seeds only if empty.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from connection import SessionLocal


def upgrade():
    print("Starting migration: seed_event_contract_config")
    db = SessionLocal()
    try:
        exists = db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'event_contract_config'
            )
        """)).scalar()
        if not exists:
            print("Creating event_contract_config table...")
            db.execute(text("""
                CREATE TABLE event_contract_config (
                    id SERIAL PRIMARY KEY,
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.commit()

        count = db.execute(text("SELECT COUNT(*) FROM event_contract_config")).scalar()
        if count == 0:
            print("Seeding default event_contract_config row...")
            db.execute(text("INSERT INTO event_contract_config (data) VALUES ('{}')"))
            db.commit()
        else:
            print("  event_contract_config already seeded, skipping")
    except Exception as e:
        db.rollback()
        print(f"  migration error (non-fatal): {e}")
    finally:
        db.close()


if __name__ == "__main__":
    upgrade()
```

(The row stores `'{}'` — an empty override set — so `config_store` returns pure defaults until the client edits anything.)

- [ ] **Step 2: Register in MIGRATIONS**

In `backend/database/migration_manager.py`, append to the end of the `MIGRATIONS` list (just before the closing `]`):
```python
    "seed_event_contract_config.py",
```

- [ ] **Step 3: Syntax check + idempotency dry run**

Run: `cd backend && python3 -m py_compile database/migrations/seed_event_contract_config.py database/migration_manager.py`
Expected: no output.

(Full run happens at app startup; the create/seed guards make re-runs safe.)

- [ ] **Step 4: Commit**

```bash
git add backend/database/migrations/seed_event_contract_config.py backend/database/migration_manager.py
git commit -m "feat(event-contract): migration to create+seed config table"
```

---

## Task 3: config_store with unit-tested merge logic (TDD)

**Files:**
- Create: `backend/services/event_contract/config_store.py`
- Test: `backend/tests/test_event_contract_config_store.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_event_contract_config_store.py`:
```python
from services.event_contract.config_store import merge_config, params_for_cfg


def test_merge_returns_defaults_when_no_overrides():
    cfg = merge_config(None)
    assert cfg["symbols"] == ["BTC", "ETH"]
    assert cfg["expiries"] == [5, 10]
    assert cfg["payout"] == 0.8
    assert cfg["default_signal"] == "of_cvd_fade"
    assert cfg["signal_params"]["BTC:5"] == {"window": 45, "thr": 1.5}


def test_merge_overrides_scalar_and_params():
    cfg = merge_config({"payout": 0.9, "signal_params": {"BTC:5": {"window": 60, "thr": 2.0}}})
    assert cfg["payout"] == 0.9
    assert cfg["signal_params"]["BTC:5"] == {"window": 60, "thr": 2.0}
    # untouched cells keep defaults
    assert cfg["signal_params"]["ETH:10"] == {"window": 20, "thr": 2.5}


def test_merge_ignores_none_values():
    cfg = merge_config({"payout": None})
    assert cfg["payout"] == 0.8


def test_params_for_cfg_falls_back():
    cfg = merge_config(None)
    assert params_for_cfg(cfg, "SOL", 5) == {"window": 30, "thr": 1.5}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_event_contract_config_store.py -v`
Expected: FAIL — `ModuleNotFoundError: ... config_store`.

- [ ] **Step 3: Write config_store.py**

`backend/services/event_contract/config_store.py`:
```python
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

_SCALAR_KEYS = ("symbols", "expiries", "payout", "default_signal", "daily_reset_tz")


def _default_config() -> dict:
    return {
        "symbols": list(_defaults.SYMBOLS),
        "expiries": list(_defaults.EXPIRIES),
        "payout": _defaults.PAYOUT,
        "default_signal": _defaults.DEFAULT_SIGNAL,
        "daily_reset_tz": _defaults.DAILY_RESET_TZ,
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


def params_for(symbol: str, expiry: int) -> dict:
    return params_for_cfg(get_config(), symbol, expiry)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_event_contract_config_store.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/event_contract/config_store.py backend/tests/test_event_contract_config_store.py
git commit -m "feat(event-contract): DB-backed config_store with tested merge logic"
```

---

## Task 4: Wire simulator + stats to config_store

**Files:**
- Modify: `backend/services/event_contract/simulator.py:20-24`, body
- Modify: `backend/services/event_contract/stats.py:12`

- [ ] **Step 1: Update simulator imports**

In `backend/services/event_contract/simulator.py`, replace the import block (lines 20-24):
```python
from .config import (
    DEFAULT_EXCHANGE, DEFAULT_SIGNAL, EXPIRIES, PAYOUT, SYMBOLS, params_for,
)
```
with (keep `DEFAULT_EXCHANGE` static from config; pull the rest dynamically):
```python
from .config import DEFAULT_EXCHANGE
from .config_store import (
    DEFAULT_SIGNAL_FALLBACK as _unused,  # placeholder removed below
)
```
Then DELETE that placeholder line and instead use accessors. The cleanest edit: import `config_store as cfg` and reference `cfg.default_signal()`, `cfg.expiries()`, `cfg.payout()`, `cfg.symbols()`, `cfg.params_for(...)`. Final import block:
```python
from .config import DEFAULT_EXCHANGE
from . import config_store as cfg
```

- [ ] **Step 2: Replace usages in simulator.py**

Apply these exact substitutions (module-level constants are now function calls):
- `_last_closed_signal` (~line 43): `fn = OF_SIGNALS[DEFAULT_SIGNAL]` → `fn = OF_SIGNALS[cfg.default_signal()]`
- `_last_closed_signal` (~line 45): `direction = fn(window, params_for(symbol, expiry))` → `direction = fn(window, cfg.params_for(symbol, expiry))`
- `current_signals` (~line 57): `for symbol in SYMBOLS:` → `for symbol in cfg.symbols():`
- `current_signals` (~line 60): `for expiry in EXPIRIES:` → `for expiry in cfg.expiries():`
- `run_signal_cycle` (~line 79): `for symbol in SYMBOLS:` → `for symbol in cfg.symbols():`
- `run_signal_cycle` (~line 83): `for expiry in EXPIRIES:` → `for expiry in cfg.expiries():`
- `run_signal_cycle` (~line 103): `strategy=DEFAULT_SIGNAL,` → `strategy=cfg.default_signal(),`
- `run_signal_cycle` (~line 107): `result="pending", payout=PAYOUT,` → `result="pending", payout=cfg.payout(),`

- [ ] **Step 3: Update stats.py**

In `backend/services/event_contract/stats.py`, replace line 12:
```python
from .config import DAILY_RESET_TZ
```
with:
```python
from .config_store import daily_reset_tz
```
Then replace each use of `DAILY_RESET_TZ` in the file with `daily_reset_tz()`. (Find with `grep -n DAILY_RESET_TZ backend/services/event_contract/stats.py` — expect the default-arg or call site; if it is a function default like `def daily_stats(mode, tz_name=DAILY_RESET_TZ)`, change to `tz_name=None` and inside do `tz_name = tz_name or daily_reset_tz()`.)

- [ ] **Step 4: Syntax check + run signal preview**

Run: `cd backend && python3 -m py_compile services/event_contract/simulator.py services/event_contract/stats.py`
Expected: no output.

Run the existing config-store tests still pass: `cd backend && uv run pytest tests/test_event_contract_config_store.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/event_contract/simulator.py backend/services/event_contract/stats.py
git commit -m "refactor(event-contract): read runtime config via config_store"
```

---

## Task 5: Config + branding API routes

**Files:**
- Modify: `backend/api/event_contract_routes.py`

- [ ] **Step 1: Inspect current route file usage of config**

Run: `grep -n "ec_config\|router\s*=\|@router" backend/api/event_contract_routes.py | head -40`
Note the `router` definition and where `ec_config.SYMBOLS/EXPIRIES/PAYOUT/DEFAULT_*` are referenced (the `/overview` and `/backtest/compare` handlers).

- [ ] **Step 2: Switch overview to config_store and add config/branding endpoints**

In `backend/api/event_contract_routes.py`:
- Replace `from services.event_contract import config as ec_config` (line 12) with:
```python
from services.event_contract import config as ec_config  # static defaults (DEFAULT_EXCHANGE)
from services.event_contract import config_store as ec_store
from pydantic import BaseModel
import os
```
- In the `/overview` handler, source symbols/expiries/payout/default_signal from `ec_store.get_config()` instead of `ec_config.*` (keep `ec_config.DEFAULT_EXCHANGE`).
- Append these handlers (use the existing `router` object; respect its prefix `/api/event-contract`):
```python
class EventContractConfigPatch(BaseModel):
    symbols: list[str] | None = None
    expiries: list[int] | None = None
    payout: float | None = None
    default_signal: str | None = None
    daily_reset_tz: str | None = None
    signal_params: dict | None = None


@router.get("/config")
def get_event_contract_config():
    return ec_store.get_config()


@router.put("/config")
def update_event_contract_config(patch: EventContractConfigPatch):
    return ec_store.save_config(patch.model_dump(exclude_none=True))


@router.get("/branding")
def get_branding():
    return {
        "site_name": os.getenv("SITE_NAME", "Hyper Alpha Arena"),
        "site_url": os.getenv("SITE_URL", "/"),
        "site_logo": os.getenv("SITE_LOGO", "/static/logo_app.png"),
    }
```

- [ ] **Step 3: Syntax check**

Run: `cd backend && python3 -m py_compile api/event_contract_routes.py`
Expected: no output.

- [ ] **Step 4: File-size check**

Run: `bash scripts/check-file-size.sh 2>/dev/null | grep event_contract_routes || echo "within limit"`
If `event_contract_routes.py` now exceeds 300 lines, split the three new handlers into `backend/api/event_contract_config_routes.py` (own `APIRouter`, registered in `app_bootstrap/route_registry.py`). Otherwise keep inline.

- [ ] **Step 5: Commit**

```bash
git add backend/api/event_contract_routes.py
git commit -m "feat(event-contract): config GET/PUT + branding endpoints"
```

---

## Task 6: Phase 2 execution seam (paper backend only)

**Files:**
- Create: `backend/services/event_contract/execution.py`

- [ ] **Step 1: Write the seam**

`backend/services/event_contract/execution.py`:
```python
"""Execution backend seam for the event-contract product.

Phase 1 ships only the paper (simulation) backend — orders are recorded, not
sent to any exchange. A future LiveExecutionBackend can implement the same
Protocol and be returned by get_execution_backend() without touching simulator.
"""
from __future__ import annotations

from typing import Protocol

from database.models_event_contract import EventContractOrder


class ExecutionBackend(Protocol):
    def open_order(self, order: EventContractOrder) -> None: ...
    def settle_order(self, order: EventContractOrder, settle_price: float) -> None: ...


class PaperExecutionBackend:
    """No real orders. Settlement is decided by EventContractOrder.settle()."""

    def open_order(self, order: EventContractOrder) -> None:
        return None

    def settle_order(self, order: EventContractOrder, settle_price: float) -> None:
        order.settle(settle_price)


_BACKEND: ExecutionBackend = PaperExecutionBackend()


def get_execution_backend() -> ExecutionBackend:
    return _BACKEND
```

- [ ] **Step 2: Route simulator settlement through the seam**

In `backend/services/event_contract/simulator.py`:
- Add import near the others: `from .execution import get_execution_backend`
- In `settle_due_orders`, replace `o.settle(float(sp))` (~line 146) with:
```python
get_execution_backend().settle_order(o, float(sp))
```

- [ ] **Step 3: Syntax check**

Run: `cd backend && python3 -m py_compile services/event_contract/execution.py services/event_contract/simulator.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/services/event_contract/execution.py backend/services/event_contract/simulator.py
git commit -m "feat(event-contract): execution backend seam (paper only, phase 2 ready)"
```

---

## Task 7: Frontend product config

**Files:**
- Create: `frontend/app/lib/productConfig.ts`

- [ ] **Step 1: Write productConfig.ts**

`frontend/app/lib/productConfig.ts`:
```ts
// Product focus configuration. Driven by VITE_PRODUCT_MODE so this dedicated
// client repo ships as an event-contract product by default, while 'full'
// keeps every page for internal development.
type ProductMode = 'event_contract' | 'full'

const MODE = (import.meta.env.VITE_PRODUCT_MODE as ProductMode) || 'event_contract'

const EVENT_CONTRACT_PAGES = ['event-contract', 'hyper-ai', 'settings']

export const productConfig = {
  mode: MODE,
  // null => all pages visible (full mode)
  visiblePages: MODE === 'event_contract' ? EVENT_CONTRACT_PAGES : null as string[] | null,
  defaultPage: MODE === 'event_contract' ? 'event-contract' : 'hyper-ai',
  showExchangeSelector: MODE !== 'event_contract',
  showTradingModeToggle: MODE !== 'event_contract',
}

export function isPageVisible(page: string): boolean {
  return productConfig.visiblePages === null || productConfig.visiblePages.includes(page)
}
```

- [ ] **Step 2: Typecheck via build**

Run: `cd frontend && pnpm build`
Expected: build succeeds (no TS errors from the new file).

- [ ] **Step 3: Commit**

```bash
git add frontend/app/lib/productConfig.ts
git commit -m "feat(event-contract): frontend product focus config"
```

---

## Task 8: Branding env wiring

**Files:**
- Modify: `frontend/app/lib/branding.ts`
- Modify: `frontend/app/components/layout/Header.tsx`
- Modify: repo root `.env.example` and `backend/.env.example` (whichever exist)

- [ ] **Step 1: Make branding env-driven**

Replace `frontend/app/lib/branding.ts` contents with:
```ts
// Site branding for this deployment. Set via Vite env at build/deploy time:
//   VITE_SITE_NAME, VITE_SITE_URL, VITE_SITE_LOGO
export const SITE_NAME = (import.meta.env.VITE_SITE_NAME as string) || 'Hyper Alpha Arena'
export const SITE_URL = (import.meta.env.VITE_SITE_URL as string) || '/'
export const SITE_LOGO = (import.meta.env.VITE_SITE_LOGO as string) || '/static/logo_app.png'
```

- [ ] **Step 2: Use branding in Header**

Run: `grep -n "Hyper Alpha Arena\|logo_app\|import" frontend/app/components/layout/Header.tsx`
If a hardcoded brand string/logo exists, import `{ SITE_NAME, SITE_LOGO }` from `@/lib/branding` and replace the literals. If none exists, no change (Header shows page title only) — note that in the commit.

- [ ] **Step 3: Document env vars**

Append to the repo-root `.env.example` (create the lines if absent):
```
# Event-contract product / white-label (frontend, Vite — must be prefixed VITE_)
VITE_PRODUCT_MODE=event_contract   # or 'full' for internal dev
VITE_SITE_NAME=Hyper Alpha Arena
VITE_SITE_URL=/
VITE_SITE_LOGO=/static/logo_app.png
```

- [ ] **Step 4: Build**

Run: `cd frontend && pnpm build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/lib/branding.ts frontend/app/components/layout/Header.tsx .env.example
git commit -m "feat(event-contract): env-driven white-label branding"
```

---

## Task 9: Extract nav items + filter Sidebar

**Files:**
- Create: `frontend/app/components/layout/navItems.ts`
- Modify: `frontend/app/components/layout/Sidebar.tsx`

- [ ] **Step 1: Create navItems.ts**

`frontend/app/components/layout/navItems.ts` (move the icon imports + array out of Sidebar; each item carries a translation key + default):
```ts
import {
  Bot, BarChart3, Ghost, NotebookPen, ScrollText, Coins, FileText, FlaskConical, ArrowUpDown,
} from 'lucide-react'
import { AttributionIcon, KLinesIcon, PremiumIcon, SignalIcon } from './navIcons' // if custom icons are local, see note

export interface NavItem {
  page: string
  i18nKey: string
  fallback: string
  icon: any
}

// Full nav. Sidebar filters this by productConfig.visiblePages.
export const NAV_ITEMS: NavItem[] = [
  { page: 'hyper-ai', i18nKey: 'hyperAi.title', fallback: 'Hyper AI', icon: Bot },
  { page: 'comprehensive', i18nKey: 'sidebar.dashboard', fallback: 'Dashboard', icon: BarChart3 },
  { page: 'trader-management', i18nKey: 'sidebar.aiTrader', fallback: 'AI Trader', icon: Ghost },
  { page: 'prompt-management', i18nKey: 'sidebar.prompts', fallback: 'Prompts', icon: NotebookPen },
  { page: 'program-trader', i18nKey: 'sidebar.programTrader', fallback: 'Program Trader', icon: ScrollText },
  { page: 'signal-management', i18nKey: 'sidebar.signals', fallback: 'Signals', icon: SignalIcon },
  { page: 'event-contract', i18nKey: 'sidebar.eventContract', fallback: 'Event Contract', icon: ArrowUpDown },
  { page: 'attribution', i18nKey: 'sidebar.attribution', fallback: 'Attribution', icon: AttributionIcon },
  { page: 'factor-library', i18nKey: 'sidebar.factorLibrary', fallback: 'Factors', icon: FlaskConical },
  { page: 'hyperliquid', i18nKey: 'sidebar.manualTrading', fallback: 'Manual Trading', icon: Coins },
  { page: 'klines', i18nKey: 'sidebar.klines', fallback: 'K-Lines', icon: KLinesIcon },
  { page: 'premium-features', i18nKey: 'sidebar.premium', fallback: 'Advanced', icon: PremiumIcon },
  { page: 'system-logs', i18nKey: 'sidebar.systemLogs', fallback: 'System Logs', icon: FileText },
]
```
NOTE: `Sidebar.tsx` currently imports its icons (including any custom `*Icon` components) at the top. Copy the EXACT icon import lines from `Sidebar.tsx` (run `grep -n "import.*lucide-react\|Icon" frontend/app/components/layout/Sidebar.tsx | head`) into `navItems.ts` so names resolve. Do not invent `./navIcons` if the icons are imported from elsewhere — use the real source paths.

- [ ] **Step 2: Consume + filter in Sidebar.tsx**

In `frontend/app/components/layout/Sidebar.tsx`:
- Add imports: `import { NAV_ITEMS } from './navItems'` and `import { productConfig, isPageVisible } from '@/lib/productConfig'` and `import { SITE_NAME, SITE_LOGO } from '@/lib/branding'`.
- Delete the inline `desktopNav` array (lines 138-152) and the now-unused icon imports that moved to navItems.
- Build the visible nav inside the component:
```tsx
const desktopNav = NAV_ITEMS
  .filter((item) => isPageVisible(item.page))
  .map((item) => ({ label: t(item.i18nKey, item.fallback), page: item.page, icon: item.icon }))
```
- Brand block (lines 164-165): replace `<img src="/static/logo_app.png" ...>` `src` with `{SITE_LOGO}` and the text `Hyper Alpha Arena` with `{SITE_NAME}`.
- Wrap the Exchange block (lines 170-188) in `{productConfig.showExchangeSelector && ( ... )}` and the Trading Mode block (lines 190+, the `rounded-lg ... Trading Mode` div through its close) in `{productConfig.showTradingModeToggle && ( ... )}`.

- [ ] **Step 3: Build**

Run: `cd frontend && pnpm build`
Expected: build succeeds; no unused-import TS errors (remove any leftover icon imports flagged).

- [ ] **Step 4: Commit**

```bash
git add frontend/app/components/layout/navItems.ts frontend/app/components/layout/Sidebar.tsx
git commit -m "feat(event-contract): focus-mode sidebar (filtered nav, hidden perp controls)"
```

---

## Task 10: Default landing page + mobile nav filter

**Files:**
- Modify: `frontend/app/main.tsx:33`
- Modify: mobile nav (locate via grep)

- [ ] **Step 1: Default page from productConfig**

In `frontend/app/main.tsx`:
- Add import: `import { productConfig, isPageVisible } from '@/lib/productConfig'`
- Line 33: `const [currentPage, setCurrentPage] = useState<string>('hyper-ai')` → `const [currentPage, setCurrentPage] = useState<string>(productConfig.defaultPage)`
- In the hash-init effect (line 97-98) and `onHashChange` (line 103-104), guard navigation to hidden pages:
```tsx
if (pageName && PAGE_TITLES[pageName] && isPageVisible(pageName)) setCurrentPage(pageName)
```

- [ ] **Step 2: Filter mobile navigation**

Run: `grep -rn "comprehensive\|program-trader\|setCurrentPage\|onPageChange" frontend/app/components/mobile/ | head`
Wherever the mobile menu hardcodes pages, filter with `isPageVisible(page)` (import from `@/lib/productConfig`). If mobile reuses `NAV_ITEMS`, apply the same `.filter(isPageVisible)`.

- [ ] **Step 3: Build**

Run: `cd frontend && pnpm build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/main.tsx frontend/app/components/mobile
git commit -m "feat(event-contract): default to event-contract page, guard hidden routes"
```

---

## Task 11: Config panel API client

**Files:**
- Modify: `frontend/app/lib/eventContractApi.ts`

- [ ] **Step 1: Add types + client functions**

Append to `frontend/app/lib/eventContractApi.ts`:
```ts
export interface EventContractConfig {
  symbols: string[]
  expiries: number[]
  payout: number
  default_signal: string
  daily_reset_tz: string
  signal_params: Record<string, { window: number; thr: number }>
}

export function getEventContractConfig() {
  return get<EventContractConfig>('/api/event-contract/config')
}

export function updateEventContractConfig(patch: Partial<EventContractConfig>) {
  return fetch('/api/event-contract/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }).then((r) => {
    if (!r.ok) throw new Error(`PUT /config -> ${r.status}`)
    return r.json() as Promise<EventContractConfig>
  })
}
```

- [ ] **Step 2: Build**

Run: `cd frontend && pnpm build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/lib/eventContractApi.ts
git commit -m "feat(event-contract): config API client"
```

---

## Task 12: Config panel UI + integration

**Files:**
- Create: `frontend/app/components/event-contract/EventContractConfigPanel.tsx`
- Modify: `frontend/app/components/event-contract/EventContractPage.tsx`
- Modify: `frontend/app/locales/en.json`, `frontend/app/locales/zh.json`

- [ ] **Step 1: Build the config panel**

`frontend/app/components/event-contract/EventContractConfigPanel.tsx`:
```tsx
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { EventContractConfig, getEventContractConfig, updateEventContractConfig } from '@/lib/eventContractApi'

export default function EventContractConfigPanel({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const [cfg, setCfg] = useState<EventContractConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => { getEventContractConfig().then(setCfg).catch(() => setCfg(null)) }, [])

  if (!cfg) return <div className="text-sm text-muted-foreground p-4">{t('eventContract.loading', '加载中…')}</div>

  const setParam = (key: string, field: 'window' | 'thr', value: number) => {
    setCfg({ ...cfg, signal_params: { ...cfg.signal_params, [key]: { ...cfg.signal_params[key], [field]: value } } })
  }

  const save = async () => {
    setSaving(true); setMsg('')
    try {
      const next = await updateEventContractConfig({ payout: cfg.payout, daily_reset_tz: cfg.daily_reset_tz, signal_params: cfg.signal_params })
      setCfg(next); setMsg(t('eventContract.saved', '已保存'))
    } catch { setMsg(t('eventContract.saveFailed', '保存失败')) } finally { setSaving(false) }
  }

  return (
    <div className="border rounded-lg p-4 bg-card space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">{t('eventContract.config', '事件合约配置')}</h3>
        <button onClick={onClose} className="text-sm text-muted-foreground hover:text-foreground">✕</button>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-sm">{t('eventContract.payout', '赔付')}</label>
        <input type="number" step="0.01" value={cfg.payout}
          onChange={(e) => setCfg({ ...cfg, payout: Number(e.target.value) })}
          className="border rounded px-2 py-1 text-sm bg-background w-24" />
        <label className="text-sm">{t('eventContract.resetTz', '重置时区')}</label>
        <input value={cfg.daily_reset_tz}
          onChange={(e) => setCfg({ ...cfg, daily_reset_tz: e.target.value })}
          className="border rounded px-2 py-1 text-sm bg-background w-44" />
      </div>

      <div>
        <div className="text-sm font-medium mb-2">{t('eventContract.signalParams', '信号参数 (window / thr)')}</div>
        <table className="text-sm">
          <tbody>
            {Object.keys(cfg.signal_params).map((key) => (
              <tr key={key}>
                <td className="pr-3 py-1 font-mono">{key}</td>
                <td className="pr-2"><input type="number" value={cfg.signal_params[key].window}
                  onChange={(e) => setParam(key, 'window', Number(e.target.value))}
                  className="border rounded px-2 py-1 bg-background w-20" /></td>
                <td><input type="number" step="0.05" value={cfg.signal_params[key].thr}
                  onChange={(e) => setParam(key, 'thr', Number(e.target.value))}
                  className="border rounded px-2 py-1 bg-background w-20" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center gap-3">
        <button onClick={save} disabled={saving}
          className="px-3 py-1 text-sm rounded bg-primary text-primary-foreground disabled:opacity-50">
          {saving ? t('eventContract.saving', '保存中…') : t('eventContract.save', '保存')}
        </button>
        {msg && <span className="text-xs text-muted-foreground">{msg}</span>}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Add gear toggle to EventContractPage**

In `frontend/app/components/event-contract/EventContractPage.tsx`:
- Add import: `import EventContractConfigPanel from './EventContractConfigPanel'`
- Add state in the component (after line 52): `const [showConfig, setShowConfig] = useState(false)`
- In the signal-board header row (lines 83-86), add a gear button next to the `updated` span:
```tsx
<button onClick={() => setShowConfig((v) => !v)}
  className="text-xs px-2 py-1 rounded border hover:bg-muted">
  ⚙ {t('eventContract.config', '配置')}
</button>
```
- Render the panel right under the header row (inside the `flex-1` div, before the grid):
```tsx
{showConfig && <div className="mb-3"><EventContractConfigPanel onClose={() => setShowConfig(false)} /></div>}
```

- [ ] **Step 3: Add i18n strings (both files)**

In `frontend/app/locales/en.json`, inside the `eventContract` object, add (use English values):
```json
"config": "Config",
"signalParams": "Signal params (window / thr)",
"resetTz": "Reset timezone",
"save": "Save",
"saving": "Saving…",
"saved": "Saved",
"saveFailed": "Save failed"
```
In `frontend/app/locales/zh.json`, inside `eventContract`, add the same keys with Chinese values (`配置 / 信号参数 (window / thr) / 重置时区 / 保存 / 保存中… / 已保存 / 保存失败`). Verify `payout` and `loading` keys already exist in both; add if missing.

- [ ] **Step 4: Build**

Run: `cd frontend && pnpm build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/components/event-contract/EventContractConfigPanel.tsx frontend/app/components/event-contract/EventContractPage.tsx frontend/app/locales/en.json frontend/app/locales/zh.json
git commit -m "feat(event-contract): client config panel"
```

---

## Task 13: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Backend imports + tests**

Run: `cd backend && python3 -m py_compile main.py && uv run pytest tests/test_event_contract_config_store.py -v`
Expected: compile clean, 4 passed.

- [ ] **Step 2: Frontend production build**

Run: `cd frontend && pnpm build`
Expected: build succeeds.

- [ ] **Step 3: File-size rule**

Run: `./scripts/check-file-size.sh`
Expected: no new violations from touched files (`Sidebar.tsx` should be smaller than before; new files < 300 lines).

- [ ] **Step 4: Manual smoke (if app is running on :8802 — confirm before restart per AGENTS.md)**

Verify in `event_contract` mode: sidebar shows only Event Contract / Hyper AI / Settings; landing page is Event Contract; no exchange selector / testnet toggle; gear opens config panel; editing payout/params + Save persists (reload shows saved values); Hyper AI page still loads.
With `VITE_PRODUCT_MODE=full` rebuild: all pages return.

- [ ] **Step 5: Final commit (docs/status if anything pending)**

```bash
git add -A && git commit -m "chore(event-contract): productization phase 1 complete" || echo "nothing to commit"
```

---

## Self-Review Notes

- **Spec coverage:** focus nav (T7/T9/T10), default page (T10), hide perp controls (T9), white-label branding (T8), config panel + runtime config (T1-T5, T11-T12), execution seam (T6), file-size compliance (T9 extraction, T5 split guard, T13). Signal-quality ≥66% is explicitly a separate non-blocking track (spec §6) — no task here by design.
- **Type consistency:** `merge_config`/`params_for_cfg`/`get_config`/`save_config` names match across T3/T4/T5; `EventContractConfig` (TS) mirrors backend `/config` payload; `productConfig`/`isPageVisible` used consistently T7/T9/T10.
- **Assumptions carried from spec:** config panel open to any logged-in user; branding via env, params via DB; visible pages = event-contract/hyper-ai/settings.
