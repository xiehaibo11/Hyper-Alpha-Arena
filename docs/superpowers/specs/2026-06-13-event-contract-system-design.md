# 事件合约多空信号系统 — 设计文档

日期：2026-06-13
来源需求：`功能需求.md`

## 目标

把项目改造成**事件合约（二元涨跌）信号系统**：基于 1 分钟 K 线，对 BTC/ETH 输出 **多 / 空 / 无** 信号，支持 **5 分钟 / 10 分钟**到期，**多平台**（Binance / Hyperliquid / OKX），先**历史回测**评估胜率，再**实时纸上模拟**累积数据。核心验收：**平推固定金额、胜率 ≥ 66% 且净收益为正**。

## 已锁定决策

- 信号算法：**可插拔策略库**，回测挑最优后迭代（66% 由策略经验决定，框架不保证）。
- 币种：**BTC + ETH**；到期：**5min + 10min** 两档。
- 数据源：交易所参数化，默认 **Binance** 1m K线（`crypto_klines.period='1m'`，已采集）；支持 Hyperliquid/OKX。
- 模式：纯**模拟出信号**，客户手动开单（初期不接 TradingView / 不下真单）。
- 统计周期：每日 **00:00 重置**（时区默认 Asia/Hong_Kong，可配置）。
- 赔付模型：可配置 `payout`（默认 0.8，典型二元期权），用于计算"平推净收益"。胜率为主指标。

## 交易/结算规则（来自需求）

1m K线收盘确认信号 → 下一根 K线开盘价为开仓价 → N 分钟（5/10）后的价格为结算价。
多单：结算价 > 开仓价 为赢；空单：结算价 < 开仓价 为赢；相等判负（保守）。

## 架构（方案 A：独立模块 + 新页面）

### 后端
- `database/models_event_contract.py` — `EventContractOrder` 表（在 main.py 中导入以便 create_all 注册）。
  字段：id, mode(backtest/live), exchange, symbol, strategy, direction(long/short),
  expiry_minutes, signal_time, entry_time, entry_price, settle_time, settle_price,
  result(win/loss/pending), payout, pnl, created_at。索引：(mode, symbol, expiry_minutes, entry_time)。
- `services/event_contract/strategies.py` — 策略注册表。每个策略：`evaluate(klines_df) -> 'long'|'short'|None`。
  初始基线：动量(EMA/ROC)、均值回归(RSI/布林)、订单流(taker buy 比)等若干，全部可配置。
- `services/event_contract/backtest.py` — 历史回测：取某交易所某币 1m K线，逐根滚动评估策略，
  按规则开仓/结算，统计 总单/赢/输/胜率/净收益（按 payout）。复用 `backend/backtest/historical_data_provider`。
- `services/event_contract/simulator.py` — 实时纸上模拟：APScheduler 每分钟在 1m 收盘后评估策略，
  写入 pending 单；到期时回填结算价并判定赢负。
- `services/event_contract/stats.py` — 每日统计聚合（当日总单/赢/输/胜率，按时区 00:00 切分）。
- `api/event_contract_routes.py` — 路由：当前信号(live state)、每日统计、回测运行与结果、历史明细。
  在 main.py 注册。

### 前端
- 新页面 `#event-contract`（加入导航）：
  - **信号展示**：BTC/ETH × 5m/10m，大号 多/空/无 指示牌（绿/红/灰），含倒计时与开仓/结算价。
  - **左上角每日统计表**：开单总数 / 赢 / 输 / 胜率（按需求样式），00:00 重置。
  - **回测面板**：选交易所/币种/到期/策略/时间段 → 跑回测 → 显示胜率与净收益曲线。
  - 实时更新：轮询或复用 WebSocket。
- i18n：新增字符串到 en.json / zh.json。

## 数据流

历史回测：UI → `/api/event-contract/backtest` → backtest.py 读 crypto_klines → 统计返回。
实时：scheduler(每分钟) → simulator 评估策略 → 写 EventContractOrder(pending) → 到期回填 → stats 聚合 → 前端轮询展示。

## 非目标（YAGNI）

- 不下真单、不接交易所下单 API、不接 TradingView。
- 不做价格区间/外部事件合约（仅涨跌二元）。
- 不重构现有 AI/永续交易模块。

## 验收对齐

胜率 = 赢单 ÷ 已结算单；净收益 = Σ(win·payout − loss·1)·单注。回测样本量、数据源、时间段在结果页明确展示，便于核对 ≥66%。
