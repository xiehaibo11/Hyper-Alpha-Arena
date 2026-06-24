"""Event-contract (binary up/down) signal system.

Modules:
- strategies: pluggable directional signal strategies (long/short/none)
- backtest: historical win-rate evaluation over 1m klines
- simulator: live forward paper-simulation driven by the scheduler
- stats: daily win-rate aggregation (resets at local midnight)
"""
