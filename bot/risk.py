from dataclasses import dataclass
from typing import Dict, Optional
import numpy as np

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
                   live_trades_today: int,
                   current_drawdown: float = 0.0) -> RiskDecision:
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

        if current_drawdown < 0:
            amount = self.get_max_drawdown_protection(amount, current_drawdown, max_drawdown_threshold=0.15)

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
    
    def get_volatility_adjusted_amount(self, base_amount: float, atr: float, 
                                     atr_multiplier: float = 1.5) -> float:
        """Calculate volatility-adjusted trade amount based on ATR."""
        if atr <= 0:
            return base_amount
        
        # Adjust position size based on volatility
        # Higher volatility = smaller position
        volatility_factor = min(atr_multiplier / atr, 2.0)
        
        adjusted_amount = base_amount / volatility_factor
        
        # Ensure amount stays within bounds
        adjusted_amount = max(self.settings.min_trade_amount, adjusted_amount)
        adjusted_amount = min(self.settings.max_trade_amount, adjusted_amount)
        
        return round(adjusted_amount, 2)
    
    def get_correlation_adjusted_amount(self, base_amount: float, 
                                      correlation_matrix: Dict[str, float],
                                      current_crypto: str) -> float:
        """Adjust trade amount based on correlation with other assets."""
        if not correlation_matrix or current_crypto not in correlation_matrix:
            return base_amount
        
        # Get correlation with other assets
        correlation = correlation_matrix.get(current_crypto, 0)
        
        # If highly correlated with losing positions, reduce size
        if correlation > 0.7:
            adjustment_factor = 0.7  # Reduce by 30%
        elif correlation < -0.7:
            adjustment_factor = 1.2  # Increase by 20% (diversification)
        else:
            adjustment_factor = 1.0
        
        adjusted_amount = base_amount * adjustment_factor
        
        # Ensure amount stays within bounds
        adjusted_amount = max(self.settings.min_trade_amount, adjusted_amount)
        adjusted_amount = min(self.settings.max_trade_amount, adjusted_amount)
        
        return round(adjusted_amount, 2)
    
    def get_max_drawdown_protection(self, base_amount: float, 
                                   current_drawdown: float,
                                   max_drawdown_threshold: float = 0.15) -> float:
        """Apply max drawdown protection to trade sizing."""
        if current_drawdown <= 0:
            return base_amount
        
        # Calculate drawdown percentage
        drawdown_pct = abs(current_drawdown) / base_amount
        
        if drawdown_pct >= max_drawdown_threshold:
            # Reduce position size significantly
            reduction_factor = 0.3  # Only 30% of normal size
        elif drawdown_pct >= max_drawdown_threshold * 0.7:
            # Moderate reduction
            reduction_factor = 0.7  # 70% of normal size
        elif drawdown_pct >= max_drawdown_threshold * 0.4:
            # Small reduction
            reduction_factor = 0.9  # 90% of normal size
        else:
            reduction_factor = 1.0  # Full size
        
        protected_amount = base_amount * reduction_factor
        
        # Ensure amount stays within bounds
        protected_amount = max(self.settings.min_trade_amount, protected_amount)
        protected_amount = min(self.settings.max_trade_amount, protected_amount)
        
        return round(protected_amount, 2)