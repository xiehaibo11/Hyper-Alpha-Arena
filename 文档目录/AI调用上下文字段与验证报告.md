# AI 调用上下文字段与验证报告

更新时间：2026-05-19

## 调查范围

本项目当前是 Python/FastAPI 后端，不存在 `decision/engine.go`。本报告按实际代码链路核对后端所有主要 AI 调用点，重点验证 AI Trader 决策 prompt 可用字段是否真实传入模型。

核心链路：

- AI Trader 决策：`backend/services/ai_decision_service.py`
- Prompt 生成助手：`backend/services/ai_prompt_generation_service.py`
- Program Trader 编程助手：`backend/services/ai_program_service.py`
- Signal 生成助手：`backend/services/ai_signal_generation_service.py`
- 归因诊断助手：`backend/services/ai_attribution_service.py`
- K 线图分析：`backend/services/kline_ai_analysis_service.py`
- Hyper AI 聊天/工具调用：`backend/services/hyper_ai_service.py`
- 新闻分类：`backend/services/news_ai_classifier.py`
- Prompt 回测：`backend/services/prompt_backtest_service.py`
- 记忆/上下文压缩：`backend/services/hyper_ai_memory_service.py`、`backend/services/ai_context_compression_service.py`

## AI Trader 决策 Prompt 字段

AI Trader 唯一上下文拼装入口是 `_build_prompt_context(...)`。用户自定义 AI Trader prompt 只能稳定引用这里返回的字段和动态变量。

### 基础兼容字段

| Prompt 字段 | 含义 | 状态 |
| --- | --- | --- |
| `{account_state}` | 旧版账户状态摘要 | 已传递 |
| `{market_snapshot}` | 旧版市场快照 | 已传递 |
| `{session_context}` | 旧版会话上下文 | 已传递 |
| `{sampling_data}` | 多币种采样/价格历史摘要 | 已传递 |
| `{decision_task}` | 决策任务说明 | 已传递 |
| `{output_format}` | 平台强制输出格式 | 必填，已传递 |
| `{prices_json}` | 价格 JSON | 已传递 |
| `{portfolio_json}` | 组合 JSON | 已传递 |
| `{portfolio_positions_json}` | 持仓 JSON | 已传递 |
| `{news_section}` | 新闻摘要 | 已传递 |
| `{account_name}` | AI Trader 名称 | 已传递 |
| `{model_name}` | 当前模型名 | 已传递 |

### 账户与风控字段

| Prompt 字段 | 含义 | 状态 |
| --- | --- | --- |
| `{runtime_minutes}` | 运行时长分钟数 | 已传递 |
| `{current_time_utc}` | 当前 UTC 时间 | 已传递 |
| `{total_return_percent}` | 组合总收益率 | 已传递 |
| `{available_cash}` | 可用现金/余额摘要 | 已传递 |
| `{total_account_value}` | 账户总价值 | 已传递 |
| `{total_equity}` | 合约账户权益 | 已传递 |
| `{available_balance}` | 可用余额 | 已传递 |
| `{used_margin}` | 已用保证金 | 已传递 |
| `{margin_usage_percent}` | 保证金使用率 | 已传递 |
| `{maintenance_margin}` | 维持保证金 | 已传递 |
| `{margin_info}` | 保证金摘要 | 已传递 |
| `{trading_environment}` | 交易平台和环境说明 | 已传递 |
| `{environment}` | `testnet` / `mainnet` | 已传递 |
| `{real_trading_warning}` | 主网风险提示 | 已传递 |
| `{operational_constraints}` | 运行约束 | 已传递 |
| `{leverage_constraints}` | 杠杆约束 | 已传递 |
| `{max_leverage}` | 当前账户最大杠杆 | 已传递 |
| `{default_leverage}` | 默认杠杆 | 已传递 |

### 持仓、订单、触发字段

| Prompt 字段 | 含义 | 状态 |
| --- | --- | --- |
| `{positions_detail}` | 开仓明细：方向、数量、入场价、标记价、仓位价值、未实现盈亏、ROE、资金费、净盈亏、杠杆、保证金、强平价、持仓时长 | 已传递 |
| `{positions_structured_json}` | 机器可读持仓 JSON：`symbol`、`side`、`size`、`entry_price`、`mark_price`、`unrealized_pnl_usd`、`unrealized_pnl_pct`、`margin_used_usd`、`leverage`、`liquidation_price`、`liquidation_distance_pct`、`holding_duration`、`peak_pnl_pct`（来源提供时） | 已传递 |
| `{holdings_detail}` | 现货/旧版持仓摘要；合约环境下复用 `{positions_detail}` | 已传递 |
| `{recent_trades_summary}` | 近期平仓记录，并包含开放订单摘要 | 已传递 |
| `{recent_trades_json}` | 机器可读最近交易 JSON | 已传递 |
| `{open_orders_detail}` | 开放订单明细 | 已补齐传递 |
| `{open_orders_json}` | 机器可读开放订单 JSON | 已传递 |
| `{api_query_snapshot_json}` | 只读 Binance/OKX 公开 API 快照：ticker、K线、订单簿、资金费率、OI、多空情绪、近期成交和历史数据（有界数量，接口失败时分段记录错误） | 已传递 |
| `{trigger_context}` | 信号触发或定时触发说明 | 已传递 |

关键核对：

- 盈亏金额：`positions_detail` 中通过 `Unrealized P&L (exchange)`、`Net P&L` 自然语言传递。
- 盈亏百分比：`positions_detail` 中通过 `ROE` 传递。
- 保证金：`positions_detail` 中通过 `Margin` 传递。
- 入场价、当前价、杠杆、强平价、持仓时长：均在 `positions_detail` 中传递。
- 最高收益率 / `PeakPnLPct`：当前 Python AI Trader 不会凭空计算历史峰值；如果上游持仓来源提供 `peak_pnl_pct` / `PeakPnLPct`，会进入 `{positions_structured_json}`。否则该字段为 `null`，prompt 不应要求 AI 自行假设回撤。

### 市场与币种字段

| Prompt 字段 | 含义 | 状态 |
| --- | --- | --- |
| `{market_prices}` | 选中币种价格摘要 | 已传递 |
| `{selected_symbols_csv}` | 支持交易币种 CSV | 已传递 |
| `{selected_symbols_detail}` | 支持交易币种详情 | 已传递 |
| `{selected_symbols_count}` | 支持交易币种数量 | 已传递 |

动态变量模式：

- `{BTC_market_data}`、`{ETH_market_data}`：单币种市场数据。
- `{BTC_klines_15m}`、`{ETH_klines_1h}`：K 线数据，可写 `{BTC_klines_1h}(200)` 指定数量。
- `{BTC_RSI14_15m}`、`{BTC_MACD_15m}`、`{BTC_MA_15m}`、`{BTC_BOLL_15m}` 等技术指标。
- `{BTC_CVD_15m}`、`{BTC_OI_DELTA_1h}`、`{BTC_FUNDING_4h}` 等资金流指标。
- `{market_regime}`、`{BTC_market_regime_5m}`、`{trigger_market_regime}`：市场状态。
- `{BTC_factor_1h_RSI21}`、`{BTC_factor_RSI21}`：因子变量。
- `{BTC_news_sentiment}`、`{BTC_news_headlines_4h}`、`{macro_news}`、`{crypto_news_detail}`：新闻变量。

## 其他后端 AI 调用上下文

| 调用点 | 传给 AI 的主要上下文 | 是否给 AI Trader prompt 直接使用 |
| --- | --- | --- |
| Prompt 生成助手 | 当前 prompt、会话历史、变量参考、预览工具、行情/决策查询工具 | 否，属于提示词编辑助手 |
| Program Trader 编程助手 | `MarketData` API 说明、账户字段、持仓、订单、信号池、行情方法、程序代码上下文 | 否，属于程序策略生成 |
| Signal 生成助手 | 信号生成 system prompt、K 线/指标/组合预测工具 | 否 |
| 归因诊断助手 | 账户、prompt、信号池、决策链、因子归因等工具返回 | 否 |
| K 线图分析 | `symbol`、`exchange`、`period`、价格、成交量、OI、资金费、K 线摘要、指标摘要、持仓摘要、用户问题 | 否 |
| Hyper AI 聊天 | system prompt、用户档案、长期记忆、历史消息、工具列表及工具结果 | 否 |
| 新闻分类 | 新闻文章、watchlist、交易所币种映射 | 否 |
| Prompt 回测 | 回测 system prompt、修改后的 prompt、历史任务上下文 | 否 |
| 记忆/上下文压缩 | 聊天历史、摘要目标、记忆候选 | 否 |

结论：这些 AI 调用有自己的上下文和工具，不等于 AI Trader 决策 prompt 可直接引用的字段。AI Trader 自定义 prompt 字段必须以 `_build_prompt_context(...)` 和动态变量解析器为准。

## 已落地校验与保护

本次执行已补充以下保护：

- 新增统一校验服务 `backend/services/prompt_validation_service.py`。
- 保存提示词时校验字段白名单、动态变量模式、`{output_format}` 必填、Python format 语法。
- UI 保存、Hyper AI `save_prompt`、预览、AI Trader 实际执行链路均接入校验。
- 禁止自定义 prompt 使用 `<reasoning>`、`<decision>` XML 保留标签。
- AI Trader 调用模型时新增 system 级硬约束：用户 prompt 不能覆盖风控、杠杆、交易环境和输出格式。
- 模型返回解析改为严格 JSON-only：必须是单个 JSON object，并且包含 `decisions` 数组；不再从 markdown、说明文字或破损 JSON 中人工猜测交易指令。
- 补齐 `{open_orders_detail}` 的实际上下文传递，避免之前文档/预览认为可用但执行链路缺字段。
- 新增 `{positions_structured_json}`、`{recent_trades_json}`、`{open_orders_json}`，把关键交易事实用机器可读 JSON 传给 prompt，减少自然语言标签歧义。
- 新增共享只读交易所查询工具，Hyper AI、Prompt AI、Program AI、Signal AI、Attribution AI 均可调用 Binance/OKX 公开行情数据；AI Trader 决策上下文直接注入 Binance/OKX API 快照。

## 当前风险与后续建议

- 如果业务确实需要“最高收益率 / 回撤幅度”，应在持仓来源数据中新增真实峰值收益字段；当前上下文只传递来源真实提供的 `peak_pnl_pct`，不能让 prompt 自行假设。
- 风控与输出格式应继续保持平台硬约束；自定义 prompt 只能表达策略偏好。
- OKX 当前只接入公开市场数据；项目内尚未配置 OKX 私有账户/下单 API，因此 AI 不会获得 OKX 私钥、余额或下单权限。
- Prompt 中需要自然语言原因时，应放入 JSON 字符串字段 `reason` 或 `trading_strategy`，不得输出 JSON 外说明、markdown 或 XML 标签。
