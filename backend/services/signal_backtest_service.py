"""
Signal Backtest Service

Backtests signals against historical data to show where triggers would occur.
"""

import json
from typing import Dict, List, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

from services.signal_backtest_common import TIMEFRAME_MS, logger
from services.signal_backtest_factor_mixin import SignalBacktestFactorMixin
from services.signal_backtest_event_mixin import SignalBacktestEventMixin
from services.signal_backtest_bucket_mixin import SignalBacktestBucketMixin
from services.signal_backtest_pool_mixin import SignalBacktestPoolMixin
from services.signal_backtest_pool_and_mixin import SignalBacktestPoolAndMixin
from services.signal_backtest_pool_or_mixin import SignalBacktestPoolOrMixin
from services.signal_backtest_data_mixin import SignalBacktestDataMixin
from services.signal_backtest_precompute_mixin import SignalBacktestPrecomputeMixin


class SignalBacktestService(
    SignalBacktestFactorMixin,
    SignalBacktestEventMixin,
    SignalBacktestBucketMixin,
    SignalBacktestPoolMixin,
    SignalBacktestPoolAndMixin,
    SignalBacktestPoolOrMixin,
    SignalBacktestDataMixin,
    SignalBacktestPrecomputeMixin,
):
    """Service for backtesting signals against historical data."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def backtest_signal(
        self, db: Session, signal_id: int, symbol: str,
        kline_min_ts: int = None, kline_max_ts: int = None
    ) -> Dict[str, Any]:
        """
        Backtest a signal against historical data.
        Returns only trigger points - K-lines should be fetched separately via market API.

        Args:
            db: Database session
            signal_id: Signal definition ID
            symbol: Trading symbol (e.g., 'BTC')
            kline_min_ts: Minimum K-line timestamp in milliseconds (for filtering triggers)
            kline_max_ts: Maximum K-line timestamp in milliseconds (for filtering triggers)
        """
        logger.warning(f"[Backtest] START signal_id={signal_id} symbol={symbol} "
                       f"ts_range=[{kline_min_ts}, {kline_max_ts}]")

        # Clear bucket cache for fresh data
        self._bucket_cache = {}

        # Get signal definition
        result = db.execute(
            text("""
                SELECT id, signal_name, description, trigger_condition, enabled, exchange
                FROM signal_definitions WHERE id = :id AND (is_deleted IS NULL OR is_deleted = false)
            """),
            {"id": signal_id}
        )
        row = result.fetchone()
        if not row:
            logger.warning(f"[Backtest] Signal {signal_id} NOT FOUND in database")
            return {"error": "Signal not found"}

        exchange = row[5] if len(row) > 5 and row[5] else "hyperliquid"

        # Debug: log raw row data and types
        logger.warning(f"[Backtest] DB row: id={row[0]}, name={row[1]}, exchange={exchange}, "
                       f"trigger_condition type={type(row[3])}")

        # Handle trigger_condition - may be string (SQLite/some drivers) or dict (PostgreSQL JSONB)
        trigger_condition = row[3]
        if isinstance(trigger_condition, str):
            import json
            try:
                trigger_condition = json.loads(trigger_condition)
                logger.warning(f"[Backtest] Parsed trigger_condition from JSON string")
            except json.JSONDecodeError as e:
                logger.warning(f"[Backtest] Failed to parse trigger_condition: {e}")
                trigger_condition = {}

        signal_def = {
            "id": row[0],
            "signal_name": row[1],
            "description": row[2],
            "trigger_condition": trigger_condition if isinstance(trigger_condition, dict) else {},
            "enabled": row[4]
        }

        condition = signal_def.get("trigger_condition", {})
        metric = condition.get("metric") if isinstance(condition, dict) else None
        time_window = condition.get("time_window", "5m") if isinstance(condition, dict) else "5m"

        logger.warning(f"[Backtest] Signal found: name={signal_def['signal_name']}, "
                       f"metric={metric}, time_window={time_window}, condition={condition}")

        if not metric:
            logger.warning(f"[Backtest] Signal {signal_id} has no metric configured")
            return {"error": "Signal has no metric configured"}

        # Find triggers within the specified time range
        triggers = self._find_triggers_in_range(
            db, signal_def, symbol, time_window, kline_min_ts, kline_max_ts, exchange
        )

        logger.warning(f"[Backtest] END signal_id={signal_id} success, {len(triggers)} triggers found")
        return {
            "signal_id": signal_id,
            "signal_name": signal_def["signal_name"],
            "symbol": symbol,
            "time_window": time_window,
            "condition": condition,
            "trigger_count": len(triggers),
            "triggers": triggers,
        }

    def backtest_temp_signal(
        self, db: Session, symbol: str, trigger_condition: Dict,
        kline_min_ts: int = None, kline_max_ts: int = None,
        exchange: str = "hyperliquid"
    ) -> Dict[str, Any]:
        """
        Backtest a temporary signal configuration without saving to database.
        Used for AI signal creation preview.

        Args:
            db: Database session
            symbol: Trading symbol (e.g., 'BTC')
            trigger_condition: Signal trigger condition dict
            kline_min_ts: Minimum K-line timestamp in milliseconds
            kline_max_ts: Maximum K-line timestamp in milliseconds
            exchange: Exchange name (hyperliquid or binance)
        """
        # Clear bucket cache for fresh data
        self._bucket_cache = {}

        # Build temporary signal definition
        signal_def = {
            "id": None,
            "signal_name": "Temporary Preview",
            "description": "AI-generated signal preview",
            "trigger_condition": trigger_condition,
            "enabled": True
        }

        metric = trigger_condition.get("metric")
        time_window = trigger_condition.get("time_window", "5m")

        if not metric:
            return {"error": "Signal has no metric configured"}

        # Find triggers within the specified time range
        triggers = self._find_triggers_in_range(
            db, signal_def, symbol, time_window, kline_min_ts, kline_max_ts, exchange
        )

        return {
            "signal_id": None,
            "signal_name": "Temporary Preview",
            "symbol": symbol,
            "time_window": time_window,
            "condition": trigger_condition,
            "trigger_count": len(triggers),
            "triggers": triggers,
        }

    def _find_triggers_in_range(
        self, db: Session, signal_def: Dict, symbol: str, time_window: str,
        kline_min_ts: int = None, kline_max_ts: int = None,
        exchange: str = "hyperliquid"
    ) -> List[Dict]:
        """
        Find trigger points within a time range using 15-second sliding window detection.

        This simulates real-time detection behavior:
        - Check every 15 seconds (matching data collection granularity)
        - At each check point, calculate indicator using data available at that moment
        - Apply edge detection: only trigger on False -> True transitions

        Args:
            db: Database session
            signal_def: Signal definition dict
            symbol: Trading symbol
            time_window: Time window (e.g., '5m', '15m')
            kline_min_ts: Minimum timestamp in milliseconds (optional)
            kline_max_ts: Maximum timestamp in milliseconds (optional)
        """
        condition = signal_def.get("trigger_condition", {})
        metric = condition.get("metric")
        operator = condition.get("operator")
        threshold = condition.get("threshold")

        logger.warning(f"[Backtest] _find_triggers_in_range: symbol={symbol}, metric={metric}, "
                       f"operator={operator}, threshold={threshold}, time_window={time_window}, exchange={exchange}")

        # Handle taker_volume composite signal
        if metric == "taker_volume":
            logger.warning(f"[Backtest] Using taker_volume composite signal handler")
            return self._find_taker_triggers_in_range(
                db, signal_def, symbol, time_window, kline_min_ts, kline_max_ts, exchange
            )

        # Handle MACD event-based signal
        if metric == "macd":
            logger.warning(f"[Backtest] Using MACD event-based signal handler")
            return self._find_macd_triggers_in_range(
                db, signal_def, symbol, time_window, kline_min_ts, kline_max_ts, exchange
            )

        # Handle factor-based signal
        if metric and metric.startswith("factor:"):
            logger.warning(f"[Backtest] Using factor signal handler for {metric}")
            return self._find_factor_triggers_in_range(
                db, signal_def, symbol, time_window, kline_min_ts, kline_max_ts, exchange
            )

        # Handle oi USD change signal (special: calculates USD value change)
        if metric == "oi":
            logger.warning(f"[Backtest] Using oi USD change signal handler")
            return self._find_oi_change_triggers_in_range(
                db, signal_def, symbol, time_window, kline_min_ts, kline_max_ts, exchange
            )

        if not all([metric, operator, threshold is not None]):
            logger.warning(f"[Backtest] Missing required fields: metric={metric}, "
                           f"operator={operator}, threshold={threshold}")
            return []

        # Map metric names for backward compatibility
        metric_map = {
            "oi_delta_percent": "oi_delta",
            "funding_rate": "funding",
            "taker_buy_ratio": "taker_ratio",
        }
        mapped_metric = metric_map.get(metric, metric)
        if mapped_metric != metric:
            logger.warning(f"[Backtest] Metric mapped: {metric} -> {mapped_metric}")
        metric = mapped_metric

        interval_ms = TIMEFRAME_MS.get(time_window, 300000)
        check_interval_ms = 15000  # 15 seconds, matching data granularity

        # Load raw 15-second granularity data for the time range
        raw_data = self._load_raw_data_for_metric(
            db, symbol, metric, kline_min_ts, kline_max_ts, interval_ms, exchange
        )
        if not raw_data:
            logger.warning(f"[Backtest] NO DATA returned from _load_raw_data_for_metric "
                           f"for {symbol}/{metric}")
            return []
        logger.warning(f"[Backtest] Loaded {len(raw_data)} raw data points for {symbol}/{metric}")

        # Generate check points every 15 seconds
        check_points = self._generate_check_points(
            raw_data, kline_min_ts, kline_max_ts, check_interval_ms
        )

        # Simulate real-time detection with edge triggering
        triggers = []
        was_active = False

        # Build timestamps index for O(log n) binary search optimization
        timestamps_index = [r[0] for r in raw_data]

        for check_time in check_points:
            # Calculate indicator value at this check point (using only data up to check_time)
            value = self._calculate_indicator_at_time(
                raw_data, metric, check_time, interval_ms, timestamps_index
            )

            if value is None:
                continue

            # Check condition
            condition_met = self._evaluate_condition(value, operator, threshold)

            # Edge detection: only trigger on False -> True
            if condition_met and not was_active:
                triggers.append({
                    "timestamp": check_time,
                    "value": value,
                    "threshold": threshold,
                    "operator": operator,
                })

            was_active = condition_met

        return triggers



# Singleton instance
signal_backtest_service = SignalBacktestService()
