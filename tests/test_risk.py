import unittest

from bot.config import Settings
from bot.risk import RiskManager


class RiskManagerTest(unittest.TestCase):
    def test_compound_uses_balance_fraction_and_confidence(self):
        settings = Settings(max_trade_amount=25.0, min_trade_amount=0.99)
        decision = RiskManager(settings).size_trade(
            base_amount=0.99,
            confidence=0.3,
            balance=100.0,
            daily_loss=0,
            live_trades_today=0,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.amount, 2.0)

    def test_compound_caps_max_trade_amount(self):
        settings = Settings(max_trade_amount=10.0, min_trade_amount=0.99)
        decision = RiskManager(settings).size_trade(
            base_amount=0.99,
            confidence=1.0,
            balance=1000.0,
            daily_loss=0,
            live_trades_today=0,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.amount, 10.0)

    def test_low_balance_is_blocked(self):
        settings = Settings(max_trade_amount=10.0, min_trade_amount=0.99)
        decision = RiskManager(settings).size_trade(
            base_amount=0.99,
            confidence=0.3,
            balance=0.5,
            daily_loss=0,
            live_trades_today=0,
        )
        self.assertFalse(decision.allowed)


if __name__ == "__main__":
    unittest.main()

