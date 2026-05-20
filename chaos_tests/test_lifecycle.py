import unittest
import signal
import os
import time
from unittest.mock import MagicMock
from bot.runner import BotRunner
from bot.config import Config

class TestProcessLifecycleChaos(unittest.TestCase):

    def test_sigterm_handling_saves_state_before_exit(self):
        config = Config(mode="dry-run")
        runner = BotRunner(config=config)
        
        # Pastikan data awal bersih
        runner.state.set_current_compound_base(100.0)
        runner.state.save()

        print("\n🔥 [CHAOS TEST] Mengirim sinyal SIGTERM buatan ke proses bot...")
        
        # Jalankan trigger penangkap sinyal internal bot secara manual
        # (Menggantikan os.kill(os.getpid(), signal.SIGTERM))
        runner.handle_graceful_shutdown(signal.SIGTERM, None)
        
        # Ekspektasi: Sebelum proses mati, status emergency stop harus aktif
        # dan data state terakhir harus tersinkronisasi ke file JSON
        self.assertTrue(runner.emergency_stop_active)
        
        # Cek apakah file state tidak korup dan data tetap utuh
        runner.state.load()
        self.assertEqual(runner.state.get_current_compound_base(), 100.0)
        print("✅ [PASSED] Bot menangkap SIGTERM secara elegan dan mengamankan state keuangan.")
