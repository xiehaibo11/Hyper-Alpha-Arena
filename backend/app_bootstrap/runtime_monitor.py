"""Warning-only runtime monitoring for thread and AI queue growth."""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

THREAD_WARNING_THRESHOLDS = (200, 400, 800, 1200)
AI_QUEUE_WARNING_THRESHOLDS = (8, 16, 32)
RUNTIME_MONITOR_INTERVAL_SECONDS = int(os.getenv("RUNTIME_MONITOR_INTERVAL_SECONDS", "300"))

_runtime_monitor_thread: threading.Thread | None = None
_runtime_monitor_running = False


def _get_current_thread_count() -> int:
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("Threads:"):
                    return int(line.split()[1])
    except Exception:
        return -1
    return -1


def _threshold_level(value: int, thresholds: tuple[int, ...]) -> int:
    level = 0
    for idx, threshold in enumerate(thresholds, start=1):
        if value >= threshold:
            level = idx
        else:
            break
    return level


def start_runtime_monitor() -> None:
    """Start background threshold logging; never mutates runtime behavior."""
    global _runtime_monitor_thread, _runtime_monitor_running

    if _runtime_monitor_running:
        return

    def monitor_loop() -> None:
        from services.ai_stream_service import get_ai_runtime_stats

        thread_level = 0
        task_queue_level = 0
        bg_queue_level = 0

        while _runtime_monitor_running:
            try:
                thread_count = _get_current_thread_count()
                ai_stats = get_ai_runtime_stats()

                next_thread_level = (
                    _threshold_level(thread_count, THREAD_WARNING_THRESHOLDS)
                    if thread_count >= 0
                    else 0
                )
                if next_thread_level > thread_level:
                    threshold = THREAD_WARNING_THRESHOLDS[next_thread_level - 1]
                    logger.warning(
                        "[RuntimeMonitor] Thread count crossed threshold: threads=%s threshold=%s ai_running=%s ai_task_queue=%s ai_bg_queue=%s",
                        thread_count,
                        threshold,
                        ai_stats["running_tasks"],
                        ai_stats["task_queue"],
                        ai_stats["background_queue"],
                    )
                thread_level = next_thread_level

                next_task_queue_level = _threshold_level(
                    ai_stats["task_queue"], AI_QUEUE_WARNING_THRESHOLDS
                )
                if next_task_queue_level > task_queue_level:
                    threshold = AI_QUEUE_WARNING_THRESHOLDS[next_task_queue_level - 1]
                    logger.warning(
                        "[RuntimeMonitor] AI task queue crossed threshold: queue=%s threshold=%s running=%s workers=%s threads=%s",
                        ai_stats["task_queue"],
                        threshold,
                        ai_stats["running_tasks"],
                        ai_stats["task_max_workers"],
                        ai_stats["task_threads"],
                    )
                task_queue_level = next_task_queue_level

                next_bg_queue_level = _threshold_level(
                    ai_stats["background_queue"], AI_QUEUE_WARNING_THRESHOLDS
                )
                if next_bg_queue_level > bg_queue_level:
                    threshold = AI_QUEUE_WARNING_THRESHOLDS[next_bg_queue_level - 1]
                    logger.warning(
                        "[RuntimeMonitor] AI background queue crossed threshold: queue=%s threshold=%s workers=%s threads=%s",
                        ai_stats["background_queue"],
                        threshold,
                        ai_stats["background_max_workers"],
                        ai_stats["background_threads"],
                    )
                bg_queue_level = next_bg_queue_level
            except Exception as exc:
                print(f"[runtime-monitor] non-fatal monitor error: {exc}", flush=True)

            time.sleep(RUNTIME_MONITOR_INTERVAL_SECONDS)

    _runtime_monitor_running = True
    _runtime_monitor_thread = threading.Thread(
        target=monitor_loop,
        daemon=True,
        name="runtime-monitor",
    )
    _runtime_monitor_thread.start()


def stop_runtime_monitor() -> None:
    """Ask the background monitor to stop on application shutdown."""
    global _runtime_monitor_running
    _runtime_monitor_running = False
