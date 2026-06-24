# 事件合约 — 非重绘箭头 K线图 + 顺势信号 设计

日期：2026-06-15
关联：`2026-06-15-event-contract-productization-design.md`（产品化）

## 来源（客户经中间人转述）

- 玩法：二元事件合约,5/10 分钟,开多/开空,结算价比入场价高/低**哪怕 1 点**即赢/输(本金归零)。已实现。
- 策略方向：**单边趋势顺势走、别逆势,底部做反转识别,主要顺势**。
- 指标：要一个**简单箭头** —— 做多在该 K线给**向上箭头**,做空给**向下箭头**。
- **关键(非重绘)**:箭头不能盘中出现又消失;在**这根 K线收盘时才决定/锁定**;然后**下一根 K线第 1 秒入场**。

中间人无法做专业判断,故以下决策由实现方按客户原话直接拍定。

## 决策

### Part 1（先做）— 非重绘箭头 K线图
- **数据源**:箭头 = `EventContractOrder`(mode='live')行。这些行**只在 1m K线收盘、信号确认时由 simulator 创建** → 天然非重绘、永不回撤。
- **后端**:`GET /api/event-contract/signals/history?symbol&expiry_minutes&exchange&limit` 返回:
  - `candles`: 最近 `limit` 根 1m K线(`time, open, high, low, close`,来自 `load_klines`)
  - `markers`: 窗口内的 EventContractOrder(`time`=signal_time 秒、`direction`、`result`、`entry_price`、`settle_price`)
- **前端**:`EventContractChart.tsx`,用 **lightweight-charts v5**:`addSeries(CandlestickSeries)` 画 K线 + `createSeriesMarkers` 画箭头(long→belowBar arrowUp,short→aboveBar arrowDown;按 result 上色:win 绿 / loss 红 / pending 中性)。每 15s 轮询。集成进事件合约页,带 symbol(BTC/ETH)+ expiry(5/10) 选择器。
- **非重绘保证**:markers 只来自已收盘信号的订单行;盘中 forming K线在收盘前没有箭头,收盘后下一周期(≤60s)才出现并永久保留。对应"收盘锁定 + 下根第 1 秒入场"。

### Part 2（后做）— 顺势信号
- 把默认信号从逆势 `of_cvd_fade` 改为**顺势 + 极端反转**逻辑(趋势段跟随、超卖底部反转),加入信号注册表并保留 fade 为可选。
- **诚实约束**:历史回测显示纯顺势约 50–53%(低于 55.6% 保本),fade 约 58–60%。改为顺势后**先用 `/backtest/compare` 跑出真实胜率回报**,不假装能到 66%。

## 非目标
- 不接 TradingView;不改二元结算规则;不接真实下单(仍 Phase 2)。
- Part 1 不依赖 Part 2:箭头图对任何选定的默认信号都成立。

## 测试
- 后端:`/signals/history` 返回 candles+markers,marker.time 落在某根 candle 上;py_compile。
- 前端:`pnpm build` 通过;图表渲染非空(部署后冒烟);箭头方向/颜色正确。
