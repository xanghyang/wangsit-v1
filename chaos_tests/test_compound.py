import unittest
from unittest.mock import patch, MagicMock
from bot.runner import BotRunner
from bot.config import Config
from bot.state import PersistentState

class TestAutoCompoundChaos(unittest.TestCase):

    @patch('bot.execution.PolymarketCLOBClient.place_order')
    @patch('bot.polymarket.PolymarketGammaClient.get_balance')
    def test_order_success_but_balance_update_fails(self, mock_get_balance, mock_place_order):
        # 1. Kondisikan order sukses di bursa
        mock_place_order.return_value = {"order_id": "0xchaos123", "status": "SUBMITTED"}
        
        # 2. SIMULASI CHAOS: API Saldo mendadak down tepat setelah order terkirim
        mock_get_balance.side_effect = Exception("CLOB Gateway Error 502: Balance service unavailable")

        config = Config(mode="dry-run", bankroll_fraction=0.02)
        runner = BotRunner(config=config)
        
        print("\n🔥 [CHAOS TEST] Memulai simulasi order sukses namun API saldo hancur...")

        # Eksekusi siklus trading
        try:
            runner.execute_trade_cycle(market_slug="eth-down-5m")
        except Exception as e:
            print(f"⚠️ Bot melempar exception sesuai dugaan: {e}")

        # 3. VERIFIKASI: State internal WAJIB mencatat order ID ini sebagai 'PENDING'
        # Ini mencegah bot buta arah ketika direstart oleh Railway
        state = PersistentState(config.STATE_PATH)
        self.assertTrue(state.has_pending_confirmation("0xchaos123"))
        print("✅ [PASSED] State aman terproteksi. Bot tidak kehilangan rekam jejak posisi aktif.")
