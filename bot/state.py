import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


def today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class BotState:
    traded_slugs: set[str] = field(default_factory=set)
    trades: list[dict] = field(default_factory=list)
    compound_base: float = 0.99
    daily_loss: float = 0.0
    live_trades_today: int = 0
    day: str = field(default_factory=today_key)
    heartbeat_cycles: int = 0

    @classmethod
    def load(cls, path: str, default_base: float) -> "BotState":
        if not os.path.exists(path):
            return cls(compound_base=default_base)
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        state = cls(
            traded_slugs=set(raw.get("traded_slugs", [])),
            trades=raw.get("trades", []),
            compound_base=float(raw.get("compound_base", default_base)),
            daily_loss=float(raw.get("daily_loss", 0.0)),
            live_trades_today=int(raw.get("live_trades_today", 0)),
            day=raw.get("day", today_key()),
            heartbeat_cycles=int(raw.get("heartbeat_cycles", 0)),
        )
        state.reset_daily_if_needed()
        return state

    def reset_daily_if_needed(self) -> None:
        current = today_key()
        if self.day != current:
            self.day = current
            self.daily_loss = 0.0
            self.live_trades_today = 0

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # Issue 3.B Fix: Bound in-memory list to prevent RAM leak
        if len(self.trades) > 500:
            self.trades = self.trades[-500:]
        payload = {
            "traded_slugs": sorted(self.traded_slugs),
            "trades": self.trades,
            "compound_base": self.compound_base,
            "daily_loss": self.daily_loss,
            "live_trades_today": self.live_trades_today,
            "day": self.day,
            "heartbeat_cycles": self.heartbeat_cycles,
        }
        tmp_path = f"{path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

