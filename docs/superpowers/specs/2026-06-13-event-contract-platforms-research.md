# 事件合约平台调研（5/10 分钟加密涨跌合约 + API）

日期：2026-06-13

## 结论

真正提供 **5/10 分钟加密「涨跌/二元」合约且有 API** 的平台很少。主流现货/合约交易所没有该原生产品，只能作为**行情数据源**。

## 平台对照

| 平台 | 产品 | 5/10分钟 | API | 认证/模式 | 用途 |
|---|---|---|---|---|---|
| Polymarket | BTC/ETH/XRP Up-or-Down 5min | ✅ 5min | CLOB REST + WebSocket，Py/TS/Rust SDK，`createAndPostOrder()` | 链上 Polygon + USDC，钱包私钥 + API key | 5分钟下单执行（DeFi） |
| Deriv | Rise/Fall 二元期权（含加密标的） | ✅ 5/10min（tick~day 可选） | WebSocket（proposal/buy/sell）+ REST（账户） | app_id + Bearer(OAuth2/PAT) | 5/10分钟下单执行（经纪） |
| Kalshi | 加密 Up/Down 事件合约 | ⚠️ 最短 15min / 小时 | REST + WebSocket + FIX | API Key（RSA 签名），美国合规 KYC | 接近，非 5/10min |
| 二元经纪：Quotex / Pocket Option / IQ Option / Bubinga | 加密二元 | ✅ 5/10min | 多为非官方/逆向 SDK | 不稳定、违规风险 | 不建议集成 |
| Robinhood / Coinbase / Crypto.com / Interactive Brokers | 事件合约（多通过 Kalshi） | ⚠️ 非 5/10min | 受限 / KYC | 美国合规 | 暂不适合 |
| 币安 / OKX / Gate / Bitget / MEXC / Bybit / Hyperliquid | 现货 / 永续 / 期权 | ❌ 无该产品 | 完善 REST + WS | API Key | **行情数据源**（已集成 Binance/Hyperliquid/OKX） |

## 设计含义

- **执行层（真正能下 5/10min 涨跌单）**：现实候选只有 **Polymarket（5min）** 与 **Deriv（5/10min）**；Kalshi 为 15min/小时。
- **数据层**：所有 CEX 的 1m K线都可作为信号输入与回测数据，已集成 3 个，可继续扩。
- 因此「多平台集成」拆成两层：①统一**行情数据源**适配（已有基础，可扩）；②统一**事件合约执行**适配（Polymarket / Deriv / Kalshi 适配器，按需接入，需用户凭证 + KYC + 地域合规）。

## 风险与前置条件

- 真金白银下单 API 集成属高风险外部操作：需用户提供各平台凭证（Deriv app_id+token / Polymarket 钱包+API key / Kalshi RSA key），并受 KYC、地域限制、监管诉讼（多州起诉预测市场）影响。
- 初期系统为**纯模拟出信号 + 手动开单**；执行适配器先做接口与只读（行情/市场列表/报价），下真单需用户逐平台显式授权与配置密钥。

## 来源

- https://polymarket.com/crypto/5M
- https://docs.polymarket.com/
- https://developers.deriv.com/docs/intro/api-overview/
- https://kalshi.com/category/crypto/frequency/fifteen_min
- https://docs.kalshi.com/welcome
- https://medium.com/@XT_com/crypto-event-contracts-prediction-markets-how-to-trade-bitcoin-ethereum-events-51c895b317b9
