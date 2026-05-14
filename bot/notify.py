import requests

from bot.config import Settings
from bot.logging_setup import log


class Notifier:
    def __init__(self, settings: Settings):
        self.settings = settings

    def heartbeat(self, message: str) -> None:
        if self.settings.healthcheck_url:
            try:
                requests.get(self.settings.healthcheck_url, timeout=3)
            except Exception as exc:
                log(f"[HEARTBEAT ERROR] {exc}")
        if self.settings.telegram_bot_token and self.settings.telegram_chat_id:
            self.telegram(message)

    def telegram(self, message: str) -> None:
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage",
                json={"chat_id": self.settings.telegram_chat_id, "text": message},
                timeout=5,
            )
        except Exception as exc:
            log(f"[TELEGRAM ERROR] {exc}")

