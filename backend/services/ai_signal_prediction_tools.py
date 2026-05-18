"""Signal combination prediction tools for AI signal generation."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from services.signal_backtest_service import TIMEFRAME_MS, signal_backtest_service

def _combine_signals_with_pool_edge_detection(
    db: Session, symbol: str, signals: List[Dict],
    preloaded_data: Dict[str, List] = None,
    preloaded_indexes: Dict[str, List[int]] = None
) -> set:
    """
    Combine signals using pool-level edge detection (same as real-time detection).
    Evaluates all signals at each check point and triggers only on False->True transition.

    Performance optimization: accepts preloaded_data and preloaded_indexes to avoid
    redundant database queries and enable O(log n) binary search.
    """
    if not signals:
        return set()

    # Get time window from first signal
    time_window = signals[0].get("time_window", "5m")
    timeframe_ms = {
        "1m": 60000, "3m": 180000, "5m": 300000,
        "15m": 900000, "30m": 1800000, "1h": 3600000
    }
    interval_ms = timeframe_ms.get(time_window, 300000)

    import math
    metric_map = {"oi_delta_percent": "oi_delta", "taker_buy_ratio": "taker_ratio"}

    # Use preloaded data if available, otherwise load from database
    if preloaded_data is not None:
        metrics_data = preloaded_data
        metrics_indexes = preloaded_indexes or {}
    else:
        # Fallback: load raw data for all metrics (backward compatibility)
        metrics_data = {}
        metrics_indexes = {}
        for sig in signals:
            metric = sig.get("indicator")
            if metric:
                # taker_volume uses taker_ratio data
                if metric == "taker_volume":
                    mapped_metric = "taker_ratio"
                else:
                    mapped_metric = metric_map.get(metric, metric)
                if mapped_metric not in metrics_data:
                    raw_data = signal_backtest_service._load_raw_data_for_metric(
                        db, symbol, mapped_metric, None, None, interval_ms
                    )
                    metrics_data[mapped_metric] = raw_data
                    metrics_indexes[mapped_metric] = [r[0] for r in raw_data] if raw_data else []

    # Generate check points from all data timestamps
    all_timestamps = set()
    for data in metrics_data.values():
        if data:
            all_timestamps.update(r[0] for r in data)

    check_points = sorted(all_timestamps)
    if not check_points:
        return set()

    # Evaluate all signals at each check point with pool-level edge detection
    triggers = set()
    was_active = False

    for check_time in check_points:
        all_met = True

        for sig in signals:
            metric = sig.get("indicator")

            # Handle taker_volume composite signal
            if metric == "taker_volume":
                direction = sig.get("direction", "any")
                ratio_threshold = sig.get("ratio_threshold", 1.5)
                volume_threshold = sig.get("volume_threshold", 0)
                log_threshold = math.log(max(ratio_threshold, 1.01))

                raw_data = metrics_data.get("taker_ratio", [])

                # Use _calc_taker_data_at_time to get both log_ratio and volume
                taker_data = signal_backtest_service._calc_taker_data_at_time(
                    raw_data, check_time, interval_ms
                )

                if taker_data is None:
                    all_met = False
                    break

                log_ratio = taker_data["log_ratio"]
                total_volume = taker_data["volume"]

                # Check ratio condition
                if direction == "buy":
                    ratio_met = log_ratio >= log_threshold
                elif direction == "sell":
                    ratio_met = log_ratio <= -log_threshold
                else:  # any
                    ratio_met = abs(log_ratio) >= log_threshold

                # Check volume condition
                volume_met = total_volume >= volume_threshold

                if not (ratio_met and volume_met):
                    all_met = False
                    break
            else:
                # Standard indicator
                operator = sig.get("operator")
                threshold = sig.get("threshold")

                mapped_metric = metric_map.get(metric, metric)
                raw_data = metrics_data.get(mapped_metric, [])
                ts_index = metrics_indexes.get(mapped_metric)

                value = signal_backtest_service._calculate_indicator_at_time(
                    raw_data, mapped_metric, check_time, interval_ms, ts_index
                )

                if value is None:
                    all_met = False
                    break

                if not signal_backtest_service._evaluate_condition(value, operator, threshold):
                    all_met = False
                    break

        # Pool-level edge detection: only trigger on False -> True
        if all_met and not was_active:
            triggers.add(check_time)

        was_active = all_met

    return triggers


def _tool_predict_signal_combination(
    db: Session, symbol: str, signals: List[Dict], logic: str,
    exchange: str = "hyperliquid"
) -> Dict[str, Any]:
    """
    Predict trigger count when combining multiple signals.

    Performance optimizations:
    1. Preload all required metric data once (avoid redundant DB queries)
    2. Build timestamp indexes for O(log n) binary search
    3. Reuse preloaded data for both individual and combined analysis
    """
    # Limit to 5 signals
    signals = signals[:5]
    if not signals:
        return {"error": "No signals provided"}

    # Get time window from first signal (assume all signals use same time window)
    time_window = signals[0].get("time_window", "5m")
    timeframe_ms = {
        "1m": 60000, "3m": 180000, "5m": 300000,
        "15m": 900000, "30m": 1800000, "1h": 3600000
    }
    interval_ms = timeframe_ms.get(time_window, 300000)

    metric_map = {"oi_delta_percent": "oi_delta", "taker_buy_ratio": "taker_ratio"}

    # Step 1: Preload all required metric data ONCE
    preloaded_data = {}
    preloaded_indexes = {}
    required_metrics = set()

    for sig in signals:
        metric = sig.get("indicator")
        if metric:
            # Factor and taker_volume handled separately
            if metric.startswith("factor:") or metric == "taker_volume":
                if metric == "taker_volume":
                    required_metrics.add("taker_ratio")
            else:
                mapped_metric = metric_map.get(metric, metric)
                required_metrics.add(mapped_metric)

    # Calculate 7-day time range (matching backtest behavior)
    current_time_ms = int(datetime.utcnow().timestamp() * 1000)
    start_time_ms = current_time_ms - (7 * 24 * 60 * 60 * 1000)  # 7 days ago

    for mapped_metric in required_metrics:
        raw_data = signal_backtest_service._load_raw_data_for_metric(
            db, symbol.upper(), mapped_metric, start_time_ms, current_time_ms, interval_ms, exchange
        )
        preloaded_data[mapped_metric] = raw_data
        # Build timestamp index for binary search (data is already sorted by timestamp)
        preloaded_indexes[mapped_metric] = [r[0] for r in raw_data] if raw_data else []

    # Step 2: Calculate individual signal triggers using preloaded data
    signal_triggers = {}
    individual_counts = {}
    individual_samples = {}

    for i, sig in enumerate(signals):
        metric = sig.get("indicator")

        # Handle factor signal
        if metric and metric.startswith("factor:"):
            factor_triggers = _find_factor_signal_triggers(
                db, symbol.upper(), sig, start_time_ms, current_time_ms, exchange
            )
            if isinstance(factor_triggers, dict) and "error" in factor_triggers:
                return factor_triggers
            triggers = factor_triggers
        # Handle taker_volume composite signal separately
        elif metric == "taker_volume":
            direction = sig.get("direction", "any")
            ratio_threshold = sig.get("ratio_threshold", 1.5)
            volume_threshold = sig.get("volume_threshold", 0)

            raw_data = preloaded_data.get("taker_ratio", [])
            ts_index = preloaded_indexes.get("taker_ratio", [])

            if not raw_data:
                return {"error": f"No data found for taker_volume"}

            triggers = _find_taker_volume_triggers(
                raw_data, ts_index, direction, ratio_threshold, volume_threshold, interval_ms
            )
        else:
            # Standard indicator
            operator = sig.get("operator")
            threshold = sig.get("threshold")

            if not all([metric, operator, threshold is not None]):
                return {"error": f"Signal {i+1} has incomplete configuration"}

            mapped_metric = metric_map.get(metric, metric)
            raw_data = preloaded_data.get(mapped_metric, [])
            ts_index = preloaded_indexes.get(mapped_metric, [])

            if not raw_data:
                return {"error": f"No data found for metric {metric}"}

            # Find triggers using preloaded data with binary search
            triggers = _find_triggers_with_preloaded_data(
                raw_data, ts_index, mapped_metric, operator, threshold, interval_ms
            )

        signal_triggers[i] = set(triggers)
        individual_counts[i] = len(triggers)
        individual_samples[i] = sorted(triggers)[:5]

    # Step 3: Combine based on logic (reuse preloaded data)
    if logic == "AND":
        combined_ts = _combine_signals_with_pool_edge_detection(
            db, symbol.upper(), signals, preloaded_data, preloaded_indexes
        )
    else:  # OR
        combined_ts = set.union(*signal_triggers.values()) if signal_triggers else set()

    combined_count = len(combined_ts)
    combined_samples = sorted(list(combined_ts))[:10]

    # Build response
    response = {
        "symbol": symbol.upper(),
        "exchange": exchange,
        "logic": logic,
        "signal_count": len(signals),
        "individual_triggers": individual_counts,
        "individual_sample_timestamps": individual_samples,
        "combined_triggers": combined_count,
        "combined_sample_timestamps": combined_samples,
        "assessment": (
            "too_many" if combined_count > 50 else
            "too_few" if combined_count < 3 else
            "reasonable"
        )
    }

    if logic == "AND" and combined_count < 3:
        response["recommendation"] = "AND logic too strict. Consider relaxing thresholds or using OR logic."
    elif logic == "OR" and combined_count > 50:
        response["recommendation"] = "OR logic too loose. Consider tightening thresholds or using AND logic."

    return response


def _find_factor_signal_triggers(
    db: Session, symbol: str, sig: Dict,
    start_time_ms: int, current_time_ms: int, exchange: str
) -> List[int]:
    """Find factor signal trigger timestamps using K-line data and edge detection."""
    import pandas as pd
    from sqlalchemy import text
    from services.factor_resolver import compute_factor_series

    metric = sig.get("indicator", "")
    factor_name = metric.split(":", 1)[1] if ":" in metric else metric
    operator = sig.get("operator")
    threshold = sig.get("threshold")
    tw = sig.get("time_window", "1h")

    if not all([operator, threshold is not None]):
        return {"error": f"Factor signal missing operator/threshold"}

    # Load K-lines for time range + warm-up
    from services.factor_data_provider import get_klines_from_db
    interval_ms = TIMEFRAME_MS.get(tw, 3600000)
    warmup_ms = interval_ms * 200
    load_start_s = (start_time_ms - warmup_ms) // 1000
    end_s = current_time_ms // 1000

    klines = get_klines_from_db(db, exchange, symbol, tw, start_ts=load_start_s, end_ts=end_s)

    if len(klines) < 30:
        return {"error": f"Insufficient K-line data for factor {factor_name}"}

    series, _, err = compute_factor_series(
        db=db,
        factor_name=factor_name,
        symbol=symbol,
        period=tw,
        exchange=exchange,
        klines=klines,
    )
    if series is None or len(series) == 0:
        return {"error": err or f"Factor {factor_name} computation failed"}

    # Iterate with edge detection
    triggers = []
    was_active = False
    backtest_start_s = start_time_ms // 1000

    for idx, kline in enumerate(klines):
        ts = kline["timestamp"]
        if idx >= len(series) or pd.isna(series.iloc[idx]):
            continue
        value = float(series.iloc[idx])
        condition_met = signal_backtest_service._evaluate_condition(value, operator, threshold)
        if ts < backtest_start_s:
            was_active = condition_met
            continue
        if condition_met and not was_active:
            triggers.append(ts * 1000)
        was_active = condition_met

    return triggers


def _find_triggers_with_preloaded_data(
    raw_data: List, ts_index: List[int], metric: str,
    operator: str, threshold: float, interval_ms: int
) -> List[int]:
    """
    Find trigger timestamps using preloaded data with binary search optimization.
    Implements edge detection: only triggers on False -> True transitions.
    """
    if not raw_data:
        return []

    # Generate check points from data timestamps
    check_points = sorted(set(ts_index))
    if not check_points:
        return []

    triggers = []
    was_active = False

    for check_time in check_points:
        value = signal_backtest_service._calculate_indicator_at_time(
            raw_data, metric, check_time, interval_ms, ts_index
        )

        if value is None:
            was_active = False
            continue

        condition_met = signal_backtest_service._evaluate_condition(value, operator, threshold)

        # Edge detection: only trigger on False -> True
        if condition_met and not was_active:
            triggers.append(check_time)

        was_active = condition_met

    return triggers


def _find_taker_volume_triggers(
    raw_data: List, ts_index: List[int], direction: str,
    ratio_threshold: float, volume_threshold: float, interval_ms: int
) -> List[int]:
    """
    Find taker_volume trigger timestamps using log ratio AND volume threshold.
    Uses edge detection: only triggers on False -> True transitions.

    Both conditions must be met:
    1. Ratio condition: |log(buy/sell)| >= log(ratio_threshold) for direction
    2. Volume condition: total_volume (buy + sell) >= volume_threshold
    """
    import math

    if not raw_data:
        return []

    check_points = sorted(set(ts_index))
    if not check_points:
        return []

    # Convert ratio_threshold to log threshold
    log_threshold = math.log(max(ratio_threshold, 1.01))

    triggers = []
    was_active = False

    for check_time in check_points:
        # Get taker data including volume at this time point
        taker_data = signal_backtest_service._calc_taker_data_at_time(
            raw_data, check_time, interval_ms
        )

        if taker_data is None:
            was_active = False
            continue

        log_ratio = taker_data["log_ratio"]
        total_volume = taker_data["volume"]

        # Check BOTH ratio and volume conditions
        ratio_met = False
        if direction == "buy":
            ratio_met = log_ratio >= log_threshold
        elif direction == "sell":
            ratio_met = log_ratio <= -log_threshold
        elif direction == "any":
            ratio_met = abs(log_ratio) >= log_threshold

        volume_met = total_volume >= volume_threshold
        condition_met = ratio_met and volume_met

        # Edge detection: only trigger on False -> True
        if condition_met and not was_active:
            triggers.append(check_time)

        was_active = condition_met

    return triggers
