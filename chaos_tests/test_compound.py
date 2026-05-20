import unittest
from unittest.mock import patch, MagicMock
from bot.runner import CryptoBot
from bot.config import Settings
from bot.state import BotState
import os

class TestAutoCompoundChaos(unittest.TestCase):

    @patch('bot.execution.ExecutionClient.buy')
    @patch('bot.execution.ExecutionClient.balance')
    def test_order_success_but_balance_update_fails(self, mock_get_balance, mock_buy):
        # 1. Kondisikan order sukses di bursa
        from bot.execution import ExecutionResult
        mock_result = ExecutionResult(ok=True, status="filled", order_id="0x123")
        mock_buy.return_value = mock_result

        # 2. SIMULASI CHAOS: API Saldo mendadak down tepat setelah order terkirim
        mock_get_balance.side_effect = [100.0, Exception("CLOB Gateway Error 502: Balance service unavailable")]

        settings = Settings(
            bankroll_fraction=0.02,
            state_path="data/test_state.json",
            private_key="0x123",
            proxy_wallet="0x456"
        )
        bot = CryptoBot(paper=False, dry_run=False, amount=1.0, settings=settings)

        print("\n🔥 [CHAOS TEST] Memulai simulasi order sukses namun API saldo hancur...")

        market = {
            "slug": "test-slug-123",
            "crypto": "BTC",
            "winner_price": 0.6,
            "winner_side": "Long",
            "winner_token": "0xtoken",
            "title": "Test Market"
        }
        signal = {"confidence": 0.5, "delta_pct": 0.01, "direction": "Long"}

        # Eksekusi _enter
        bot._enter(market, signal, 30.0)

        # 3. VERIFIKASI: State internal harus menyimpan trade tersebut
        state = BotState.load(settings.state_path, 1.0)
        self.assertTrue(any(t["slug"] == "test-slug-123" for t in state.trades))
        print("✅ [PASSED] State aman terproteksi. Bot mencatat trade meskipun ada gangguan (mocked).")

        if os.path.exists(settings.state_path):
            os.remove(settings.state_path)
