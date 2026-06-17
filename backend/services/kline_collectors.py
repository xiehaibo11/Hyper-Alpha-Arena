"""
K线数据采集器 - 交易所分流架构
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class KlineData:
    """标准化的K线数据结构"""
    exchange: str
    symbol: str
    timestamp: int  # Unix timestamp in seconds
    period: str     # "1m", "5m", "1h", etc.
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float


class BaseKlineCollector(ABC):
    """K线采集器基类 - 定义统一接口"""

    def __init__(self, exchange_id: str):
        self.exchange_id = exchange_id
        self.logger = logging.getLogger(f"{__name__}.{exchange_id}")

    @abstractmethod
    async def fetch_current_kline(self, symbol: str, period: str = "1m") -> Optional[KlineData]:
        """获取当前分钟的K线数据"""
        pass

    @abstractmethod
    async def fetch_historical_klines(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        period: str = "1m"
    ) -> List[KlineData]:
        """获取历史K线数据"""
        pass

    @abstractmethod
    def get_supported_symbols(self) -> List[str]:
        """获取支持的交易对列表"""
        pass


class HyperliquidKlineCollector(BaseKlineCollector):
    """Hyperliquid K线采集器"""

    def __init__(self):
        super().__init__("hyperliquid")
        # 复用现有的 hyperliquid_market_data 服务
        from .hyperliquid_market_data import HyperliquidClient
        self.market_data = HyperliquidClient()

    async def fetch_current_kline(self, symbol: str, period: str = "1m") -> Optional[KlineData]:
        """获取当前分钟K线"""
        try:
            # 调用现有的K线获取方法 (同步方法，不需要 await)
            klines = self.market_data.get_kline_data(symbol, period, count=1)
            if not klines:
                return None

            latest = klines[0]
            return KlineData(
                exchange=self.exchange_id,
                symbol=symbol,
                timestamp=int(latest['timestamp']),
                period=period,
                open_price=float(latest['open']),
                high_price=float(latest['high']),
                low_price=float(latest['low']),
                close_price=float(latest['close']),
                volume=float(latest['volume'])
            )
        except Exception as e:
            self.logger.error(f"Failed to fetch current kline for {symbol}: {e}")
            return None

    async def fetch_historical_klines(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        period: str = "1m"
    ) -> List[KlineData]:
        """获取历史K线数据"""
        try:
            # 计算需要的数据量
            time_diff = end_time - start_time
            if period == "1m":
                limit = int(time_diff.total_seconds() / 60)
            else:
                # 其他周期的计算逻辑
                limit = 1000  # 默认限制

            # 调用现有方法获取历史数据 (同步方法，不需要await)
            klines = self.market_data.get_kline_data(
                symbol, period, count=min(limit, 5000)
            )

            result = []
            for kline in klines:
                kline_time = datetime.fromtimestamp(kline['timestamp'])
                if start_time <= kline_time <= end_time:
                    result.append(KlineData(
                        exchange=self.exchange_id,
                        symbol=symbol,
                        timestamp=int(kline['timestamp']),
                        period=period,
                        open_price=float(kline['open']),
                        high_price=float(kline['high']),
                        low_price=float(kline['low']),
                        close_price=float(kline['close']),
                        volume=float(kline['volume'])
                    ))

            return result
        except Exception as e:
            self.logger.error(f"Failed to fetch historical klines for {symbol}: {e}")
            return []

    def get_supported_symbols(self) -> List[str]:
        """获取用户Watch List中选择的交易对（实时采集用）"""
        try:
            from .hyperliquid_symbol_service import get_selected_symbols
            symbols = get_selected_symbols()
            if symbols:
                return symbols
        except Exception as e:
            self.logger.warning(f"Failed to get symbols from hyperliquid_symbol_service: {e}")

        # Fallback to BTC only
        return ["BTC"]


class BinanceKlineCollector(BaseKlineCollector):
    """Binance K线采集器"""

    def __init__(self):
        super().__init__("binance")
        from .exchanges.binance_adapter import BinanceAdapter
        self.adapter = BinanceAdapter()

    def _convert_kline(self, kline, period: str) -> KlineData:
        """Convert unified Binance adapter data to the legacy KlineData shape."""
        return KlineData(
            exchange=self.exchange_id,
            symbol=kline.symbol,
            timestamp=int(kline.timestamp),
            period=period,
            open_price=float(kline.open_price),
            high_price=float(kline.high_price),
            low_price=float(kline.low_price),
            close_price=float(kline.close_price),
            volume=float(kline.volume),
        )

    async def fetch_current_kline(self, symbol: str, period: str = "1m") -> Optional[KlineData]:
        """获取当前K线"""
        try:
            klines = self.adapter.fetch_klines(symbol, period, limit=1)
            if not klines:
                return None
            return self._convert_kline(klines[-1], period)
        except Exception as e:
            self.logger.error(f"Failed to fetch Binance current kline for {symbol}/{period}: {e}")
            return None

    async def fetch_historical_klines(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        period: str = "1m"
    ) -> List[KlineData]:
        """获取历史K线数据"""
        try:
            start_ms = int(start_time.timestamp() * 1000)
            end_ms = int(end_time.timestamp() * 1000)

            klines = self.adapter.fetch_klines(
                symbol,
                period,
                limit=1500,
                start_time=start_ms,
                end_time=end_ms,
            )
            return [self._convert_kline(kline, period) for kline in klines]
        except Exception as e:
            self.logger.error(f"Failed to fetch Binance historical klines for {symbol}/{period}: {e}")
            return []

    def get_supported_symbols(self) -> List[str]:
        """获取用户 Binance Watch List 中选择的交易对（内部格式）"""
        try:
            from .binance_symbol_service import get_selected_symbols
            symbols = get_selected_symbols()
            if symbols:
                return symbols
        except Exception as e:
            self.logger.warning(f"Failed to get symbols from binance_symbol_service: {e}")

        return ["BTC"]


class OKXKlineCollector(BaseKlineCollector):
    """OKX K-line collector."""

    def __init__(self):
        super().__init__("okx")
        from .exchanges.okx_adapter import OKXAdapter
        self.adapter = OKXAdapter()

    def _convert_kline(self, kline, period: str) -> KlineData:
        return KlineData(
            exchange=self.exchange_id,
            symbol=kline.symbol,
            timestamp=int(kline.timestamp),
            period=period,
            open_price=float(kline.open_price),
            high_price=float(kline.high_price),
            low_price=float(kline.low_price),
            close_price=float(kline.close_price),
            volume=float(kline.volume),
        )

    async def fetch_current_kline(self, symbol: str, period: str = "1m") -> Optional[KlineData]:
        try:
            klines = self.adapter.fetch_klines(symbol, period, limit=1)
            if not klines:
                return None
            return self._convert_kline(klines[-1], period)
        except Exception as e:
            self.logger.error(f"Failed to fetch OKX current kline for {symbol}/{period}: {e}")
            return None

    async def fetch_historical_klines(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        period: str = "1m"
    ) -> List[KlineData]:
        try:
            start_ms = int(start_time.timestamp() * 1000)
            end_ms = int(end_time.timestamp() * 1000)
            klines = self.adapter.fetch_klines(
                symbol,
                period,
                limit=2000,
                start_time=start_ms,
                end_time=end_ms,
            )
            return [self._convert_kline(kline, period) for kline in klines]
        except Exception as e:
            self.logger.error(f"Failed to fetch OKX historical klines for {symbol}/{period}: {e}")
            return []

    def get_supported_symbols(self) -> List[str]:
        try:
            from .okx_symbol_service import get_selected_symbols
            symbols = get_selected_symbols()
            if symbols:
                return symbols
        except Exception as e:
            self.logger.warning(f"Failed to get symbols from okx_symbol_service: {e}")

        return ["BTC"]


class AsterKlineCollector(BaseKlineCollector):
    """Aster DEX K线采集器 - 预留实现"""

    def __init__(self):
        super().__init__("aster")

    async def fetch_current_kline(self, symbol: str, period: str = "1m") -> Optional[KlineData]:
        # TODO: 实现Aster API调用
        self.logger.warning("Aster collector not implemented yet")
        return None

    async def fetch_historical_klines(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        period: str = "1m"
    ) -> List[KlineData]:
        # TODO: 实现Aster历史数据获取
        self.logger.warning("Aster historical data not implemented yet")
        return []

    def get_supported_symbols(self) -> List[str]:
        return ["BTC/USDT", "ETH/USDT"]  # 示例


class CryptoComKlineCollector(BaseKlineCollector):
    """Crypto.com K线采集器(OHLCV;无 taker 量)。"""

    def __init__(self):
        super().__init__("crypto_com")
        from .exchanges.crypto_com_adapter import CryptoComAdapter
        self.adapter = CryptoComAdapter()

    def _convert(self, kline, period: str) -> KlineData:
        return KlineData(
            exchange=self.exchange_id, symbol=kline.symbol,
            timestamp=int(kline.timestamp), period=period,
            open_price=float(kline.open_price), high_price=float(kline.high_price),
            low_price=float(kline.low_price), close_price=float(kline.close_price),
            volume=float(kline.volume),
        )

    async def fetch_current_kline(self, symbol: str, period: str = "1m") -> Optional[KlineData]:
        try:
            ks = self.adapter.fetch_klines(symbol, period, limit=1)
            return self._convert(ks[-1], period) if ks else None
        except Exception as e:
            self.logger.error(f"Failed to fetch Crypto.com current kline for {symbol}/{period}: {e}")
            return None

    async def fetch_historical_klines(
        self, symbol: str, start_time: datetime, end_time: datetime, period: str = "1m"
    ) -> List[KlineData]:
        try:
            ks = self.adapter.fetch_klines(symbol, period, limit=300)
            return [self._convert(k, period) for k in ks]
        except Exception as e:
            self.logger.error(f"Failed to fetch Crypto.com historical klines for {symbol}/{period}: {e}")
            return []

    def get_supported_symbols(self) -> List[str]:
        return ["BTC", "ETH"]


class GateKlineCollector(BaseKlineCollector):
    """Gate.io USDT-futures K线采集器(OHLCV;无 taker 量)。"""

    def __init__(self):
        super().__init__("gate")
        from .exchanges.gate_adapter import GateAdapter
        self.adapter = GateAdapter()

    def _convert(self, kline, period: str) -> KlineData:
        return KlineData(
            exchange=self.exchange_id, symbol=kline.symbol,
            timestamp=int(kline.timestamp), period=period,
            open_price=float(kline.open_price), high_price=float(kline.high_price),
            low_price=float(kline.low_price), close_price=float(kline.close_price),
            volume=float(kline.volume),
        )

    async def fetch_current_kline(self, symbol: str, period: str = "1m") -> Optional[KlineData]:
        try:
            ks = self.adapter.fetch_klines(symbol, period, limit=2)
            return self._convert(ks[-1], period) if ks else None
        except Exception as e:
            self.logger.error(f"Failed to fetch Gate current kline for {symbol}/{period}: {e}")
            return None

    async def fetch_historical_klines(
        self, symbol: str, start_time: datetime, end_time: datetime, period: str = "1m"
    ) -> List[KlineData]:
        try:
            ks = self.adapter.fetch_klines(symbol, period, limit=2000)
            return [self._convert(k, period) for k in ks]
        except Exception as e:
            self.logger.error(f"Failed to fetch Gate historical klines for {symbol}/{period}: {e}")
            return []

    def get_supported_symbols(self) -> List[str]:
        return ["BTC", "ETH"]


class ExchangeDataSourceFactory:
    """交易所数据源工厂 - 根据配置返回对应采集器"""

    _collectors = {
        "hyperliquid": HyperliquidKlineCollector,
        "binance": BinanceKlineCollector,
        "okx": OKXKlineCollector,
        "aster": AsterKlineCollector,
        "crypto_com": CryptoComKlineCollector,
        "gate": GateKlineCollector,
    }

    @classmethod
    def get_collector(cls, exchange_id: str) -> BaseKlineCollector:
        """根据交易所ID获取对应的采集器实例"""
        if exchange_id not in cls._collectors:
            raise ValueError(f"Unsupported exchange: {exchange_id}")

        collector_class = cls._collectors[exchange_id]
        return collector_class()

    @classmethod
    def get_supported_exchanges(cls) -> List[str]:
        """获取支持的交易所列表"""
        return list(cls._collectors.keys())
