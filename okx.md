OKX API v5 官方文档：

https://www.okx.com/docs-v5/zh/#overview
https://www.okx.com/docs-v5/en/

已接入项目的公共数据接口：

- 交易产品：`GET /api/v5/public/instruments`
- 最新行情：`GET /api/v5/market/ticker`
- 批量行情：`GET /api/v5/market/tickers`
- K线：`GET /api/v5/market/history-candles`
- 盘口：`GET /api/v5/market/books`
- 最近成交：`GET /api/v5/market/trades`
- 资金费率：`GET /api/v5/public/funding-rate`
- 资金费率历史：`GET /api/v5/public/funding-rate-history`
- 持仓量：`GET /api/v5/public/open-interest`
- 标记价格：`GET /api/v5/public/mark-price`
- 指数价格：`GET /api/v5/market/index-tickers`
- 多空账户比：`GET /api/v5/rubik/stat/contracts/long-short-account-ratio`
- 合约持仓量/成交量历史：`GET /api/v5/rubik/stat/contracts/open-interest-volume`
- 主动买卖量：`GET /api/v5/rubik/stat/taker-volume`

项目内部接入点：

- `backend/services/exchanges/okx_adapter.py`
- `backend/services/exchanges/okx_collector.py`
- `backend/services/okx_symbol_service.py`
- `backend/api/okx_routes.py`
- `/api/market/*` 支持 `market=okx`
- K-Line 自动补数据支持 `exchange=okx`

说明：

- 现在接入的是无需 API key 的公共行情/统计数据。
- 账户、下单、资金账户、订单历史等私有 API 需要 OKX API key、secret、passphrase 和权限设计，不能混入公共数据接入。
