"""Factor and OI trigger helpers for signal backtests."""

from datetime import datetime
from typing import Dict, List
from sqlalchemy.orm import Session

from services.signal_backtest_common import TIMEFRAME_MS, logger


class SignalBacktestFactorMixin:
    def _find_oi_change_triggers_in_range(
        self, db: Session, signal_def: Dict, symbol: str, time_window: str,
        kline_min_ts: int = None, kline_max_ts: int = None,
        exchange: str = "hyperliquid"
    ) -> List[Dict]:
        """
        Find OI USD change signal triggers.

        OI change measures the absolute USD value change in open interest.
        Formula: (current_OI - previous_OI) × mark_price
        Returns USD value (can be positive or negative).
        """
        from database.models import MarketAssetMetrics
        from datetime import datetime

        condition = signal_def.get("trigger_condition", {})
        operator = condition.get("operator")
        threshold = condition.get("threshold")

        interval_ms = TIMEFRAME_MS.get(time_window, 300000)

        # Load data for backtest range + one extra interval for first change calc
        current_time_ms = kline_max_ts or int(datetime.utcnow().timestamp() * 1000)
        start_time_ms = (kline_min_ts or current_time_ms - 24*60*60*1000) - interval_ms

        records = db.query(
            MarketAssetMetrics.timestamp,
            MarketAssetMetrics.open_interest,
            MarketAssetMetrics.mark_price
        ).filter(
            MarketAssetMetrics.exchange == exchange,
            MarketAssetMetrics.symbol == symbol.upper(),
            MarketAssetMetrics.timestamp >= start_time_ms,
            MarketAssetMetrics.timestamp <= current_time_ms,
            MarketAssetMetrics.open_interest.isnot(None),
            MarketAssetMetrics.mark_price.isnot(None)
        ).order_by(MarketAssetMetrics.timestamp).all()

        if not records:
            logger.warning(f"[Backtest] No OI data for {symbol}")
            return []

        # Aggregate by interval bucket
        buckets = {}
        for ts, oi, price in records:
            bucket_ts = (ts // interval_ms) * interval_ms
            buckets[bucket_ts] = (float(oi), float(price))

        sorted_times = sorted(buckets.keys())
        if len(sorted_times) < 2:
            return []

        logger.warning(f"[Backtest] Loaded {len(buckets)} OI buckets for USD change calc")

        # Calculate USD changes and find triggers
        triggers = []
        was_active = False
        backtest_start = kline_min_ts or sorted_times[1]

        for i in range(1, len(sorted_times)):
            check_time = sorted_times[i]
            if check_time < backtest_start:
                continue

            curr_oi, curr_price = buckets[sorted_times[i]]
            prev_oi, _ = buckets[sorted_times[i-1]]
            change_usd = (curr_oi - prev_oi) * curr_price

            # Evaluate condition
            condition_met = self._evaluate_condition(change_usd, operator, threshold)

            # Edge detection
            if condition_met and not was_active:
                triggers.append({
                    "timestamp": check_time,
                    "value": round(change_usd, 2),
                    "threshold": threshold,
                    "operator": operator,
                })

            was_active = condition_met

        return triggers

    def _find_factor_triggers_in_range(
        self, db: Session, signal_def: Dict, symbol: str, time_window: str,
        kline_min_ts: int = None, kline_max_ts: int = None,
        exchange: str = "hyperliquid"
    ) -> List[Dict]:
        """
        Find factor signal triggers using K-line close timestamps.

        Factor values only change when a new K-line closes. We:
        1. Load historical K-lines for the backtest range
        2. Run expression engine once on the full series
        3. Iterate each K-line close timestamp with edge detection
        """
        from services.factor_resolver import compute_factor_series
        import pandas as pd

        condition = signal_def.get("trigger_condition", {})
        metric = condition.get("metric", "")
        operator = condition.get("operator")
        threshold = condition.get("threshold")
        factor_name = metric.split(":", 1)[1] if ":" in metric else metric

        if not all([operator, threshold is not None]):
            return []

        # Load K-lines for backtest range with 200-bar warm-up
        from services.factor_data_provider import get_klines_from_db
        interval_ms = TIMEFRAME_MS.get(time_window, 3600000)
        warmup_ms = interval_ms * 200
        load_start = (kline_min_ts or 0) - warmup_ms

        klines = get_klines_from_db(
            db, exchange, symbol, time_window,
            start_ts=load_start // 1000,
            end_ts=(kline_max_ts or int(datetime.utcnow().timestamp() * 1000)) // 1000,
        )

        if len(klines) < 30:
            logger.warning(f"[Backtest] Insufficient K-line data for factor {factor_name}: {len(klines)} bars")
            return []

        # Run factor computation once on full series
        series, _, err = compute_factor_series(
            db=db,
            factor_name=factor_name,
            symbol=symbol,
            period=time_window,
            exchange=exchange,
            klines=klines,
        )
        if series is None or len(series) == 0:
            logger.warning(f"[Backtest] Factor {factor_name} execution failed: {err}")
            return []

        logger.warning(f"[Backtest] Factor {factor_name}: computed {len(series)} values "
                       f"from {len(klines)} K-lines")

        # Iterate K-line close timestamps with edge detection
        triggers = []
        was_active = False
        backtest_start_s = (kline_min_ts or 0) // 1000

        for i, kline in enumerate(klines):
            ts = kline["timestamp"]
            # Only check within backtest range
            if ts < backtest_start_s:
                # Still update was_active for warm-up edge detection
                if i < len(series) and not pd.isna(series.iloc[i]):
                    val = float(series.iloc[i])
                    was_active = self._evaluate_condition(val, operator, threshold)
                continue

            if i >= len(series) or pd.isna(series.iloc[i]):
                continue

            value = float(series.iloc[i])
            condition_met = self._evaluate_condition(value, operator, threshold)

            # Edge detection: False -> True
            if condition_met and not was_active:
                triggers.append({
                    "timestamp": ts * 1000,  # Convert back to ms
                    "value": value,
                    "threshold": threshold,
                    "operator": operator,
                })

            was_active = condition_met

        logger.warning(f"[Backtest] Factor {factor_name}: found {len(triggers)} triggers")
        return triggers

    def _precompute_factor_for_pool(
        self, db: Session, signal_id: int, sig_def: Dict, symbol: str,
        kline_min_ts: int, kline_max_ts: int, exchange: str
    ) -> tuple:
        """Precompute factor condition at each K-line close for pool backtest.

        Returns:
            (kline_close_ms_list, conditions_dict)
            - kline_close_ms_list: sorted list of K-line close timestamps (ms)
            - conditions_dict: {ts_ms: (condition_met, value_info)}
              The condition persists until the next K-line close.
        """
        from services.factor_resolver import compute_factor_series
        from services.factor_data_provider import get_klines_from_db
        import pandas as pd

        condition = sig_def["trigger_condition"]
        metric = condition.get("metric", "")
        operator = condition.get("operator")
        threshold = condition.get("threshold")
        time_window = condition.get("time_window", "1h")
        factor_name = metric.split(":", 1)[1] if ":" in metric else metric

        if not all([operator, threshold is not None]):
            return ([], {})

        interval_ms = TIMEFRAME_MS.get(time_window, 3600000)
        warmup_ms = interval_ms * 200
        load_start = (kline_min_ts or 0) - warmup_ms

        klines = get_klines_from_db(
            db, exchange, symbol, time_window,
            start_ts=load_start // 1000,
            end_ts=(kline_max_ts or int(datetime.utcnow().timestamp() * 1000)) // 1000,
        )
        if len(klines) < 30:
            return ([], {})

        series, _, err = compute_factor_series(
            db=db,
            factor_name=factor_name,
            symbol=symbol,
            period=time_window,
            exchange=exchange,
            klines=klines,
        )
        if series is None or len(series) == 0:
            return ([], {})

        backtest_start_s = (kline_min_ts or 0) // 1000
        kline_close_ms_list = []
        conditions = {}

        for i, kline in enumerate(klines):
            ts_s = kline["timestamp"]
            if i >= len(series) or pd.isna(series.iloc[i]):
                continue
            value = float(series.iloc[i])
            condition_met = self._evaluate_condition(value, operator, threshold)
            ts_ms = ts_s * 1000
            if ts_s >= backtest_start_s:
                kline_close_ms_list.append(ts_ms)
            value_info = {
                "signal_id": signal_id,
                "signal_name": sig_def["signal_name"],
                "value": value,
                "threshold": threshold,
                "operator": operator,
            } if condition_met else None
            conditions[ts_ms] = (condition_met, value_info)

        return (kline_close_ms_list, conditions)
