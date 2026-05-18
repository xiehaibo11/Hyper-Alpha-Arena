"""Event-style and legacy trigger helpers for signal backtests."""

from typing import Dict, List
from sqlalchemy.orm import Session

from services.signal_backtest_common import TIMEFRAME_MS, logger


class SignalBacktestEventMixin:
    def _find_taker_triggers_in_range(
        self, db: Session, signal_def: Dict, symbol: str, time_window: str,
        kline_min_ts: int = None, kline_max_ts: int = None,
        exchange: str = "hyperliquid"
    ) -> List[Dict]:
        """
        Find taker_volume composite signal triggers using 15-second sliding window.
        Simulates real-time detection with edge triggering.
        """
        condition = signal_def.get("trigger_condition", {})
        direction = condition.get("direction", "any")
        ratio_threshold = condition.get("ratio_threshold", 1.5)
        volume_threshold = condition.get("volume_threshold", 0)

        interval_ms = TIMEFRAME_MS.get(time_window, 300000)

        # Load raw 15-second granularity data
        raw_data = self._load_raw_data_for_metric(
            db, symbol, "taker_ratio", kline_min_ts, kline_max_ts, interval_ms, exchange
        )
        if not raw_data:
            return []

        # Generate check points every 15 seconds
        check_points = self._generate_check_points(raw_data, kline_min_ts, kline_max_ts, 15000)

        # Simulate real-time detection with edge triggering
        triggers = []
        was_active = False

        import math
        # Convert user's ratio threshold to log threshold
        log_threshold = math.log(max(ratio_threshold, 1.01))

        # Build timestamps index for O(log n) binary search optimization
        timestamps_index = [r[0] for r in raw_data]

        for check_time in check_points:
            # Calculate taker data at this check point
            taker_data = self._calc_taker_data_at_time(raw_data, check_time, interval_ms, timestamps_index)
            if not taker_data:
                continue

            log_ratio = taker_data["log_ratio"]
            ratio = taker_data["ratio"]  # Original ratio for display
            total = taker_data["volume"]

            if total < volume_threshold:
                was_active = False
                continue

            # Check condition using log ratio (symmetric around 0)
            condition_met = False
            actual_dir = None

            if direction == "buy" and log_ratio >= log_threshold:
                condition_met, actual_dir = True, "buy"
            elif direction == "sell" and log_ratio <= -log_threshold:
                condition_met, actual_dir = True, "sell"
            elif direction == "any":
                if log_ratio >= log_threshold:
                    condition_met, actual_dir = True, "buy"
                elif log_ratio <= -log_threshold:
                    condition_met, actual_dir = True, "sell"

            # Edge detection: only trigger on False -> True
            if condition_met and not was_active:
                triggers.append({
                    "timestamp": check_time,
                    "direction": actual_dir,
                    "log_ratio": log_ratio,
                    "ratio": ratio,  # Original ratio for display
                    "ratio_threshold": ratio_threshold,
                    "volume": total,
                    "volume_threshold": volume_threshold,
                })

            was_active = condition_met

        return triggers

    def _find_macd_triggers_in_range(
        self, db: Session, signal_def: Dict, symbol: str, time_window: str,
        kline_min_ts: int = None, kline_max_ts: int = None,
        exchange: str = "hyperliquid"
    ) -> List[Dict]:
        """
        Find MACD event-based signal triggers.
        Checks for golden cross, death cross, and other MACD events.
        """
        import pandas as pd
        import pandas_ta as ta
        from database.models import CryptoKline
        from sqlalchemy import desc

        condition = signal_def.get("trigger_condition", {})
        event_types = condition.get("event_types", [])

        if not event_types:
            logger.warning(f"[Backtest] MACD signal has no event_types configured")
            return []

        interval_ms = TIMEFRAME_MS.get(time_window, 3600000)  # Default 1h for MACD
        interval_sec = interval_ms // 1000

        # Convert milliseconds to seconds (CryptoKline.timestamp is in seconds)
        kline_min_ts_sec = kline_min_ts // 1000 if kline_min_ts else None
        kline_max_ts_sec = kline_max_ts // 1000 if kline_max_ts else None

        # Load K-line data for MACD calculation
        query = db.query(CryptoKline).filter(
            CryptoKline.symbol == symbol,
            CryptoKline.period == time_window,
            CryptoKline.exchange == exchange
        )

        if kline_min_ts_sec:
            # Need extra data before min_ts for MACD calculation (at least 35 candles)
            lookback_sec = interval_sec * 50
            query = query.filter(CryptoKline.timestamp >= kline_min_ts_sec - lookback_sec)
        if kline_max_ts_sec:
            query = query.filter(CryptoKline.timestamp <= kline_max_ts_sec)

        rows = query.order_by(CryptoKline.timestamp.asc()).all()

        if not rows or len(rows) < 35:
            logger.warning(f"[Backtest] Insufficient K-line data for MACD: {len(rows) if rows else 0}")
            return []

        # Convert to DataFrame
        kline_data = [{
            'timestamp': int(row.timestamp),
            'close': float(row.close_price) if row.close_price else 0.0,
        } for row in rows]

        df = pd.DataFrame(kline_data)
        df['close'] = pd.to_numeric(df['close'], errors='coerce')

        # Calculate MACD
        macd_result = ta.macd(df['close'])
        if macd_result is None or macd_result.empty:
            return []

        df['macd'] = macd_result['MACD_12_26_9'].fillna(0)
        df['signal'] = macd_result['MACDs_12_26_9'].fillna(0)
        df['histogram'] = macd_result['MACDh_12_26_9'].fillna(0)

        # Find triggers with edge detection
        triggers = []

        for i in range(1, len(df)):
            ts_sec = df.iloc[i]['timestamp']  # timestamp in seconds

            # Skip if outside requested range (compare in seconds)
            if kline_min_ts_sec and ts_sec < kline_min_ts_sec:
                continue
            if kline_max_ts_sec and ts_sec > kline_max_ts_sec:
                continue

            curr_hist = df.iloc[i]['histogram']
            prev_hist = df.iloc[i-1]['histogram']
            curr_macd = df.iloc[i]['macd']
            prev_macd = df.iloc[i-1]['macd']

            triggered_event = None

            for event_type in event_types:
                if event_type == "golden_cross" or event_type == "histogram_positive":
                    if prev_hist <= 0 and curr_hist > 0:
                        triggered_event = event_type
                        break
                elif event_type == "death_cross" or event_type == "histogram_negative":
                    if prev_hist >= 0 and curr_hist < 0:
                        triggered_event = event_type
                        break
                elif event_type == "macd_above_zero":
                    if prev_macd <= 0 and curr_macd > 0:
                        triggered_event = event_type
                        break
                elif event_type == "macd_below_zero":
                    if prev_macd >= 0 and curr_macd < 0:
                        triggered_event = event_type
                        break

            if triggered_event:
                triggers.append({
                    "timestamp": ts_sec * 1000,  # Convert back to milliseconds for frontend
                    "triggered_event": triggered_event,
                    "event_types": event_types,
                    "values": {
                        "macd": float(df.iloc[i]['macd']),
                        "signal": float(df.iloc[i]['signal']),
                        "histogram": float(curr_hist),
                        "prev_histogram": float(prev_hist),
                    },
                    "cross_strength": abs(curr_hist - prev_hist),
                })

        logger.warning(f"[Backtest] MACD found {len(triggers)} triggers for {symbol}/{time_window}")
        return triggers

    # Legacy method - kept for backward compatibility but no longer used

    def _find_triggers(
        self, db: Session, signal_def: Dict, symbol: str, klines: List[Dict], time_window: str
    ) -> List[Dict]:
        """
        Find trigger points in historical data.

        IMPORTANT: This method iterates over MARKET FLOW DATA (buckets), not K-lines.
        K-lines are only used as a visual background - the actual trigger detection
        is based on market flow indicator values from the database.

        The trigger timestamp is the bucket timestamp, and we find the closest
        K-line to display the price context.
        """
        condition = signal_def.get("trigger_condition", {})
        metric = condition.get("metric")
        operator = condition.get("operator")
        threshold = condition.get("threshold")

        if not all([metric, operator, threshold is not None]):
            # Handle taker_volume composite signal
            if metric == "taker_volume":
                return self._find_taker_triggers(db, signal_def, symbol, klines, time_window)
            return []

        # Map metric names for backward compatibility
        metric_map = {
            "oi_delta_percent": "oi_delta",
            "funding_rate": "funding",
            "taker_buy_ratio": "taker_ratio",
        }
        metric = metric_map.get(metric, metric)

        interval_ms = TIMEFRAME_MS.get(time_window, 300000)

        # Get ALL bucket values from market flow data (this is the PRIMARY data source)
        cache_key = f"{symbol}_{metric}_{interval_ms}"
        if cache_key not in self._bucket_cache:
            self._bucket_cache[cache_key] = self._compute_all_bucket_values(
                db, symbol, metric, interval_ms
            )
        bucket_values = self._bucket_cache[cache_key]

        if not bucket_values:
            return []

        # Build a lookup for K-line prices (for display only)
        from services.market_flow_indicators import floor_timestamp
        kline_prices = {}
        for kline in klines:
            bucket_ts = floor_timestamp(kline["timestamp"], interval_ms)
            kline_prices[bucket_ts] = kline["close"]

        # Get K-line time range for filtering triggers to display
        if klines:
            kline_min_ts = min(floor_timestamp(k["timestamp"], interval_ms) for k in klines)
            kline_max_ts = max(floor_timestamp(k["timestamp"], interval_ms) for k in klines)
        else:
            return []

        # Iterate over ALL buckets and find triggers
        triggers = []
        for bucket_ts, value in sorted(bucket_values.items()):
            # Only include triggers within K-line display range
            if bucket_ts < kline_min_ts or bucket_ts > kline_max_ts:
                continue

            if value is not None and self._evaluate_condition(value, operator, threshold):
                # Get price from K-line (for display context)
                price = kline_prices.get(bucket_ts, 0)
                triggers.append({
                    "timestamp": bucket_ts,
                    "value": value,
                    "threshold": threshold,
                    "operator": operator,
                    "price": price,
                })

        return triggers

    def _find_taker_triggers(
        self, db: Session, signal_def: Dict, symbol: str, klines: List[Dict], time_window: str
    ) -> List[Dict]:
        """
        Find taker_volume composite signal triggers.

        IMPORTANT: This method iterates over MARKET FLOW DATA (buckets), not K-lines.
        K-lines are only used as a visual background.
        Uses log(buy/sell) for symmetric ratio detection.
        """
        import math
        condition = signal_def.get("trigger_condition", {})
        direction = condition.get("direction", "any")
        ratio_threshold = condition.get("ratio_threshold", 1.5)
        volume_threshold = condition.get("volume_threshold", 0)

        # Convert user's ratio threshold to log threshold
        log_threshold = math.log(max(ratio_threshold, 1.01))

        interval_ms = TIMEFRAME_MS.get(time_window, 300000)

        # Compute all taker volume buckets from market flow data
        taker_buckets = self._compute_taker_volume_buckets(db, symbol, interval_ms)
        if not taker_buckets:
            return []

        # Build K-line price lookup
        from services.market_flow_indicators import floor_timestamp
        kline_prices = {}
        for kline in klines:
            bucket_ts = floor_timestamp(kline["timestamp"], interval_ms)
            kline_prices[bucket_ts] = kline["close"]

        # Get K-line time range
        if not klines:
            return []
        kline_min_ts = min(floor_timestamp(k["timestamp"], interval_ms) for k in klines)
        kline_max_ts = max(floor_timestamp(k["timestamp"], interval_ms) for k in klines)

        # Iterate over all buckets and find triggers
        triggers = []
        for bucket_ts, data in sorted(taker_buckets.items()):
            # Only include triggers within K-line display range
            if bucket_ts < kline_min_ts or bucket_ts > kline_max_ts:
                continue

            log_ratio = data["log_ratio"]
            ratio = data["ratio"]  # Original ratio for display
            total = data["volume"]

            if total < volume_threshold:
                continue

            triggered = False
            actual_dir = None

            if direction == "buy" and log_ratio >= log_threshold:
                triggered, actual_dir = True, "buy"
            elif direction == "sell" and log_ratio <= -log_threshold:
                triggered, actual_dir = True, "sell"
            elif direction == "any":
                if log_ratio >= log_threshold:
                    triggered, actual_dir = True, "buy"
                elif log_ratio <= -log_threshold:
                    triggered, actual_dir = True, "sell"

            if triggered:
                triggers.append({
                    "timestamp": bucket_ts,
                    "direction": actual_dir,
                    "log_ratio": log_ratio,
                    "ratio": ratio,  # Original ratio for display
                    "ratio_threshold": ratio_threshold,
                    "volume": total,
                    "volume_threshold": volume_threshold,
                    "price": kline_prices.get(bucket_ts, 0),
                })

        return triggers

    def _compute_taker_volume_buckets(
        self, db, symbol, interval_ms
    ) -> Dict[int, Dict]:
        """Compute taker volume data (log_ratio and volume) for each bucket.

        Uses ln(buy/sell) for symmetric ratio around 0.
        """
        import math
        from services.market_flow_indicators import floor_timestamp
        from database.models import MarketTradesAggregated
        from datetime import datetime

        current_time_ms = int(datetime.utcnow().timestamp() * 1000)
        start_time_ms = current_time_ms - (7 * 24 * 60 * 60 * 1000)

        records = db.query(
            MarketTradesAggregated.timestamp,
            MarketTradesAggregated.taker_buy_notional,
            MarketTradesAggregated.taker_sell_notional
        ).filter(
            MarketTradesAggregated.symbol == symbol.upper(),
            MarketTradesAggregated.timestamp >= start_time_ms,
            MarketTradesAggregated.timestamp <= current_time_ms
        ).order_by(MarketTradesAggregated.timestamp).all()

        if not records:
            return {}

        buckets = {}
        for ts, buy, sell in records:
            bucket_ts = floor_timestamp(ts, interval_ms)
            if bucket_ts not in buckets:
                buckets[bucket_ts] = {"buy": 0, "sell": 0}
            buckets[bucket_ts]["buy"] += float(buy or 0)
            buckets[bucket_ts]["sell"] += float(sell or 0)

        # Calculate log ratio and volume for each bucket
        result = {}
        for ts, data in buckets.items():
            buy, sell = data["buy"], data["sell"]
            total = buy + sell
            if buy > 0 and sell > 0 and total > 0:
                result[ts] = {
                    "log_ratio": math.log(buy / sell),
                    "ratio": buy / sell,  # Original ratio for display
                    "volume": total
                }

        return result
