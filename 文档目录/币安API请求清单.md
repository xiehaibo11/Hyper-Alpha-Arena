# 币安 API 请求清单

更新时间：2026-05-19

本文档整理的是 Hyper Alpha Arena 当前代码中已经接入、可给决策 AI 使用的 Binance 请求。范围是 Binance USDT-M Perpetual Futures，不是币安官方所有产品线的全集。

## 一、总体原则

1. 决策 AI 只使用页面选择的币种，不全市场轮询。
2. 内部币种格式使用 `BTC`、`ETH`，请求币安时转换为 `BTCUSDT`、`ETHUSDT`。
3. 决策 AI 应读取系统封装后的数据块，不要自己生成私有下单签名。
4. API Key、Secret、签名、钱包私密信息禁止进入 Prompt、日志和前端展示。
5. 决策输出必须明确 Binance 交易环境：`Platform: Binance USDT-M Perpetual Futures`。

## 二、基础地址与鉴权

| 用途 | Base URL | 说明 |
|---|---|---|
| 主网行情/交易 | `https://fapi.binance.com` | 当前主网 Binance Futures 请求 |
| 行情适配器测试网 | `https://testnet.binancefuture.com` | `BinanceAdapter` 测试网行情 |
| 交易客户端测试网 | `https://demo-fapi.binance.com` | `BinanceTradingClient` 测试网交易 |
| WebSocket | `wss://fstream.binance.com/ws` | 当前只订阅聚合成交流 |

私有接口签名规则：

- Header：`X-MBX-APIKEY: <api_key>`
- 参数：`timestamp`、`recvWindow=10000`
- 签名：HMAC SHA256，使用 Secret 对 query string 签名，追加 `signature`
- 时间同步：客户端会先请求 `/fapi/v1/time`，计算服务器时间偏移
- 速率信息：读取响应头 `x-mbx-used-weight-1m`

## 三、官方 Binance 请求

### 1. 交易对与精度

| 方法 | Endpoint | 鉴权 | 当前用途 |
|---|---|---|---|
| `GET` | `/fapi/v1/time` | 否 | 同步 Binance 服务器时间 |
| `GET` | `/fapi/v1/exchangeInfo` | 否 | 获取 USDT 永续交易对、tick size、step size、最小数量、最小名义价值 |

决策 AI 使用方式：

- 用 `/fapi/v1/exchangeInfo` 的结果校验页面选择的币种是否可交易。
- 下单前由执行层按 `PRICE_FILTER`、`LOT_SIZE`、`MIN_NOTIONAL` 自动修正价格和数量精度。

### 2. 实时价格、24h 行情、K 线

| 方法 | Endpoint | 鉴权 | 关键参数 | 当前用途 |
|---|---|---|---|---|
| `GET` | `/fapi/v1/ticker/price` | 否 | `symbol=BTCUSDT` | 获取最新成交价 |
| `GET` | `/fapi/v1/ticker/24hr` | 否 | `symbol=BTCUSDT` | 获取 24h 涨跌、成交额、成交量 |
| `GET` | `/fapi/v1/klines` | 否 | `symbol`、`interval`、`limit`、`startTime`、`endTime` | 获取 K 线，用于技术指标和信号回看 |

当前需要支持的周期：

- `1m`
- `3m`
- `5m`
- `15m`
- `30m`

当前采集器额外保留 `1h`，用于更长周期判断。

决策 AI 应从 K 线计算或读取以下指标：

- 趋势：`MA5`、`MA10`、`MA20`、`EMA20`、`EMA50`、`EMA100`、`VWAP`
- 动量：`RSI7`、`RSI14`、`STOCH`、`MACD`
- 波动率：`BOLL`、`ATR14`
- 成交量：`OBV`、成交量变化、主动买卖量

### 3. 订单簿、资金费率、持仓量、多空比

| 方法 | Endpoint | 鉴权 | 关键参数 | 当前用途 |
|---|---|---|---|---|
| `GET` | `/fapi/v1/depth` | 否 | `symbol`、`limit=10` | 获取订单簿快照、买卖盘深度、盘口失衡 |
| `GET` | `/fapi/v1/premiumIndex` | 否 | `symbol` | 获取 mark price、index price、实时资金费率、下一次资金费时间 |
| `GET` | `/fapi/v1/fundingRate` | 否 | `symbol`、`limit`、`startTime`、`endTime` | 获取历史资金费率 |
| `GET` | `/fapi/v1/openInterest` | 否 | `symbol` | 获取实时未平仓量 |
| `GET` | `/futures/data/openInterestHist` | 否 | `symbol`、`period`、`limit` | 获取未平仓量历史 |
| `GET` | `/futures/data/topLongShortPositionRatio` | 否 | `symbol`、`period`、`limit` | 获取大户多空持仓比例 |

决策 AI 使用方式：

- `depth`：计算 `bid_depth_5`、`ask_depth_5`、`depth_ratio`、`order_imbalance`。
- `premiumIndex`：读取 mark price、资金费率，避免只看 last price。
- `openInterest` / `openInterestHist`：判断增仓上涨、减仓上涨、增仓下跌、减仓下跌。
- `topLongShortPositionRatio`：判断大户拥挤方向，避免追入单边拥挤行情。

### 4. WebSocket 实时成交流

| 连接 | Stream | 鉴权 | 当前用途 |
|---|---|---|---|
| `wss://fstream.binance.com/ws` | `<symbol>@aggTrade` | 否 | 聚合成交，15 秒窗口统计主动买入/卖出 |

当前订阅示例：

```json
{
  "method": "SUBSCRIBE",
  "params": ["btcusdt@aggTrade", "ethusdt@aggTrade"],
  "id": 1
}
```

当前写入数据库的 15 秒指标：

- taker buy volume
- taker sell volume
- taker buy notional
- taker sell notional
- large buy notional
- large sell notional
- high price
- low price

### 5. 账户、余额、仓位

| 方法 | Endpoint | 鉴权 | 关键参数 | 当前用途 |
|---|---|---|---|---|
| `GET` | `/fapi/v3/account` | 是 | 无 | 获取账户权益、可用余额、保证金、未实现盈亏 |
| `GET` | `/fapi/v3/positionRisk` | 是 | 可选 `symbol` | 获取持仓数量、开仓价、标记价、强平价、保证金 |
| `GET` | `/fapi/v1/leverageBracket` | 是 | 可选 `symbol` | 获取最大杠杆和名义价值档位 |
| `GET` | `/fapi/v1/income` | 是 | `incomeType`、`startTime`、`endTime`、`limit` | 获取已实现盈亏、资金费、手续费等流水 |
| `GET` | `/fapi/v1/apiReferral/ifNewUser` | 是 | `brokerId` | 检查返佣/经纪商资格 |

决策 AI 使用方式：

- `account`：读取 `total_equity`、`available_balance`、`used_margin`、`maintenance_margin`、`margin_usage_percent`。
- `positionRisk`：读取当前方向、仓位大小、entry price、mark price、unrealized PnL、liquidation price。
- `leverageBracket`：限制最大杠杆，不允许 AI 输出超过账户或币种限制的杠杆。
- `income`：用于交易统计、回看近期亏损来源。

### 6. 普通订单与条件单

| 方法 | Endpoint | 鉴权 | 当前用途 |
|---|---|---|---|
| `POST` | `/fapi/v1/leverage` | 是 | 设置指定币种杠杆 |
| `POST` | `/fapi/v1/order` | 是 | 下普通市价单或限价单 |
| `GET` | `/fapi/v1/order` | 是 | 查询单个普通订单 |
| `DELETE` | `/fapi/v1/order` | 是 | 撤销单个普通订单 |
| `DELETE` | `/fapi/v1/allOpenOrders` | 是 | 撤销某个币种全部普通挂单 |
| `POST` | `/fapi/v1/algoOrder` | 是 | 下 TP/SL 条件单 |
| `DELETE` | `/fapi/v1/algoOrder` | 是 | 撤销 TP/SL 条件单 |
| `GET` | `/fapi/v1/openOrders` | 是 | 查询当前普通挂单 |
| `GET` | `/fapi/v1/openAlgoOrders` | 是 | 查询当前 TP/SL 条件单 |
| `GET` | `/fapi/v1/userTrades` | 是 | 查询成交明细、手续费、已实现盈亏 |
| `GET` | `/fapi/v1/allOrders` | 是 | 查询历史订单，用于把 TP/SL 成交映射回主订单 |

当前支持的普通订单参数：

- `symbol`
- `side=BUY|SELL`
- `type=MARKET|LIMIT`
- `quantity`
- `price`
- `timeInForce=GTC|IOC|FOK|GTX`
- `reduceOnly=true|false`
- `newClientOrderId=x-<broker_id>-<timestamp>`

当前支持的条件单参数：

- `type=STOP_MARKET|TAKE_PROFIT_MARKET|STOP|TAKE_PROFIT`
- `algoType=CONDITIONAL`
- `triggerPrice`
- `workingType=MARK_PRICE`
- `timeInForce=GTE_GTC`
- `clientAlgoId=TP_<main_order_id>` 或 `SL_<main_order_id>`
- `reduceOnly=true`

## 四、项目内部 Binance API 封装

这些是本项目后端暴露给前端、AI 决策和手动交易页面的接口，不是 Binance 官方接口。

| 方法 | 内部路径 | 用途 |
|---|---|---|
| `POST` | `/api/binance/accounts/{account_id}/setup` | 绑定 Binance API Key/Secret |
| `GET` | `/api/binance/accounts/{account_id}/config` | 查看钱包绑定状态，API Key 脱敏 |
| `GET` | `/api/binance/accounts/{account_id}/balance` | 查询余额和保证金 |
| `GET` | `/api/binance/accounts/{account_id}/positions` | 查询当前持仓 |
| `POST` | `/api/binance/accounts/{account_id}/order` | 手动下单，内部走统一 TP/SL 下单逻辑 |
| `POST` | `/api/binance/accounts/{account_id}/close-position` | 平掉指定币种仓位 |
| `DELETE` | `/api/binance/accounts/{account_id}/wallet` | 删除 Binance 钱包绑定 |
| `GET` | `/api/binance/accounts/{account_id}/summary` | 获取账户汇总 |
| `GET` | `/api/binance/accounts/{account_id}/rate-limit` | 查看 Binance 请求权重 |
| `GET` | `/api/binance/price/{symbol}` | 查询公开价格 |
| `GET` | `/api/binance/wallets/all` | 获取所有已绑定 Binance 钱包 |
| `GET` | `/api/binance/accounts/{account_id}/trading-stats` | 查询胜率、盈亏、成交统计 |
| `POST` | `/api/binance/check-rebate-eligibility` | 检查返佣资格 |
| `POST` | `/api/binance/accounts/{account_id}/confirm-limited-binding` | 非返佣主网账户确认限额绑定 |
| `GET` | `/api/binance/accounts/{account_id}/daily-quota` | 查询主网非返佣账户每日交易额度 |
| `GET` | `/api/binance/symbols/available` | 获取缓存的可交易币种列表 |
| `GET` | `/api/binance/symbols/watchlist` | 获取当前页面选择的 Binance 币种 |
| `PUT` | `/api/binance/symbols/watchlist` | 更新当前页面选择的 Binance 币种，并刷新采集器 |

## 五、当前采集频率

| 数据 | 来源 | 频率 |
|---|---|---|
| K 线 | `/fapi/v1/klines` | 每 60 秒 |
| 实时未平仓量 | `/fapi/v1/openInterest` | 每 60 秒 |
| 实时资金费率 | `/fapi/v1/premiumIndex` | 每 60 秒 |
| 大户多空比 | `/futures/data/topLongShortPositionRatio` | 每 300 秒 |
| 订单簿快照 | `/fapi/v1/depth` | 每 15 秒 |
| 主动买卖成交 | WebSocket `@aggTrade` | 15 秒聚合 |

采集币种来源：

- `GET /api/binance/symbols/watchlist`
- 最大 watchlist 数量：10
- 默认币种：`BTC`

## 六、决策 AI 每次触发应读取的数据块

每 5 分钟触发时，决策 AI 应按页面选择的 Binance 币种逐个读取以下数据：

### 1. 交易环境

```text
Platform: Binance USDT-M Perpetual Futures
Exchange: binance
Trading Mode: mainnet 或 testnet
Symbol Format: BTC -> BTCUSDT
Selected Symbols: 页面 watchlist
```

### 2. 每个币种的行情数据

- 最新价：`/fapi/v1/ticker/price`
- 24h 行情：`/fapi/v1/ticker/24hr`
- K 线：`1m`、`3m`、`5m`、`15m`、`30m`
- 技术指标：`MA5`、`MA10`、`MA20`、`EMA20`、`EMA50`、`EMA100`、`VWAP`、`RSI7`、`RSI14`、`STOCH`、`MACD`、`BOLL`、`ATR14`、`OBV`
- 订单簿：bid/ask depth、spread、imbalance
- 资金费率：current funding、next funding time
- 持仓量：open interest、open interest change
- 多空比：top trader long/short ratio
- 主动成交：taker buy/sell、large buy/sell、CVD

### 3. 账户与风控数据

- 总权益
- 可用余额
- 已用保证金
- 维持保证金
- 保证金占用率
- 当前持仓方向、数量、入场价、标记价、未实现盈亏、强平价
- 当前普通挂单
- 当前 TP/SL 条件单
- 最近成交
- 最近已平仓交易
- 近期资金费、手续费、已实现盈亏
- Binance 请求权重和剩余容量

### 4. 决策输出要求

AI 输出必须是中文，并且必须基于 Binance 数据：

```json
{
  "action": "hold|buy|sell|close",
  "symbol": "BTC",
  "exchange": "binance",
  "direction": "long|short|none",
  "leverage": 1,
  "size_usdt": 0,
  "take_profit_price": null,
  "stop_loss_price": null,
  "confidence": 0.0,
  "reason_zh": "中文说明：为什么开仓/平仓/观望"
}
```

执行层再把决策转换成 Binance 私有下单请求，AI 不直接处理签名和 API Secret。

## 七、代码位置

| 文件 | 作用 |
|---|---|
| `backend/services/binance_trading_client.py` | 私有账户、仓位、下单、撤单、成交、盈亏统计 |
| `backend/services/exchanges/binance_adapter.py` | 公开行情、K 线、订单簿、资金费率、持仓量、多空比 |
| `backend/services/exchanges/binance_collector.py` | REST 定时采集 Binance 数据 |
| `backend/services/exchanges/binance_ws_collector.py` | WebSocket 聚合成交采集 |
| `backend/services/binance_symbol_service.py` | 可交易币种和页面 watchlist 管理 |
| `backend/services/market_data.py` | 决策和指标读取 Binance 行情的统一入口 |
| `backend/api/binance_routes.py` | 前端和手动交易页面的 Binance 内部接口 |
| `backend/services/ai_signal_generation_service.py` | 信号生成时读取 Binance K 线上下文 |

## 八、给主决策 AI 的使用结论

主决策 AI 不需要自己请求所有 Binance 官方接口。它需要每次触发时拿到本项目已经封装好的 Binance 数据块：

1. 页面 watchlist 里的币种。
2. 多周期 K 线和技术指标。
3. 订单簿、主动买卖、资金费率、持仓量、多空比。
4. 当前账户余额、保证金、仓位、挂单、TP/SL。
5. 最近成交、已实现盈亏、手续费和资金费。
6. 最终只输出中文交易决策，由执行层负责 Binance 签名下单。
