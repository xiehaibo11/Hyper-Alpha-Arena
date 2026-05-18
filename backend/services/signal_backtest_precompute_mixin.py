"""Sliding-window precomputation helpers for signal backtests."""

from typing import Dict, List, Optional


class SignalBacktestPrecomputeMixin:
    def _precompute_indicator_values(
        self, raw_data: List[tuple], metric: str, interval_ms: int, check_points: List[int]
    ) -> Dict[int, Optional[float]]:
        """
        Precompute indicator values for all check points using sliding window.

        This is a performance optimization that replaces per-checkpoint calculation
        with a single pass through the data. The algorithm maintains a sliding window
        and incrementally updates bucket aggregations.

        Args:
            raw_data: Raw data points sorted by timestamp
            metric: Metric type (cvd, oi_delta, order_imbalance, funding, etc.)
            interval_ms: Bucket interval in milliseconds
            check_points: List of timestamps to compute values for

        Returns:
            Dict mapping check_time -> indicator value (or None)
        """
        from services.market_flow_indicators import floor_timestamp

        if not raw_data or not check_points:
            return {}

        lookback_ms = interval_ms * 10
        results = {}
        sorted_checks = sorted(check_points)

        left_ptr = 0
        right_ptr = 0
        buckets = {}

        for check_time in sorted_checks:
            window_start = check_time - lookback_ms

            # Expand right pointer to include new data up to check_time
            while right_ptr < len(raw_data) and raw_data[right_ptr][0] <= check_time:
                row = raw_data[right_ptr]
                ts = row[0]
                bucket_ts = floor_timestamp(ts, interval_ms)

                self._add_to_bucket(buckets, bucket_ts, row, metric)
                right_ptr += 1

            # Contract left pointer to remove data outside window
            while left_ptr < len(raw_data) and raw_data[left_ptr][0] < window_start:
                row = raw_data[left_ptr]
                ts = row[0]
                bucket_ts = floor_timestamp(ts, interval_ms)

                self._remove_from_bucket(buckets, bucket_ts, row, metric)
                left_ptr += 1

            # Calculate result from current window
            results[check_time] = self._calc_from_buckets(buckets, metric)

        return results

    def _add_to_bucket(self, buckets: Dict, bucket_ts: int, row: tuple, metric: str):
        """Add a data point to bucket aggregation."""
        if metric == 'cvd':
            buy, sell = row[1], row[2]
            if bucket_ts not in buckets:
                buckets[bucket_ts] = {"buy": 0, "sell": 0, "count": 0}
            buckets[bucket_ts]["buy"] += float(buy or 0)
            buckets[bucket_ts]["sell"] += float(sell or 0)
            buckets[bucket_ts]["count"] += 1

        elif metric == 'order_imbalance' or metric == 'depth_ratio':
            bid, ask = row[1], row[2]
            if bucket_ts not in buckets:
                buckets[bucket_ts] = {"bid": 0, "ask": 0, "count": 0}
            # Take last value for orderbook data
            buckets[bucket_ts]["bid"] = float(bid or 0)
            buckets[bucket_ts]["ask"] = float(ask or 0)
            buckets[bucket_ts]["count"] += 1

        elif metric == 'funding':
            funding = row[1]
            if bucket_ts not in buckets:
                buckets[bucket_ts] = {"value": None, "count": 0}
            # Apply * 1000000 scaling like original
            buckets[bucket_ts]["value"] = float(funding) * 1000000 if funding is not None else None
            buckets[bucket_ts]["count"] += 1

        elif metric == 'oi_delta':
            oi = row[1]
            if bucket_ts not in buckets:
                buckets[bucket_ts] = {"value": None, "count": 0}
            buckets[bucket_ts]["value"] = float(oi) if oi else None
            buckets[bucket_ts]["count"] += 1

        elif metric == 'taker_ratio':
            buy, sell = row[1], row[2]
            if bucket_ts not in buckets:
                buckets[bucket_ts] = {"buy": 0, "sell": 0, "count": 0}
            buckets[bucket_ts]["buy"] += float(buy or 0)
            buckets[bucket_ts]["sell"] += float(sell or 0)
            buckets[bucket_ts]["count"] += 1

        elif metric in ('volatility', 'price_change'):
            # Data format: (timestamp, high_price, low_price)
            high, low = row[1], row[2]
            h = float(high) if high else None
            l = float(low) if low else None
            if h and l:
                if bucket_ts not in buckets:
                    buckets[bucket_ts] = {"high": h, "low": l, "count": 0}
                else:
                    # Track max high and min low for the bucket
                    if h > buckets[bucket_ts]["high"]:
                        buckets[bucket_ts]["high"] = h
                    if l < buckets[bucket_ts]["low"]:
                        buckets[bucket_ts]["low"] = l
                buckets[bucket_ts]["count"] += 1

    def _remove_from_bucket(self, buckets: Dict, bucket_ts: int, row: tuple, metric: str):
        """Remove a data point from bucket aggregation (for sliding window)."""
        if bucket_ts not in buckets:
            return

        if metric == 'cvd':
            buy, sell = row[1], row[2]
            buckets[bucket_ts]["buy"] -= float(buy or 0)
            buckets[bucket_ts]["sell"] -= float(sell or 0)
            buckets[bucket_ts]["count"] -= 1
            if buckets[bucket_ts]["count"] <= 0:
                del buckets[bucket_ts]

        elif metric in ('order_imbalance', 'depth_ratio', 'funding', 'oi_delta'):
            buckets[bucket_ts]["count"] -= 1
            if buckets[bucket_ts]["count"] <= 0:
                del buckets[bucket_ts]

        elif metric == 'taker_ratio':
            buy, sell = row[1], row[2]
            buckets[bucket_ts]["buy"] -= float(buy or 0)
            buckets[bucket_ts]["sell"] -= float(sell or 0)
            buckets[bucket_ts]["count"] -= 1
            if buckets[bucket_ts]["count"] <= 0:
                del buckets[bucket_ts]

        elif metric in ('volatility', 'price_change'):
            # For volatility, we just track count - high/low are recalculated
            buckets[bucket_ts]["count"] -= 1
            if buckets[bucket_ts]["count"] <= 0:
                del buckets[bucket_ts]

    def _calc_from_buckets(self, buckets: Dict, metric: str) -> Optional[float]:
        """Calculate indicator value from current bucket state."""
        import math

        # Filter to valid buckets only
        valid_buckets = {k: v for k, v in buckets.items() if v.get("count", 0) > 0}
        if not valid_buckets:
            return None

        sorted_times = sorted(valid_buckets.keys())

        if metric == 'cvd':
            last = valid_buckets[sorted_times[-1]]
            return last["buy"] - last["sell"]

        elif metric == 'order_imbalance':
            last = valid_buckets[sorted_times[-1]]
            total = last["bid"] + last["ask"]
            return (last["bid"] - last["ask"]) / total if total > 0 else None

        elif metric == 'depth_ratio':
            last = valid_buckets[sorted_times[-1]]
            return last["bid"] / last["ask"] if last["ask"] > 0 else None

        elif metric == 'funding':
            if len(sorted_times) < 2:
                return None
            prev_val = valid_buckets[sorted_times[-2]]["value"]
            curr_val = valid_buckets[sorted_times[-1]]["value"]
            if prev_val is not None and curr_val is not None:
                return curr_val - prev_val
            return None

        elif metric == 'oi_delta':
            if len(sorted_times) < 2:
                return None
            prev_val = valid_buckets[sorted_times[-2]]["value"]
            curr_val = valid_buckets[sorted_times[-1]]["value"]
            if prev_val is not None and curr_val is not None and prev_val != 0:
                return ((curr_val - prev_val) / prev_val) * 100
            return None

        elif metric == 'taker_ratio':
            last = valid_buckets[sorted_times[-1]]
            if last["sell"] > 0:
                return last["buy"] / last["sell"]
            return 1.0

        elif metric == 'volatility':
            last = valid_buckets[sorted_times[-1]]
            if last.get("low", 0) > 0:
                return ((last["high"] - last["low"]) / last["low"]) * 100
            return None

        elif metric == 'price_change':
            if len(sorted_times) < 2:
                return None
            prev = valid_buckets[sorted_times[-2]]
            curr = valid_buckets[sorted_times[-1]]
            # Use midpoint of high/low as price proxy
            prev_price = (prev["high"] + prev["low"]) / 2
            curr_price = (curr["high"] + curr["low"]) / 2
            if prev_price > 0:
                return ((curr_price - prev_price) / prev_price) * 100
            return None

        return None

    def _precompute_taker_data(
        self, raw_data: List[tuple], interval_ms: int, check_points: List[int]
    ) -> Dict[int, Optional[Dict]]:
        """
        Precompute taker data (log_ratio, ratio, volume) for all check points.
        Uses sliding window optimization for performance.
        """
        import math
        from services.market_flow_indicators import floor_timestamp

        if not raw_data or not check_points:
            return {}

        lookback_ms = interval_ms * 10
        results = {}
        sorted_checks = sorted(check_points)

        left_ptr = 0
        right_ptr = 0
        buckets = {}

        for check_time in sorted_checks:
            window_start = check_time - lookback_ms

            # Expand right pointer
            while right_ptr < len(raw_data) and raw_data[right_ptr][0] <= check_time:
                ts, buy, sell = raw_data[right_ptr]
                bucket_ts = floor_timestamp(ts, interval_ms)
                if bucket_ts not in buckets:
                    buckets[bucket_ts] = {"buy": 0, "sell": 0, "count": 0}
                buckets[bucket_ts]["buy"] += float(buy or 0)
                buckets[bucket_ts]["sell"] += float(sell or 0)
                buckets[bucket_ts]["count"] += 1
                right_ptr += 1

            # Contract left pointer
            while left_ptr < len(raw_data) and raw_data[left_ptr][0] < window_start:
                ts, buy, sell = raw_data[left_ptr]
                bucket_ts = floor_timestamp(ts, interval_ms)
                if bucket_ts in buckets:
                    buckets[bucket_ts]["buy"] -= float(buy or 0)
                    buckets[bucket_ts]["sell"] -= float(sell or 0)
                    buckets[bucket_ts]["count"] -= 1
                    if buckets[bucket_ts]["count"] <= 0:
                        del buckets[bucket_ts]
                left_ptr += 1

            # Calculate taker data from current window
            valid_buckets = {k: v for k, v in buckets.items() if v.get("count", 0) > 0}
            if not valid_buckets:
                results[check_time] = None
                continue

            sorted_times = sorted(valid_buckets.keys())
            last = valid_buckets[sorted_times[-1]]
            buy_vol, sell_vol = last["buy"], last["sell"]
            total = buy_vol + sell_vol

            if buy_vol > 0 and sell_vol > 0 and total > 0:
                results[check_time] = {
                    "log_ratio": math.log(buy_vol / sell_vol),
                    "ratio": buy_vol / sell_vol,
                    "volume": total
                }
            else:
                results[check_time] = None

        return results

    def _evaluate_condition(self, value: float, operator: str, threshold: float) -> bool:
        """Evaluate if a condition is met."""
        # Support both symbol and text forms of operators
        if operator in (">", "greater_than", "gt"):
            return value > threshold
        elif operator in (">=", "greater_than_or_equal", "gte"):
            return value >= threshold
        elif operator in ("<", "less_than", "lt"):
            return value < threshold
        elif operator in ("<=", "less_than_or_equal", "lte"):
            return value <= threshold
        elif operator in ("==", "equal", "eq"):
            return abs(value - threshold) < 1e-9
        elif operator in ("!=", "not_equal", "ne"):
            return abs(value - threshold) >= 1e-9
        elif operator in ("abs_greater_than", "abs_gt"):
            return abs(value) > threshold
        elif operator in ("abs_less_than", "abs_lt"):
            return abs(value) < threshold
        return False
