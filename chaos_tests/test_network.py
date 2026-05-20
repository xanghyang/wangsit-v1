import unittest
from unittest.mock import patch, MagicMock
import asyncio
from bot.runner import BotRunner
from bot.config import Config

class TestNetworkChaos(unittest.IsolatedAsyncioTestCase):

    @patch('bot.polymarket.PolymarketGammaClient.get_market_data')
    async def test_api_latency_spike_triggers_safe_abort(self, mock_get_market):
        # SIMULASI CHAOS: Suntik latensi 7 detik (melebihi toleransi jendela eksekusi)
        async def delayed_response(*args, **kwargs):
            await asyncio.sleep(7)
            return {"status": "open", "close_time": 123456789}
        
        mock_get_market.side_effect = delayed_response

        # Inisialisasi bot dengan konfigurasi ketat
        config = Config(mode="dry-run", ENTRY_SECONDS_MIN=10, ENTRY_SECONDS_MAX=50)
        runner = BotRunner(config=config)

        # Ekspektasi: Bot harus log eror "Timeout/Latency Spike" dan membatalkan siklus
        print("\n🔥 [CHAOS TEST] Memulai simulasi lonjakan latensi API 7 detik...")
        
        # Logika runner harus menangkap timeout dan tidak memaksa masuk pasar
        with self.assertLogs('bot', level='ERROR') as log_capture:
            await runner.tick_market_cycle("btc-up-5m")
            
        self.assertTrue(any("Timeout" in log or "Late entry avoidance" in log for log in log_capture.output))
        print("✅ [PASSED] Bot berhasil menggagalkan order karena mendeteksi latensi berbahaya.")
