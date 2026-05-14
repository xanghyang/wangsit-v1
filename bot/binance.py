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
            return self.http.get_json(
                f"{self.settings.binance_api}/api/v3/klines",
                params=params,
                timeout=3,
            )
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
            return float(data["price"])
        except Exception as exc:
            log(f"[BINANCE PRICE ERROR] {exc}")
            return 0.0

    def window_open_price(self, symbol: str, window_ts: int) -> float:
        candles = self.candles(symbol, "5m", 1, start_time=window_ts)
        if candles:
            return float(candles[0][1])
        return 0.0

    def atr(self, symbol: str, window_ts: int, periods: int) -> float:
        candles = self.candles(symbol, "5m", periods, end_time=window_ts)
        if not candles:
            return 0.0
        ranges = [float(c[2]) - float(c[3]) for c in candles]
        return sum(ranges) / len(ranges)

