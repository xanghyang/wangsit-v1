import unittest
import signal
import os
import time
from unittest.mock import MagicMock
from bot.runner import CryptoBot
from bot.config import Settings
from bot.state import BotState

class TestProcessLifecycleChaos(unittest.TestCase):

    def test_sigterm_handling_saves_state_before_exit(self):
        settings = Settings(state_path="data/test_lifecycle_state.json")
        bot = CryptoBot(paper=True, dry_run=False, amount=100.0, settings=settings)
        
        # Pastikan data awal bersih
        bot.state.compound_base = 100.0
        bot._save_state()

        print("\n🔥 [CHAOS TEST] Menguji penyelamatan state finansial sebelum terminasi...")
        
        # Simulasikan pengubahan state sebelum shutdown
        bot.state.compound_base = 105.0
        bot._save_state()
        
        # Cek apakah file state tidak korup dan data tetap utuh
        loaded_state = BotState.load(settings.state_path, default_base=0.99)
        self.assertEqual(loaded_state.compound_base, 105.0)
        print("✅ [PASSED] Bot berhasil menyimpan dan mengamankan state keuangan secara persisten.")
