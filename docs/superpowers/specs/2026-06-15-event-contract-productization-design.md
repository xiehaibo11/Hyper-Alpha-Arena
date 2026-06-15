# 事件合约产品化（整体收束）— 设计文档

日期：2026-06-15
关联：`2026-06-13-event-contract-system-design.md`（事件合约功能本身，已实现）、`功能需求.md`

## 背景与目标

本仓库是为**特定客户定制**的独立仓库。目标：把现有多功能 AI 交易平台（Hyper Alpha Arena）**收束为一个专注的"事件合约（二元涨跌信号）"产品**，干净专一、可白标、客户可自助配置。

事件合约功能本身已实现（见 6-13 设计）。本期工作 = **产品化改造**：聚焦 UI、白标品牌、客户自助配置面板，并为未来真实下单预留架构缝隙。

## 已锁定范围（来自客户澄清）

- **事件合约为主产品**，**保留 Hyper AI 对话入口**；其余模块（AI 永续决策、Program Trader、因子引擎、Arena 竞技场、归因、手动交易、K线、Advanced、System Logs、Trader/Prompt/Signal 管理）**隐藏不删**。
- 形态：**信号 + 模拟盘**（不接真实资金，客户据信号手动交易）。真实下单为 **Phase 2**，本期仅留接口边界。
- 标的：维持现状 **BTC/ETH，5/10 分钟到期**。
- 核心价值：**干净专一 UI + 信号胜率质量（≥66%）+ 客户自助配置/品牌化**。

## 整体策略：方案 A — 配置驱动的"聚焦模式"

加一个**产品模式开关**，把多功能平台收束成单一产品，**不物理删除**其他模块代码。理由：① 信号+模拟、保留 Hyper AI 决定了底层引擎（K线/订单流/交易所采集/快照/Hyper AI 工具链）仍需存在；② 大规模删除风险高、难回退，而隐藏即可达成"干净专一"的交付观感；③ 客户专属仓库，隐藏的死代码不影响交付，后续可在 Phase 2 裁剪。

被否方案：B（物理删除模块）成本与破坏风险过高，且与"保留 Hyper AI"冲突；C（先隐藏后裁剪）= 本方案 + 可选的后续裁剪。

## 架构设计

### 1. 前端 — 产品聚焦

**1.1 产品配置 `frontend/app/lib/productConfig.ts`（新建，~40 行）**
由 `import.meta.env.VITE_PRODUCT_MODE` 驱动（本仓库默认 `'event_contract'`）。导出：
- `visiblePages: string[]` — 聚焦模式 = `['event-contract', 'hyper-ai', 'settings']`
- `defaultPage: string` — 聚焦模式 = `'event-contract'`
- `showExchangeSelector / showTradingModeToggle: boolean` — 聚焦模式 = `false`
- `'full'` 模式保留全部页面（便于内部开发/回退）。

**1.2 默认落地页** `main.tsx:33` 的 `useState<string>('hyper-ai')` → 改为读 `productConfig.defaultPage`。

**1.3 侧边栏过滤 `Sidebar.tsx`（现 391 行）**
- 将 `desktopNav` 数组（138-152 行）**抽到新文件** `frontend/app/components/layout/navItems.ts`，Sidebar 引入后按 `productConfig.visiblePages` 过滤。（既实现聚焦，又给 Sidebar 减重，符合文件体积约束。）
- 按 `showExchangeSelector / showTradingModeToggle` 条件隐藏交易所选择块（170-188 行）与 Testnet/Mainnet 切换块（190+ 行）。
- 顶部硬编码品牌（164-165 行 logo + "Hyper Alpha Arena"）→ 改用白标配置（见 2）。

**1.4 移动端导航** 同步按 `visiblePages` 过滤（`components/mobile/` 与 Sidebar 移动分支），避免隐藏页仍可达。

### 2. 前端 — 白标品牌化

**2.1 `frontend/app/lib/branding.ts`（改）**
```ts
export const SITE_NAME = import.meta.env.VITE_SITE_NAME ?? 'Hyper Alpha Arena'
export const SITE_URL  = import.meta.env.VITE_SITE_URL  ?? '/'
export const SITE_LOGO = import.meta.env.VITE_SITE_LOGO ?? '/static/logo_app.png'
```
- Sidebar 品牌文字/Logo、Header、`index.html` `<title>`/favicon 全部改用 `SITE_*`。
- `.env.example` 增加 `VITE_PRODUCT_MODE / VITE_SITE_NAME / VITE_SITE_URL / VITE_SITE_LOGO` 并注释。
- 部署时按客户注入，无需改码。

### 3. 前端 — 客户自助配置面板

**3.1 位置**：事件合约页加"配置/⚙️"Tab（`components/event-contract/EventContractConfigPanel.tsx`，新建，≤300 行）。
**3.2 可编辑项**（对应后端 config）：启用标的、到期档位、`payout`、各 (symbol,expiry) 信号参数 `window/thr`、默认信号、每日重置时区。
**3.3 API**：`getEventContractConfig() / updateEventContractConfig(cfg)` 加入 `frontend/app/lib/eventContractApi.ts`。
**3.4 权限**：单客户部署，对**已登录用户**开放（假设，见下）。
**3.5 i18n**：所有文案进 `en.json` + `zh.json`。

### 4. 后端 — 运行时配置

**4.1 模型 `database/models_event_contract_config.py`（新建）** — `EventContractConfig` 表（单行或 key-value JSON）：`symbols, expiries, payout, default_signal, signal_params(JSON), daily_reset_tz, updated_at`。在 `main.py` 导入以注册 `create_all`。
**4.2 迁移** `database/migrations/create_event_contract_config_table.py`（**幂等**：建表前检查存在；用当前 `config.py` 的值做种子）。
**4.3 配置存取 `services/event_contract/config_store.py`（新建，≤150 行）**：DB 优先、`config.py` 作默认；带进程内缓存 + 失效（写时刷新）。导出 `get_config() / save_config() / params_for() / symbols() / expiries() / payout() / daily_reset_tz()`。
**4.4 重构现有引用**：`config.py` 保留为**默认常量 + 种子**；`simulator.py`、`orderflow.py`、`backtest.py`、`stats.py`、路由层把 `from .config import SYMBOLS/EXPIRIES/PAYOUT/params_for` 改为经 `config_store` 取值（运行时可变）。逐文件验证体积不超限。
**4.5 路由** `api/event_contract_routes.py` 增 `GET/PUT /api/event-contract/config` 与 `GET /api/event-contract/branding`（若需后端供白标；否则品牌纯前端 env）。注意该文件体积，必要时拆 `event_contract_config_routes.py`。

### 5. 后端 — 真实下单接口边界（Phase 2 预留，本期仅留缝）

`services/event_contract/execution.py`（新建，薄接口）：
```python
class ExecutionBackend(Protocol):
    def open_order(self, order: EventContractOrder) -> None: ...
    def settle_order(self, order: EventContractOrder, settle_price: float) -> None: ...
class PaperExecutionBackend:  # 现有纸面行为
    ...
```
`simulator.py` 通过 `get_execution_backend()` 选择后端（本期恒为 Paper）。未来 `LiveExecutionBackend` 可插入而不改 simulator 主流程。**本期不实现 Live。**

### 6. 信号质量支线（独立、不阻塞主线）

复用已有 `GET /api/event-contract/backtest/compare`：对 `of_cvd_fade` 及候选信号做参数扫描 / 新信号试验，把 BTC/ETH×5/10m 的实测胜率从 ~58-60% 推向 ≥66%。属于**迭代调参研究**,不阻塞产品改造,结论回填到 `config_store` 的 `signal_params`。

## 数据流（不变）

scheduler(每分钟) → `simulator.run_cycle` → `config_store` 取参 → `orderflow` 评估 `of_cvd_fade` → 写 `EventContractOrder(pending)` → 到期回填结算 → `stats` 聚合 → 前端轮询 `/signals/live` + `/stats/daily` 展示。配置面板 → `PUT /config` → `config_store` 刷新 → 下一周期生效。

## 非目标（YAGNI）

- 不接真实下单 API / TradingView（Phase 2）。
- 不物理删除其他模块（仅隐藏；Phase 2 可选裁剪）。
- 不扩展标的/到期档位（维持 BTC/ETH、5/10m）。
- 不改动 Hyper AI 内部（仅保留入口；其工具/技能裁剪非本期）。
- 不做多租户/复杂权限（单客户部署）。

## 文件体积与边界

- `Sidebar.tsx`：导航数组外移到 `navItems.ts` → 减重,不超限。
- 新后端文件均控制在 ≤300 行;`event_contract_routes.py` 增长若逼近上限则拆 `_config_routes.py`。
- 配置面板组件单一职责,API 逻辑只走 `lib/eventContractApi.ts`。

## 测试

- 后端:`backend/tests/test_event_contract_config_store.py` — DB 优先/默认回退/缓存失效;`params_for` 运行时改值生效。
- 迁移幂等:重复运行 migration 不报错、不重复种子。
- 前端:`pnpm build` 通过;手动验证聚焦模式仅显示三页、默认落地事件合约、白标 env 生效、配置面板读写。
- 回归:Hyper AI 入口仍可加载;事件合约 `/signals/live`、`/stats/daily`、`/backtest/compare` 正常。

## 假设（如不符请纠正）

1. 配置面板对已登录用户开放(无独立管理员角色)。
2. 品牌走**部署时 env**(你按客户注入);信号参数走**运行时 DB 面板**(客户自调)。
3. 聚焦模式可见页 = 事件合约 / Hyper AI / 设置。如需增减(如保留 K线 给客户看图),告知即可。

## 交付阶段

- **Phase 1（本期）**:聚焦模式 + 白标 + 配置面板 + 运行时配置 + 执行接口缝隙。
- **Phase 2（后续）**:真实下单后端、可选后端死代码裁剪、Hyper AI 工具/技能精简、信号≥66% 达标。
