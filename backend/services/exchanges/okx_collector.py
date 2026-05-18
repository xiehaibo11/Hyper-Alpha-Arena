"""OKX REST public market-data collector."""

from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database.connection import SessionLocal
from services.exchanges.data_persistence import ExchangeDataPersistence
from services.exchanges.okx_adapter import OKXAdapter

logger = logging.getLogger(__name__)


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _csv_env(name: str, default: str) -> List[str]:
    return [item.strip().upper() for item in os.getenv(name, default).split(",") if item.strip()]


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


PRIMARY_SYMBOLS = _csv_env("OKX_PRIMARY_SYMBOLS", "BTC,ETH,SOL,XRP")
KLINE_PERIODS = [
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
]

KLINE_INTERVAL_SECONDS = _int_env("OKX_KLINE_INTERVAL_SECONDS", 60)
OI_INTERVAL_SECONDS = _int_env("OKX_OI_INTERVAL_SECONDS", 60)
FUNDING_INTERVAL_SECONDS = _int_env("OKX_FUNDING_INTERVAL_SECONDS", 60)
SENTIMENT_INTERVAL_SECONDS = _int_env("OKX_SENTIMENT_INTERVAL_SECONDS", 300)
TAKER_VOLUME_INTERVAL_SECONDS = _int_env("OKX_TAKER_VOLUME_INTERVAL_SECONDS", 300)
ORDERBOOK_INTERVAL_SECONDS = _int_env("OKX_ORDERBOOK_INTERVAL_SECONDS", 15)

KLINE_ROTATION_BATCH_SIZE = _int_env("OKX_KLINE_ROTATION_BATCH_SIZE", 20)
OI_ROTATION_BATCH_SIZE = _int_env("OKX_OI_ROTATION_BATCH_SIZE", 25)
FUNDING_ROTATION_BATCH_SIZE = _int_env("OKX_FUNDING_ROTATION_BATCH_SIZE", 25)
SENTIMENT_ROTATION_BATCH_SIZE = _int_env("OKX_SENTIMENT_ROTATION_BATCH_SIZE", 20)
TAKER_VOLUME_ROTATION_BATCH_SIZE = _int_env("OKX_TAKER_VOLUME_ROTATION_BATCH_SIZE", 20)
ORDERBOOK_ROTATION_BATCH_SIZE = _int_env("OKX_ORDERBOOK_ROTATION_BATCH_SIZE", 10)

REST_KLINE_BACKUP_ENABLED = _bool_env("OKX_REST_KLINE_BACKUP_ENABLED", False)
REST_KLINE_INITIAL_BACKFILL_ENABLED = _bool_env("OKX_REST_KLINE_INITIAL_BACKFILL_ENABLED", False)
REST_KLINE_INITIAL_LIMIT = _int_env("OKX_REST_KLINE_INITIAL_LIMIT", 2)


class OKXCollector:
    """Singleton service for bounded OKX REST market-data polling."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.adapter = OKXAdapter()
        self.scheduler: Optional[BackgroundScheduler] = None
        self.running = False
        self.symbols: List[str] = []
        self._rotation_cursors = {
            "kline": 0,
            "oi": 0,
            "funding": 0,
            "sentiment": 0,
            "taker": 0,
            "orderbook": 0,
        }
        logger.info("OKXCollector initialized")

    def start(self, symbols: Optional[List[str]] = None) -> None:
        if self.running:
            logger.warning("OKXCollector already running")
            return
        if symbols is None:
            from services.okx_symbol_service import get_selected_symbols

            symbols = get_selected_symbols() or ["BTC"]

        self.symbols = [str(item).upper() for item in symbols if str(item).strip()]
        self.scheduler = BackgroundScheduler()

        if REST_KLINE_BACKUP_ENABLED:
            self._add_kline_job()
        else:
            logger.info("OKX REST kline backup job disabled; K-lines are filled on demand")
        self._add_oi_job()
        self._add_funding_job()
        self._add_sentiment_job()
        self._add_taker_volume_job()
        self._add_orderbook_job()

        self.scheduler.start()
        self.running = True
        logger.info("OKXCollector started with symbols: %s", self.symbols)

        threading.Thread(
            target=self._collect_all_initial,
            daemon=True,
            name="okx-initial-collection",
        ).start()

    def stop(self) -> None:
        if not self.running:
            return
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        self.running = False
        logger.info("OKXCollector stopped")

    def refresh_symbols(self, new_symbols: List[str]) -> None:
        self.symbols = [str(item).upper() for item in new_symbols if str(item).strip()]
        for key in self._rotation_cursors:
            self._rotation_cursors[key] = 0
        logger.info("OKXCollector symbols updated: %s", self.symbols)

    def _primary_symbols(self) -> List[str]:
        selected = set(self.symbols)
        return [symbol for symbol in PRIMARY_SYMBOLS if symbol in selected]

    def _rotating_symbols(self, key: str, batch_size: int, include_primary: bool = True) -> List[str]:
        primary = self._primary_symbols() if include_primary else []
        primary_set = set(primary)
        rotating_pool = [symbol for symbol in self.symbols if symbol not in primary_set]
        if not rotating_pool:
            return primary

        cursor = self._rotation_cursors.get(key, 0) % len(rotating_pool)
        batch = []
        for offset in range(min(batch_size, len(rotating_pool))):
            batch.append(rotating_pool[(cursor + offset) % len(rotating_pool)])
        self._rotation_cursors[key] = (cursor + len(batch)) % len(rotating_pool)

        merged = []
        seen = set()
        for symbol in primary + batch:
            if symbol in seen:
                continue
            seen.add(symbol)
            merged.append(symbol)
        return merged

    def _add_kline_job(self) -> None:
        self.scheduler.add_job(
            func=self._collect_klines,
            trigger=IntervalTrigger(seconds=KLINE_INTERVAL_SECONDS),
            id="okx_klines",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def _add_oi_job(self) -> None:
        self.scheduler.add_job(
            func=self._collect_oi,
            trigger=IntervalTrigger(seconds=OI_INTERVAL_SECONDS),
            id="okx_oi",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def _add_funding_job(self) -> None:
        self.scheduler.add_job(
            func=self._collect_funding,
            trigger=IntervalTrigger(seconds=FUNDING_INTERVAL_SECONDS),
            id="okx_funding",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def _add_sentiment_job(self) -> None:
        self.scheduler.add_job(
            func=self._collect_sentiment,
            trigger=IntervalTrigger(seconds=SENTIMENT_INTERVAL_SECONDS),
            id="okx_sentiment",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def _add_taker_volume_job(self) -> None:
        self.scheduler.add_job(
            func=self._collect_taker_volume,
            trigger=IntervalTrigger(seconds=TAKER_VOLUME_INTERVAL_SECONDS),
            id="okx_taker_volume",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def _add_orderbook_job(self) -> None:
        self.scheduler.add_job(
            func=self._collect_orderbook,
            trigger=IntervalTrigger(seconds=ORDERBOOK_INTERVAL_SECONDS),
            id="okx_orderbook",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def _collect_all_initial(self) -> None:
        logger.info("[OKX] Running initial data collection")
        if REST_KLINE_INITIAL_BACKFILL_ENABLED:
            self._collect_initial_klines()
        self._collect_oi()
        self._collect_funding()
        self._collect_sentiment()
        self._collect_taker_volume()
        self._collect_orderbook()
        logger.info("[OKX] Initial data collection completed")

    def _collect_initial_klines(self) -> None:
        with SessionLocal() as db:
            persistence = ExchangeDataPersistence(db)
            for symbol in self.symbols:
                for period in KLINE_PERIODS:
                    try:
                        klines = self.adapter.fetch_klines(symbol, period, limit=REST_KLINE_INITIAL_LIMIT)
                        if klines:
                            persistence.save_klines(klines)
                    except Exception as exc:
                        logger.warning("[OKX] Initial kline backfill failed for %s/%s: %s", symbol, period, exc)

    def _collect_klines(self) -> None:
        with SessionLocal() as db:
            persistence = ExchangeDataPersistence(db)
            primary_symbols = self._primary_symbols()
            rotation_symbols = self._rotating_symbols("kline", KLINE_ROTATION_BATCH_SIZE, include_primary=False)
            collection_plan = [(symbol, KLINE_PERIODS) for symbol in primary_symbols]
            collection_plan.extend((symbol, ["1m"]) for symbol in rotation_symbols)
            for symbol, periods in collection_plan:
                for period in periods:
                    try:
                        klines = self.adapter.fetch_klines(symbol, period, limit=5)
                        if klines:
                            persistence.save_klines(klines)
                    except Exception as exc:
                        logger.warning("[OKX] Failed to collect klines for %s/%s: %s", symbol, period, exc)

    def _collect_oi(self) -> None:
        with SessionLocal() as db:
            persistence = ExchangeDataPersistence(db)
            for symbol in self._rotating_symbols("oi", OI_ROTATION_BATCH_SIZE):
                try:
                    oi = self.adapter.fetch_open_interest(symbol)
                    if oi:
                        persistence.save_open_interest(oi)
                except Exception as exc:
                    logger.warning("[OKX] Failed to collect OI for %s: %s", symbol, exc)

    def _collect_funding(self) -> None:
        with SessionLocal() as db:
            persistence = ExchangeDataPersistence(db)
            for symbol in self._rotating_symbols("funding", FUNDING_ROTATION_BATCH_SIZE):
                try:
                    funding = self.adapter.fetch_funding_rate(symbol)
                    if funding:
                        persistence.save_funding_rate(funding)
                except Exception as exc:
                    logger.warning("[OKX] Failed to collect funding for %s: %s", symbol, exc)

    def _collect_sentiment(self) -> None:
        with SessionLocal() as db:
            persistence = ExchangeDataPersistence(db)
            for symbol in self._rotating_symbols("sentiment", SENTIMENT_ROTATION_BATCH_SIZE):
                try:
                    sentiment = self.adapter.fetch_sentiment_history(symbol, "5m", limit=3)
                    if sentiment:
                        persistence.save_sentiment_batch(sentiment)
                except Exception as exc:
                    logger.warning("[OKX] Failed to collect sentiment for %s: %s", symbol, exc)

    def _collect_taker_volume(self) -> None:
        with SessionLocal() as db:
            persistence = ExchangeDataPersistence(db)
            for symbol in self._rotating_symbols("taker", TAKER_VOLUME_ROTATION_BATCH_SIZE):
                try:
                    points = self.adapter.fetch_taker_volume_history(symbol, "5m", limit=3)
                    if points:
                        persistence.save_taker_volume_points(points)
                except Exception as exc:
                    logger.warning("[OKX] Failed to collect taker volume for %s: %s", symbol, exc)

    def _collect_orderbook(self) -> None:
        with SessionLocal() as db:
            persistence = ExchangeDataPersistence(db)
            for symbol in self._rotating_symbols("orderbook", ORDERBOOK_ROTATION_BATCH_SIZE):
                try:
                    orderbook = self.adapter.fetch_orderbook(symbol, depth=10)
                    if orderbook:
                        persistence.save_orderbook(orderbook)
                except Exception as exc:
                    logger.warning("[OKX] Failed to collect orderbook for %s: %s", symbol, exc)


okx_collector = OKXCollector()
