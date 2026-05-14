from dataclasses import dataclass

from bot.config import Settings


@dataclass
class RiskDecision:
    allowed: bool
    amount: float = 0.0
    reason: str = "ok"


class RiskManager:
    def __init__(self, settings: Settings):
        self.settings = settings

    def size_trade(self, *, base_amount: float, confidence: float,
                   balance: float | None, daily_loss: float,
                   live_trades_today: int) -> RiskDecision:
        if daily_loss <= -abs(self.settings.max_daily_loss):
            return RiskDecision(False, reason=f"daily loss guard hit: ${daily_loss:.2f}")

        if live_trades_today >= self.settings.max_consecutive_live_trades:
            return RiskDecision(False, reason="live trade count guard hit")

        confidence_factor = max(confidence / self.settings.min_confidence, 0.0)
        if balance is not None:
            if balance < self.settings.min_trade_amount:
                return RiskDecision(False, reason=f"balance ${balance:.2f} below min trade")
            amount = balance * self.settings.bankroll_fraction * confidence_factor
        else:
            amount = base_amount * confidence_factor

        amount = max(self.settings.min_trade_amount, amount)
        amount = min(self.settings.max_trade_amount, amount)

        if balance is not None:
            amount = min(amount, balance)
        if amount < self.settings.min_trade_amount:
            return RiskDecision(False, reason=f"sized amount ${amount:.2f} below min trade")

        return RiskDecision(True, round(amount, 2), "ok")

    def next_compound_base(self, executed_amount: float) -> float:
        return round(max(
            self.settings.min_trade_amount,
            executed_amount * (1 + self.settings.compound_rate),
        ), 2)

