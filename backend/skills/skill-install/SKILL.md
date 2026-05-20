---
name: skill-install
shortcut: install
description: Quantitative trading decision principles for AI decisioning. Use when evaluating trade direction, regime, risk, position sizing, mean reversion, trend following, momentum, portfolio allocation, tail risk, stop-loss fragility, or volatility state before making or reviewing a trading decision.
description_zh: 给交易决策 AI 使用的量化交易原则库；当需要判断方向、行情状态、仓位、风控、均值回归、趋势跟随、动量、组合分散、尾部风险、止损脆弱点或波动率状态时使用。
---

# Quant Decision Principles

Use this skill as a decision framework, not as a signal by itself. Always combine
these principles with current account state, positions, market data, risk limits,
and the user's configured strategy rules.

## Decision Workflow

1. Identify the current market regime:
   - Ranging or overextended: consider mean reversion.
   - Directional expansion: consider trend following.
   - Short-term consensus acceleration: consider momentum.
   - Shock or abnormal volatility: reduce leverage and reassess tail risk.

2. Convert the regime into a trade hypothesis:
   - State what would make the hypothesis valid.
   - State what would invalidate it.
   - Avoid guessing tops or bottoms without measurable evidence.

3. Size the trade conservatively:
   - Use Kelly-style thinking only as an upper bound, not an automatic size.
   - Lower size when win rate, payoff ratio, liquidity, or volatility assumptions are weak.
   - Avoid increasing exposure just because confidence language is strong.

4. Check portfolio and correlation risk:
   - Avoid stacking highly correlated positions as if they are independent.
   - Prefer diversified exposure when correlations are unstable.
   - Treat covariance spikes as a warning that diversification may temporarily fail.

5. Check stop-loss and liquidity fragility:
   - A stop line is not a single price; it is a cluster of triggered orders.
   - If liquidity near the stop is thin, smaller shocks can trigger cascade moves.
   - Avoid placing large orders into areas where impact can exceed available absorption.

6. Decide action:
   - Enter only when the selected principle has data support.
   - Hold when the hypothesis is still valid and risk remains acceptable.
   - Reduce or close when volatility regime, liquidity, or invalidation conditions change.

## Core Strategy Principles

### Mean Reversion

Price does not stay far from its center forever. Measure deviation from a
statistical center instead of relying on emotional impressions.

Use when:
- Price has moved outside its normal range.
- The move appears overextended relative to volatility.
- There is evidence that panic or euphoria is fading.

Avoid when:
- A strong trend is expanding with volume and volatility confirmation.
- The market is repricing due to new information.

### Trend Following

Do not guess tops or bottoms. Confirm direction from price, volume, and
volatility structure, then follow while the trend remains intact.

Use when:
- Direction is persistent across timeframes.
- Volume or open interest supports continuation.
- Momentum is broadening rather than fading.

Exit or reduce when:
- Momentum decays.
- Volatility shifts into disorder.
- The trend loses confirmation across key inputs.

### Momentum

Momentum captures short-term "strength continues" behavior. It trades the
market consensus after it forms, not before it exists.

Use when:
- Price acceleration is confirmed.
- Volume or order-flow pressure supports the move.
- Pullbacks are shallow and quickly absorbed.

Avoid when:
- Speed is falling while price keeps extending.
- Funding, crowding, or liquidation risk becomes extreme.

## Position Sizing And Portfolio Logic

### Kelly Formula

Kelly-style sizing links capital allocation to edge:
- Higher win rate and better payoff ratio justify more size.
- Higher failure probability forces smaller size.
- In practice, use fractional Kelly or stricter caps because estimates are noisy.

Never allow Kelly output to override account-level drawdown, leverage, or
liquidity limits.

### Markowitz Portfolio Theory

Do not judge assets only by standalone expected return. Consider variance,
covariance, and correlation so the portfolio seeks better return per unit risk.

Use this when:
- Several symbols are candidates at the same time.
- Exposure is concentrated in one market theme.
- Correlations are changing quickly.

## Probability And Risk Models

### Normal Distribution

Use as a baseline for ordinary return variation, confidence intervals, and
basic risk estimates. Do not trust it during extreme events because it
underestimates tails.

### Poisson Distribution

Use for discrete jump or shock arrivals, especially when modeling sudden stop
cascades, black-swan-like events, or clustered liquidation triggers.

### Student's t-distribution

Use when tails are fat and extreme moves occur more often than a normal model
would imply. Prefer this lens when volatility is elevated or regime stability is
questionable.

### Covariance

Use covariance to detect how assets move together. When covariance rises,
positions that looked diversified can become one concentrated risk.

### Bayesian Updating

Treat every new candle, fill, news item, or market-flow update as evidence that
changes the prior view. Do not freeze the decision once new evidence invalidates
the old regime.

## Stop-Loss Fragility Model

A stop-loss level is a cluster of conditional sell or buy orders around a price.
Quantitative trading measures market impact and liquidity absorption instead of
predicting direction by opinion.

Check:
- Arrival intensity: use Poisson-arrival thinking for shock frequency.
- Liquidity density: estimate order depth near likely stop zones.
- Trigger chain: if impact is greater than nearby absorption, stop orders may
  recursively release and accelerate the move.

Trading implication:
- Fragile stop zones can be opportunity areas for breakout or cascade trades.
- They are also dangerous places for oversized entries.

## Regime And Volatility Models

### Geometric Brownian Motion

Think of price as drift plus random diffusion. Drift estimates direction;
volatility estimates the width of possible future paths.

### Hidden Markov Model

The true market state is hidden. Infer whether the market is calm, trending, or
in shock by observing returns, volume, volatility, and flow. Update state
probabilities as new data arrives.

### Cointegration And Statistical Arbitrage

Trade spread deviation, not naked direction. When two assets maintain a stable
long-term relationship, use spread Z-score to identify high-estimated-value and
low-estimated-value legs. Hedge direction risk where practical.

### GARCH Volatility

Volatility has memory. Shocks can create volatility clustering, where calm
periods persist and panic periods persist. Reduce leverage and tighten risk
controls when the model suggests a dangerous volatility state.

## Decision Guardrails

- Do not open a trade because one principle sounds persuasive; require data.
- Do not average down a failing mean-reversion trade without a new risk check.
- Do not add to a trend just as momentum and liquidity support are weakening.
- Do not treat multiple correlated crypto positions as independent bets.
- Always state the invalidation condition before entering or increasing risk.
