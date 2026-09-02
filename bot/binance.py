from bot.config import Settings
from bot.http import HttpClient
from bot.logging_setup import log


class BinanceClient:
    def __init__(self, settings: Settings, http: HttpClient | None = None):
        self.settings = settings
        self.http = http or HttpClient(retries=1)

    def candles(self, symbol: str, interval: str = "1m", limit: int = 6,
                start_time: int | None = None, end_time: int | None = None) -> list:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time * 1000
        if end_time is not None:
            params["endTime"] = end_time * 1000
        try:
            res = self.http.get_json(
                f"{self.settings.binance_api}/api/v3/klines",
                params=params,
                timeout=3,
            )
            if isinstance(res, list):
                return res
            return []
        except Exception as exc:
            log(f"[BINANCE ERROR] {exc}")
            return []

    def price(self, symbol: str) -> float:
        try:
            data = self.http.get_json(
                f"{self.settings.binance_api}/api/v3/ticker/price",
                params={"symbol": symbol},
                timeout=2,
            )
            if isinstance(data, dict) and "price" in data:
                return float(data["price"])
            return 0.0
        except Exception as exc:
            log(f"[BINANCE PRICE ERROR] {exc}")
            return 0.0

    def window_open_price(self, symbol: str, window_ts: int) -> float:
        try:
            candles = self.candles(symbol, "5m", 1, start_time=window_ts)
            if candles and isinstance(candles, list) and len(candles) > 0 and len(candles[0]) >= 2:
                return float(candles[0][1])
        except Exception as exc:
            log(f"[BINANCE WINDOW OPEN ERROR] {exc}")
        return 0.0

    def atr(self, symbol: str, window_ts: int, periods: int) -> float:
        try:
            candles = self.candles(symbol, "5m", periods, end_time=window_ts)
            if not candles or not isinstance(candles, list):
                return 0.0
            ranges = []
            for c in candles:
                if isinstance(c, list) and len(c) >= 4:
                    ranges.append(float(c[2]) - float(c[3]))
            if not ranges:
                return 0.0
            return sum(ranges) / len(ranges)
        except Exception as exc:
            log(f"[BINANCE ATR ERROR] {exc}")
            return 0.0

