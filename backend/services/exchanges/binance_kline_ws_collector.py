"""
Binance K-line WebSocket collector.

REST polling is too expensive for large symbol sets because Binance klines are
requested per symbol and interval. This collector subscribes to kline streams and
persists only closed candles, keeping database writes bounded while meeting
sub-minute freshness.
"""

import json
import logging
import os
import threading
import time
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from database.connection import SessionLocal
from services.exchanges.base_adapter import UnifiedKline
from services.exchanges.data_persistence import ExchangeDataPersistence
from services.exchanges.symbol_mapper import SymbolMapper

logger = logging.getLogger(__name__)

WS_URL = "wss://fstream.binance.com/market/ws"
RECONNECT_DELAY_SECONDS = 5
PING_INTERVAL_SECONDS = 180
PING_TIMEOUT_SECONDS = 30


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _csv_env(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


KLINE_WS_INTERVALS = _csv_env(
    "BINANCE_KLINE_WS_INTERVALS",
    "1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M",
)
MAX_STREAMS_PER_CONNECTION = min(
    1024,
    _int_env("BINANCE_KLINE_WS_MAX_STREAMS_PER_CONNECTION", 900),
)
FLUSH_INTERVAL_SECONDS = _int_env("BINANCE_KLINE_WS_FLUSH_INTERVAL_SECONDS", 30)
SUBSCRIBE_CHUNK_SIZE = _int_env("BINANCE_KLINE_WS_SUBSCRIBE_CHUNK_SIZE", 200)
MAX_REQUEUE_KLINES = _int_env("BINANCE_KLINE_WS_MAX_REQUEUE_KLINES", 5000)


class BinanceKlineWSCollector:
    """Collect closed Binance K-lines over WebSocket."""

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
        self.symbols: List[str] = []
        self.intervals: List[str] = KLINE_WS_INTERVALS
        self.running = False
        self.ws_threads: List[threading.Thread] = []
        self.flush_thread: Optional[threading.Thread] = None
        self._generation = 0
        self._lifecycle_lock = threading.RLock()
        self._sockets = []
        self._sockets_lock = threading.Lock()
        self._buffer_lock = threading.Lock()
        self._closed_klines: List[UnifiedKline] = []
        self._open_klines: Dict[Tuple[str, str, int], UnifiedKline] = {}
        self._active_symbol_set = set()
        logger.info("BinanceKlineWSCollector initialized")

    def start(self, symbols: Optional[List[str]] = None):
        """Start kline stream collection for selected symbols."""
        with self._lifecycle_lock:
            if self.running:
                logger.warning("BinanceKlineWSCollector already running")
                return

            if symbols is None:
                from services.binance_symbol_service import get_selected_symbols

                symbols = get_selected_symbols() or ["BTC"]

            self.symbols = self._normalize_symbols(symbols)
            self._active_symbol_set = set(self.symbols)
            self.intervals = KLINE_WS_INTERVALS
            streams = self._build_streams(self.symbols, self.intervals)
            if not streams:
                logger.warning("[Binance Kline WS] No streams to subscribe")
                return

            self._generation += 1
            generation = self._generation
            self.running = True
            self.ws_threads = []
            for idx, chunk in enumerate(self._chunks(streams, MAX_STREAMS_PER_CONNECTION), start=1):
                thread = threading.Thread(
                    target=self._ws_loop,
                    args=(idx, chunk, generation),
                    daemon=True,
                    name=f"binance-kline-ws-{idx}",
                )
                thread.start()
                self.ws_threads.append(thread)

            self.flush_thread = threading.Thread(
                target=self._flush_loop,
                args=(generation,),
                daemon=True,
                name="binance-kline-ws-flush",
            )
            self.flush_thread.start()

            logger.info(
                "[Binance Kline WS] Started: generation=%d symbols=%d intervals=%s streams=%d connections=%d",
                generation,
                len(self.symbols),
                ",".join(self.intervals),
                len(streams),
                len(self.ws_threads),
            )

    def stop(self, flush: bool = True):
        """Stop kline stream collection."""
        with self._lifecycle_lock:
            if not self.running:
                return

            self.running = False
            self._generation += 1
            threads = list(self.ws_threads)
            flush_thread = self.flush_thread
            with self._sockets_lock:
                sockets = list(self._sockets)
                self._sockets.clear()

            for ws in sockets:
                try:
                    ws.close()
                except Exception:
                    pass

            for thread in threads:
                if thread.is_alive():
                    thread.join(timeout=3)
            if flush_thread and flush_thread.is_alive():
                flush_thread.join(timeout=3)

            if flush:
                self._flush_closed_klines()
            else:
                with self._buffer_lock:
                    self._closed_klines = []
                    self._open_klines = {}

            self.ws_threads = []
            self.flush_thread = None
            logger.info("BinanceKlineWSCollector stopped")

    def refresh_symbols(self, new_symbols: List[str]):
        """Restart streams with a new symbol set."""
        logger.info("[Binance Kline WS] Symbol refresh requested: %s", new_symbols)
        with self._lifecycle_lock:
            self.stop(flush=False)
            time.sleep(1)
            self.start(new_symbols)

    def _ws_loop(self, connection_id: int, streams: List[str], generation: int):
        while self.running and generation == self._generation:
            try:
                self._connect_and_process(connection_id, streams, generation)
            except Exception as exc:
                logger.error("[Binance Kline WS] Connection %s error: %s", connection_id, exc)
            if self.running and generation == self._generation:
                time.sleep(RECONNECT_DELAY_SECONDS)

    def _connect_and_process(self, connection_id: int, streams: List[str], generation: int):
        import websocket

        def on_message(ws, message):
            try:
                payload = json.loads(message)
                self._process_message(payload, generation)
            except Exception as exc:
                logger.error("[Binance Kline WS] Message processing error: %s", exc)

        def on_error(ws, error):
            logger.error("[Binance Kline WS] Connection %s websocket error: %s", connection_id, error)

        def on_close(ws, close_status_code, close_msg):
            logger.warning(
                "[Binance Kline WS] Connection %s closed: %s %s",
                connection_id,
                close_status_code,
                close_msg,
            )

        def on_open(ws):
            if generation != self._generation:
                ws.close()
                return
            for chunk_id, chunk in enumerate(self._chunks(streams, SUBSCRIBE_CHUNK_SIZE), start=1):
                ws.send(json.dumps({
                    "method": "SUBSCRIBE",
                    "params": chunk,
                    "id": connection_id * 1000 + chunk_id,
                }))
                time.sleep(0.25)
            logger.info(
                "[Binance Kline WS] Connection %s subscribed to %d streams",
                connection_id,
                len(streams),
            )

        ws = websocket.WebSocketApp(
            WS_URL,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )
        with self._sockets_lock:
            self._sockets.append(ws)

        try:
            ws.run_forever(
                ping_interval=PING_INTERVAL_SECONDS,
                ping_timeout=PING_TIMEOUT_SECONDS,
            )
        finally:
            with self._sockets_lock:
                if ws in self._sockets:
                    self._sockets.remove(ws)

    def _process_message(self, payload: dict, generation: Optional[int] = None):
        if generation is None:
            generation = self._generation
        if generation != self._generation:
            return
        data = payload.get("data") if "data" in payload else payload
        if not isinstance(data, dict) or data.get("e") != "kline":
            return

        kline_data = data.get("k") or {}
        kline = self._parse_kline(data, kline_data)
        if kline.symbol not in self._active_symbol_set:
            logger.debug("[Binance Kline WS] Dropped stale symbol %s from old stream", kline.symbol)
            return
        key = self._kline_key(kline)
        with self._buffer_lock:
            if kline_data.get("x"):
                self._closed_klines.append(kline)
                self._open_klines.pop(key, None)
            else:
                self._open_klines[key] = kline

    def _parse_kline(self, data: dict, kline_data: dict) -> UnifiedKline:
        exchange_symbol = kline_data.get("s") or data.get("s")
        symbol = SymbolMapper.to_internal(str(exchange_symbol or ""), "binance")
        volume = Decimal(str(kline_data["v"]))
        quote_volume = Decimal(str(kline_data["q"]))
        taker_buy_volume = Decimal(str(kline_data.get("V", "0")))
        taker_buy_notional = Decimal(str(kline_data.get("Q", "0")))
        taker_sell_volume = self._non_negative(volume - taker_buy_volume)
        taker_sell_notional = self._non_negative(quote_volume - taker_buy_notional)

        return UnifiedKline(
            exchange="binance",
            symbol=symbol,
            interval=str(kline_data["i"]),
            timestamp=int(kline_data["t"]) // 1000,
            open_price=Decimal(str(kline_data["o"])),
            high_price=Decimal(str(kline_data["h"])),
            low_price=Decimal(str(kline_data["l"])),
            close_price=Decimal(str(kline_data["c"])),
            volume=volume,
            quote_volume=quote_volume,
            taker_buy_volume=taker_buy_volume,
            taker_sell_volume=taker_sell_volume,
            taker_buy_notional=taker_buy_notional,
            taker_sell_notional=taker_sell_notional,
            trade_count=int(kline_data.get("n") or 0),
        )

    def _flush_loop(self, generation: int):
        while self.running and generation == self._generation:
            time.sleep(FLUSH_INTERVAL_SECONDS)
            self._flush_closed_klines()

    def _flush_closed_klines(self):
        with self._buffer_lock:
            if not self._closed_klines and not self._open_klines:
                return
            closed_klines = self._closed_klines
            open_klines = list(self._open_klines.values())
            self._closed_klines = []

        klines = self._dedupe_klines([
            kline for kline in closed_klines + open_klines
            if kline.symbol in self._active_symbol_set
        ])
        if not klines:
            return
        db = SessionLocal()
        try:
            persistence = ExchangeDataPersistence(db)
            result = persistence.save_klines(klines)
            one_minute_klines = [kline for kline in klines if kline.interval == "1m"]
            if one_minute_klines:
                persistence.save_taker_volumes_from_klines(one_minute_klines)
            logger.info(
                "[Binance Kline WS] Flushed klines: closed=%d open=%d result=%s",
                len(closed_klines),
                len(open_klines),
                result,
            )
        except Exception as exc:
            logger.error("[Binance Kline WS] Failed to flush klines: %s", exc)
            with self._buffer_lock:
                self._closed_klines = (closed_klines + self._closed_klines)[-MAX_REQUEUE_KLINES:]
        finally:
            db.close()

    def _build_streams(self, symbols: List[str], intervals: List[str]) -> List[str]:
        streams = []
        for symbol in symbols:
            exchange_symbol = SymbolMapper.to_exchange(symbol, "binance").lower()
            for interval in intervals:
                streams.append(f"{exchange_symbol}@kline_{interval}")
        return streams

    def _normalize_symbols(self, symbols: List[str]) -> List[str]:
        normalized = []
        seen = set()
        for symbol in symbols:
            value = SymbolMapper.to_internal(str(symbol or "").strip().upper(), "binance")
            value = str(value or "").strip().upper()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    def _chunks(self, values: List[str], chunk_size: int):
        for idx in range(0, len(values), chunk_size):
            yield values[idx:idx + chunk_size]

    def _non_negative(self, value: Decimal) -> Decimal:
        return value if value >= 0 else Decimal("0")

    def _kline_key(self, kline: UnifiedKline) -> Tuple[str, str, int]:
        return kline.symbol, kline.interval, kline.timestamp

    def _dedupe_klines(self, klines: List[UnifiedKline]) -> List[UnifiedKline]:
        by_key: Dict[Tuple[str, str, int], UnifiedKline] = {}
        for kline in klines:
            by_key[self._kline_key(kline)] = kline
        return list(by_key.values())


binance_kline_ws_collector = BinanceKlineWSCollector()
