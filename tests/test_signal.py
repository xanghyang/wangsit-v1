import unittest

from bot.config import Settings
from bot.signal import SignalEngine


class FakeBinance:
    def price(self, symbol):
        return 99.0

    def window_open_price(self, symbol, window_ts):
        return 100.0

    def atr(self, symbol, window_ts, periods):
        return 10.0

    def candles(self, symbol, interval="1m", limit=6, start_time=None, end_time=None):
        if interval == "5m":
            return [[0, "100", "101", "98", "99"]]
        return [
            [0, "100", "100", "100", "100"],
            [0, "100", "100", "100", "99.5"],
            [0, "100", "100", "100", "99.0"],
        ]


class SignalEngineTest(unittest.TestCase):
    def test_down_momentum_strengthens_down_score(self):
        signal = SignalEngine(Settings(), FakeBinance()).analyze("BTCUSDT", 0)
        self.assertEqual(signal.direction, "Down")
        self.assertLess(signal.score, 0)
        self.assertGreaterEqual(signal.confidence, 7 / 9)


if __name__ == "__main__":
    unittest.main()

