"""
Shared Binance REST request limiter.

The limit is intentionally lower than Binance's documented IP weight cap so
background collectors leave room for manual UI/API requests from the same host.
"""

import logging
import os
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


class BinanceRestRateLimiter:
    """Simple process-local sliding-window limiter for Binance REST calls."""

    def __init__(self, max_calls_per_minute: int):
        self.max_calls_per_minute = max_calls_per_minute
        self._timestamps = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                cutoff = now - 60
                while self._timestamps and self._timestamps[0] <= cutoff:
                    self._timestamps.popleft()

                if len(self._timestamps) < self.max_calls_per_minute:
                    self._timestamps.append(now)
                    return

                wait_seconds = max(0.05, 60 - (now - self._timestamps[0]))

            logger.warning(
                "[Binance] REST call limiter reached %s/min, sleeping %.2fs",
                self.max_calls_per_minute,
                wait_seconds,
            )
            time.sleep(wait_seconds)


binance_rest_rate_limiter = BinanceRestRateLimiter(
    _int_env("BINANCE_REST_CALL_LIMIT_PER_MINUTE", 300)
)
