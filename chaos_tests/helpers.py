import os
import json
import signal
import asyncio
from typing import Any, Callable

class ChaosHelpers:
    """Helper utilities untuk memicu kondisi kacau (chaos) di lingkungan lokal."""

    @staticmethod
    def corrupt_state_file(state_path: str) -> None:
        """Menulis teks acak (garbage) ke file state untuk mensimulasikan kerusakan disk/file."""
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            f.write("{ INVALID_JSON_CHAOS_TEST ... !!! ---")
        print(f"💥 [CHAOS HELPER] File state di '{state_path}' berhasil dirusak.")

    @staticmethod
    def inject_stale_state(state_path: str, custom_data: dict) -> None:
        """Menyuntikkan data kedaluwarsa atau tidak valid secara langsung ke file state."""
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(custom_data, f)
        print(f"⚠️ [CHAOS HELPER] State palsu/stale berhasil disuntikkan ke '{state_path}'.")

    @staticmethod
    def mock_latency_decorator(seconds: float) -> Callable:
        """Decorator untuk menyuntikkan latensi jaringan secara dinamis pada fungsi async."""
        def decorator(func: Callable):
            async def wrapper(*args, **kwargs):
                print(f"⏳ [CHAOS JARINGAN] Menyuntikkan delay {seconds} detik pada {func.__name__}...")
                await asyncio.sleep(seconds)
                return await func(*args, **kwargs)
            return wrapper
        return decorator

    @staticmethod
    def trigger_self_sigterm() -> None:
        """Mengirim sinyal SIGTERM ke proses saat ini secara asinkron."""
        pid = os.getpid()
        print(f"💀 [CHAOS PROCESS] Mengirim SIGTERM ke diri sendiri (PID: {pid})...")
        os.kill(pid, signal.SIGTERM)

    @staticmethod
    def clean_chaos_env(state_path: str) -> None:
        """Membersihkan sisa-sisa file pengujian chaos agar tidak mengganggu sistem asli."""
        if os.path.exists(state_path):
            try:
                os.remove(state_path)
                print(f"🧹 [CLEANUP] File dummy chaos '{state_path}' berhasil dihapus.")
            except Exception as e:
                print(f"❌ [CLEANUP] Gagal menghapus file dummy: {e}")
