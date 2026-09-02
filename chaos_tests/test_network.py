import unittest
from unittest.mock import patch, MagicMock
import asyncio
from bot.runner import CryptoBot
from bot.config import Settings
from bot.signal import Signal

class TestNetworkChaos(unittest.TestCase):

    @patch('bot.polymarket.PolymarketClient.market_for_close')
    def test_api_latency_spike_triggers_safe_abort(self, mock_market_for_close):
        # SIMULASI CHAOS: Return None (simulasi API timeout/failure saat polling)
        mock_market_for_close.return_value = None

        settings = Settings(entry_seconds_min=10, entry_seconds_max=50)
        bot = CryptoBot(paper=True, dry_run=True, amount=0.99, settings=settings)

        print("\n🔥 [CHAOS TEST] Memulai simulasi lonjakan latensi / kegagalan API...")

        # Evaluasi entry saat market bernilai None harus melempar penanganan aman
        results = bot._fetch_window_data(["btc-updown-5m"], close_ts=1700000000)
        
        # Pastikan tidak crash dan mengembalikan data aman (None)
        self.assertEqual(len(results), 1)
        prefix, market, signal = results[0]
        self.assertEqual(prefix, "btc-updown-5m")
        self.assertIsNone(market)
        self.assertIsNone(signal)
        print("✅ [PASSED] Bot berhasil membatalkan evaluasi order secara aman saat terjadi kegagalan API.")
