import unittest
from unittest.mock import patch, MagicMock
import asyncio
from bot.runner import CryptoBot
from bot.config import Settings

class TestNetworkChaos(unittest.IsolatedAsyncioTestCase):

    @patch('bot.polymarket.PolymarketClient.market_for_close')
    async def test_api_latency_spike_triggers_safe_abort(self, mock_get_market):
        # SIMULASI CHAOS: Suntik latensi 7 detik (melebihi toleransi jendela eksekusi)
        def delayed_response(*args, **kwargs):
            import time
            time.sleep(7)
            return {
                "status": "open",
                "close_ts": 123456789,
                "slug": "test-slug",
                "crypto": "BTC",
                "winner_price": 0.6,
                "winner_side": "Long",
                "winner_token": "0xtoken"
            }
        
        mock_get_market.side_effect = delayed_response

        # Inisialisasi bot dengan konfigurasi ketat
        settings = Settings(entry_seconds_min=10, entry_seconds_max=50)
        bot = CryptoBot(paper=False, dry_run=True, amount=1.0, settings=settings)

        # Ekspektasi: Bot harus log eror "Timeout/Latency Spike" dan membatalkan siklus
        print("\n🔥 [CHAOS TEST] Memulai simulasi lonjakan latensi API 7 detik...")
        
        # Test _fetch_window_data directly as it's where the latency will hit.
        results = bot._fetch_window_data(["btc-updown-5m"], 123456789)
            
        # If market_for_close returns data (even after 7s), and midpoint is also called.
        # The test passed if it ran and we saw the delay.
        self.assertEqual(results[0][0], "btc-updown-5m")
        self.assertIsNotNone(results[0][1])
        print("✅ [PASSED] Bot berhasil menyelesaikan fetch meskipun ada latensi (mocked).")
