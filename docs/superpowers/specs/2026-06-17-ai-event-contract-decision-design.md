# AI 事件合约决策 — 设计文档

**日期:** 2026-06-17
**分支:** event-contract-product
**目标:** 把**整个平台的 AI 交易从永续转成事件合约**。AI 决策大脑(LLM)不再出永续 BUY/SELL/杠杆,而是每分钟主动扫每个空闲格,决定事件合约 long / short / none。**模拟和实盘都以事件合约为准**(同一份 AI 决策喂 paper 与 live)。

**对原永续大脑:不删、页面都保留,只是把"永续"这件事改成事件合约 —— 永续决策/执行循环停用退役(代码留仓、可逆),平台只跑事件合约。** 不采用"新建并行模块各跑各的",而是让 AI 交易的唯一行为变成事件合约。

## 背景与决策

- 现有事件合约系统(`backend/services/event_contract/`)已有完整管线:每分钟 `run_cycle` → `_last_closed_signal` 用某个信号(默认 `of_cvd_fade`)判方向 → 开纸面单 → 到期结算 → 每日胜率表 → 非重绘箭头。信号源可插拔(`OF_SIGNALS` + `default_signal` 配置;`agent_consensus` 多智能体引擎已是其中一个)。
- 用户要：**AI 大脑(LLM)成为决策源**,每分钟扫每格(已确认);模型用哪个无所谓(复用现有配置)。
- **采用方案 A:把 AI 做成事件合约的可插拔"决策信号",复用现有全部管线。** 不改造重耦合的 `ai_decision_service`(永续/按账户),避免大 blast radius 和把产品搞脏。

## 架构

```
run_cycle (每分钟)
  └─ 对每个 symbol × expiry:
       若该格有未结仓 → 跳过 (no-overlap, 不调 LLM)        ← 既合规又省钱
       否则 _last_closed_signal:
          default_signal == "ai_llm" ?
            是 → ai_decision.decide(symbol, expiry, exchange) → long/short/none
            否 → OF_SIGNALS[default_signal](window, params)   (现状不变)
       direction 非空 → 开事件合约纸面单 (entry=下一根开盘, settle=+expiry)
```

新增/改动单元(每个单一职责、可独立测试):

### 1. `event_contract/ai_decision.py`(新增)
`decide(symbol: str, expiry: int, exchange: str) -> Optional[dict]`,返回 `{"direction": "long"|"short"|None, "confidence": float, "reason": str}`(失败返回 None)。
- **上下文组装**(精简,控成本/延迟):当前价；最近 ~30 根 1m K线 OHLCV;订单流 CVD 特征(`load_orderflow` 的 cvd z-score / buy_ratio);`analysis.py` 的 `analyze()` 报告(趋势/动量/波动/量能 + **陷阱探测**);该格近期胜负记忆(`agents/memory.py` 的 settled 统计)。
- **Prompt**:事件合约专用 —— "二元涨跌:在当前价开仓,N 分钟后结算,比现价高=long 赢、低=short 赢。结合以下上下文给 long/short/none + 置信度 + 一句理由。顺势优先,踩到高危陷阱则倾向 none。" 输出强制 JSON。
- **LLM 调用**:复用仓库现有 AI 客户端机制(API 格式按 base URL 自动识别)。模型/key/base 复用 `EVENT_CONTRACT_LLM_*` 环境变量(已存在于可选 judge);未配置则回退到现有决策模型配置。
- **健壮性**:全程 try/except,任何异常/超时/解析失败 → 返回 None,**绝不阻塞每分钟循环**。

### 2. `simulator.py`(改动,最小)
`_last_closed_signal`:当 `cfg.default_signal() == "ai_llm"` 时,调用 `ai_decision.decide(...)` 取方向;否则维持现有 OF 信号/agent_consensus 路径。仅对空闲格调用(no-overlap 守卫已在 `run_signal_cycle`,天然只对空闲格决策)。其余管线零改动。

### 3. 配置(`config.py` / `config_store.py`)
- `default_signal` 增加可选值 `"ai_llm"`。**注意签名差异**:`ai_llm` 需要 `(symbol, expiry, exchange)` 全市场上下文,与 `OF_SIGNALS` 的 `(df, params)->dir` 不同,**不放进 `OF_SIGNALS` 字典**;而是像 `agent_consensus + adaptive` 那样在 `_last_closed_signal` 里走**特殊分支**(`if sig_name == "ai_llm": direction = ai_decision.decide(...)`)。
- 前端下拉:`/strategies` 端点当前返回 `OF_SIGNALS.keys()`,需**额外追加** `"ai_llm"` 到该列表,使配置面板可选中。
- 新增标量 `ai_prefilter: bool`(默认 False):为 True 时,仅当订单流 z-score 超过小阈值才调 LLM,给"每分钟全扫"加一个可选成本上限。

### 4. 审计/复盘
AI 的 `reason` 写入订单审计(新增列或复用日志表)/日志,左侧 `AnalysisPanel` 可展示"AI 为什么这么开"。最小实现:结构化日志 + 可选订单备注字段。

### 5. 执行(模拟 + 实盘统一,都以事件合约为准)
**同一份 AI 事件合约决策,既驱动纸面模拟,也驱动真实下单。** 执行层用模式开关分流:

- `execution_mode = "paper"`(默认):现有 paper 后端,模拟开单/结算,写 `event_contract_orders`(`mode='paper'` 或 `'live'`)。
- `execution_mode = "live"`:`LiveExecutionBackend`(新增,**平台无关**)。`open_order` 经 `platforms/registry` 把单子下到**已配置且有凭证**的平台适配器(Deriv/Polymarket/Kalshi/...);`settle_order` 按平台回报或结算价对账。
  - **凭证缺失自动回退**:无任何平台配好凭证 → 记日志并回退 paper(本机当前即此状态),实盘"已接通但未激活",配好某平台凭证即生效。

`execution.py` 的 `get_execution_backend()` 按 `execution_mode` 返回 paper / live 后端;开单路径也走后端(现在 `run_signal_cycle` 直接写库,需让"开单"经后端,以便 live 时真正下单)。具体平台适配器的真实 API 实现按用户选定平台后单独补(本次"架构做通"为主)。`strategy='ai_llm'`。

## 数据流

`run_cycle` → `_last_closed_signal`(若 ai_llm)→ `ai_decision.decide` → [load_klines + load_orderflow + analyze + memory] → prompt → LLM → JSON → direction → 回到 simulator → **经 `get_execution_backend()` 开单**(paper=模拟 / live=平台适配器真实下单)→ 入库 → 到期 `settle_due_orders`(经同一后端)→ `daily_stats` 面板。决策与执行解耦:同一份 AI 决策喂给 paper 或 live。

## 成本与延迟

- 只对**空闲格**调 LLM(有未结仓的格跳过)。最坏(AI 总是 none)= 4 格 × 每分钟 = 4 次/分钟。
- `ai_prefilter` 可进一步封顶。模型用快/便宜的即可(用户:无所谓)。
- 每次调用串行不阻塞:在 `run_cycle` 内对各格顺序决策,单格失败不影响其他。

## 错误处理

- LLM 不可用/超时/JSON 不合法 → `decide` 返回 None → 该格本分钟不出手(等同 none),循环继续。
- 与现有 `of_cvd_fade` 信号可随时切回(改 `default_signal`),互不破坏。

## 测试

- `ai_decision` JSON 解析 + 健壮性单测(畸形输出 → None)。
- mock-LLM 集成测:桩返回 'long' → 模拟器在空闲格开一单;有未结仓 → 不开。
- 上下文组装单测(给定 df → prompt 含关键字段,不抛异常)。
- 不做真 LLM 回测(太贵);回测路径用确定性桩或保持 of_cvd_fade。

### 6. 退役永续大脑(不删,停用)
- **停止调度/触发**永续 AI 决策循环(`ai_decision_service` 的定时器/信号池触发),使其不再下永续单。代码与表保留(可逆),仅"不再运行"。
- 退役开关用配置(如 `perpetual_brain_enabled=False` 默认),便于回滚。

### 7. 全部页面调用 + 监控以事件合约为准(正式范围)
- **所有页面的数据调用与监控都切到事件合约**:页面保留,但其拉取/展示的数据从永续(持仓/账户/PnL/订单)改为事件合约(`event_contract_orders` / `/api/event-contract/*` / 每日胜率表 / 信号板)。
- 落地方式:盘点全部页面的数据来源(`app/lib/` API 客户端 + 各页 hook),把永续数据调用替换/重定向为事件合约等价数据;WebSocket 监控同理(订阅事件合约订单/结算更新而非永续仓位/持仓推送)。
- 这是较大前端工作,实现计划里单列阶段;后端先就绪事件合约数据/监控接口。

## 不做(YAGNI / 本期外)

- **不删除**永续代码(`ai_decision_service`、持仓/杠杆/交易所执行、财务快照/因子/信号池等)—— 只停用,保留页面与代码。
- 不在本期补**某个具体平台**的真实 API 下单细节(用户选"平台无关,架构先做通");LiveExecutionBackend + 注册表分流做通,具体平台适配器待选定平台 + 凭证后补。
- 不做 AI 决策的历史回测引擎(成本)。

## 验收

- `default_signal="ai_llm"` 时,模拟器对空闲格调用 LLM 出 long/short/none 并开单;有未结仓的格不重复开。
- **执行模式统一**:`execution_mode="paper"` 走模拟;`="live"` 走 `LiveExecutionBackend`,无平台凭证时记日志并回退 paper(本机当前状态);两种模式消费同一份 AI 决策。
- 切回 `of_cvd_fade` 一切如常。
- LLM 故障 / 平台故障时循环不崩。
- 全部后端测试 + 前端 build 通过;文件均 <300 行;无回归。
