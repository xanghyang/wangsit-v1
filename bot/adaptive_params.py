"""Adaptive parameter system for dynamic bot optimization."""

import json
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from collections import deque

from bot.config import Settings


@dataclass
class AdaptiveParameters:
    """Container for adaptive parameters."""
    delta_skip: float
    delta_weak: float
    delta_strong: float
    min_confidence: float
    atr_multiplier: float
    bankroll_fraction: float
    max_trade_amount: float
    volatility_threshold: float = 0.05
    correlation_threshold: float = 0.7
    performance_window: int = 50
    adaptation_rate: float = 0.1


@dataclass
class PerformanceMetrics:
    """Container for performance tracking."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    avg_holding_time: float
    volatility: float
    timestamp: float


class AdaptiveParameterManager:
    """Manages adaptive parameter optimization based on market conditions and performance."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.current_params = self._initialize_params()
        self.performance_history = deque(maxlen=100)
        self.market_conditions = {}
        self.adaptation_count = 0
        self.last_adaptation = time.time()
        
    def _initialize_params(self) -> AdaptiveParameters:
        """Initialize adaptive parameters from settings."""
        return AdaptiveParameters(
            delta_skip=self.settings.delta_skip,
            delta_weak=self.settings.delta_weak,
            delta_strong=self.settings.delta_strong,
            min_confidence=self.settings.min_confidence,
            atr_multiplier=self.settings.atr_multiplier,
            bankroll_fraction=self.settings.bankroll_fraction,
            max_trade_amount=self.settings.max_trade_amount,
            volatility_threshold=0.05,
            correlation_threshold=0.7,
            performance_window=50,
            adaptation_rate=0.1
        )
    
    def record_trade_outcome(self, trade_data: Dict[str, Any]) -> None:
        """Record trade outcome for performance tracking."""
        metrics = self._calculate_trade_metrics(trade_data)
        self.performance_history.append(metrics)
        self._check_and_adapt()
    
    def record_market_condition(self, crypto: str, condition_data: Dict[str, Any]) -> None:
        """Record market conditions for adaptive analysis."""
        self.market_conditions[crypto] = {
            'timestamp': time.time(),
            'volatility': condition_data.get('volatility', 0),
            'trend_strength': condition_data.get('trend_strength', 0),
            'liquidity': condition_data.get('liquidity', 0),
            'volume': condition_data.get('volume', 0)
        }
    
    def get_adaptive_parameters(self) -> AdaptiveParameters:
        """Get current adaptive parameters."""
        return self.current_params
    
    def _check_and_adapt(self) -> None:
        """Check if adaptation is needed and apply if necessary."""
        if len(self.performance_history) < self.current_params.performance_window:
            return
        
        # Check if enough time has passed since last adaptation
        time_since_adaptation = time.time() - self.last_adaptation
        if time_since_adaptation < 3600:  # Minimum 1 hour between adaptations
            return
        
        # Calculate current performance
        current_performance = self._calculate_overall_performance()
        
        # Check if adaptation threshold is met
        if self._should_adapt(current_performance):
            self._apply_adaptation(current_performance)
            self.last_adaptation = time.time()
            self.adaptation_count += 1
    
    def _calculate_trade_metrics(self, trade_data: Dict[str, Any]) -> PerformanceMetrics:
        """Calculate performance metrics for a single trade."""
        pnl = trade_data.get('pnl_actual', 0)
        holding_time = trade_data.get('holding_time', 300)  # Default 5 minutes
        is_win = pnl > 0
        
        return PerformanceMetrics(
            total_trades=1,
            winning_trades=1 if is_win else 0,
            losing_trades=0 if is_win else 1,
            total_pnl=pnl,
            max_drawdown=abs(pnl) if pnl < 0 else 0,
            sharpe_ratio=pnl / holding_time if holding_time > 0 else 0,
            win_rate=1.0 if is_win else 0.0,
            avg_holding_time=holding_time,
            volatility=abs(pnl),
            timestamp=time.time()
        )
    
    def _calculate_overall_performance(self) -> PerformanceMetrics:
        """Calculate overall performance from recent trades."""
        if not self.performance_history:
            return PerformanceMetrics(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                total_pnl=0,
                max_drawdown=0,
                sharpe_ratio=0,
                win_rate=0,
                avg_holding_time=0,
                volatility=0,
                timestamp=time.time()
            )
        
        total_trades = sum(m.total_trades for m in self.performance_history)
        winning_trades = sum(m.winning_trades for m in self.performance_history)
        losing_trades = sum(m.losing_trades for m in self.performance_history)
        total_pnl = sum(m.total_pnl for m in self.performance_history)
        max_drawdown = max(m.max_drawdown for m in self.performance_history)
        sharpe_ratio = sum(m.sharpe_ratio for m in self.performance_history) / len(self.performance_history)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        avg_holding_time = sum(m.avg_holding_time for m in self.performance_history) / len(self.performance_history)
        volatility = sum(m.volatility for m in self.performance_history) / len(self.performance_history)
        
        return PerformanceMetrics(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            total_pnl=total_pnl,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            win_rate=win_rate,
            avg_holding_time=avg_holding_time,
            volatility=volatility,
            timestamp=time.time()
        )
    
    def _should_adapt(self, performance: PerformanceMetrics) -> bool:
        """Determine if adaptation is needed based on performance."""
        # Adapt if win rate is too low or too high
        if performance.win_rate < 0.3 or performance.win_rate > 0.8:
            return True
        
        # Adapt if drawdown is too high
        if performance.max_drawdown > self.settings.max_daily_loss * 0.5:
            return True
        
        # Adapt if volatility is too high
        if performance.volatility > self.current_params.volatility_threshold:
            return True
        
        # Adapt if performance window is met
        if performance.total_trades >= self.current_params.performance_window:
            return True
        
        return False
    
    def _apply_adaptation(self, performance: PerformanceMetrics) -> None:
        """Apply parameter adaptations based on performance."""
        old_params = self.current_params
        
        # Adapt delta thresholds based on win rate
        if performance.win_rate < 0.3:
            # Too many losses, be more selective
            self.current_params.delta_skip *= (1 + self.current_params.adaptation_rate)
            self.current_params.delta_weak *= (1 + self.current_params.adaptation_rate)
            self.current_params.delta_strong *= (1 + self.current_params.adaptation_rate)
            self.current_params.min_confidence *= (1 + self.current_params.adaptation_rate)
        elif performance.win_rate > 0.8:
            # Too many wins, can be less selective
            self.current_params.delta_skip *= (1 - self.current_params.adaptation_rate * 0.5)
            self.current_params.delta_weak *= (1 - self.current_params.adaptation_rate * 0.5)
            self.current_params.delta_strong *= (1 - self.current_params.adaptation_rate * 0.5)
            self.current_params.min_confidence *= (1 - self.current_params.adaptation_rate * 0.5)
        
        # Adapt bankroll fraction based on volatility
        if performance.volatility > self.current_params.volatility_threshold:
            # High volatility, reduce position size
            self.current_params.bankroll_fraction *= (1 - self.current_params.adaptation_rate)
        else:
            # Low volatility, can increase position size
            self.current_params.bankroll_fraction *= (1 + self.current_params.adaptation_rate * 0.5)
        
        # Adapt ATR multiplier based on drawdown
        if performance.max_drawdown > self.settings.max_daily_loss * 0.3:
            # High drawdown, reduce position size
            self.current_params.atr_multiplier *= (1 - self.current_params.adaptation_rate)
        else:
            # Low drawdown, can be more aggressive
            self.current_params.atr_multiplier *= (1 + self.current_params.adaptation_rate * 0.5)
        
        # Ensure parameters stay within reasonable bounds
        self._enforce_parameter_bounds()
        
        # Log adaptation
        self._log_adaptation(old_params, performance)
    
    def _enforce_parameter_bounds(self) -> None:
        """Ensure parameters stay within reasonable bounds."""
        # Delta thresholds bounds
        self.current_params.delta_skip = max(0.0001, min(0.01, self.current_params.delta_skip))
        self.current_params.delta_weak = max(0.0001, min(0.01, self.current_params.delta_weak))
        self.current_params.delta_strong = max(0.0001, min(0.01, self.current_params.delta_strong))
        
        # Confidence bounds
        self.current_params.min_confidence = max(0.1, min(0.9, self.current_params.min_confidence))
        
        # Bankroll fraction bounds
        self.current_params.bankroll_fraction = max(0.01, min(0.1, self.current_params.bankroll_fraction))
        
        # ATR multiplier bounds
        self.current_params.atr_multiplier = max(0.5, min(3.0, self.current_params.atr_multiplier))
    
    def _log_adaptation(self, old_params: AdaptiveParameters, performance: PerformanceMetrics) -> None:
        """Log parameter adaptation details."""
        print(f"Adaptation #{self.adaptation_count} applied:")
        print(f"Performance - Win Rate: {performance.win_rate:.2%}, PnL: ${performance.total_pnl:.2f}")
        print(f"Delta Skip: {old_params.delta_skip:.4f} -> {self.current_params.delta_skip:.4f}")
        print(f"Bankroll: {old_params.bankroll_fraction:.2%} -> {self.current_params.bankroll_fraction:.2%}")
        print(f"ATR Multiplier: {old_params.atr_multiplier:.2f} -> {self.current_params.atr_multiplier:.2f}")
    
    def get_market_condition_adjustment(self, crypto: str) -> Dict[str, float]:
        """Get parameter adjustments based on current market conditions."""
        if crypto not in self.market_conditions:
            return {}
        
        condition = self.market_conditions[crypto]
        adjustments = {}
        
        # Adjust based on volatility
        if condition['volatility'] > 0.1:  # High volatility
            adjustments['delta_skip'] = 1.2
            adjustments['bankroll_fraction'] = 0.8
        elif condition['volatility'] < 0.02:  # Low volatility
            adjustments['delta_skip'] = 0.9
            adjustments['bankroll_fraction'] = 1.1
        
        # Adjust based on trend strength
        if condition['trend_strength'] > 0.8:  # Strong trend
            adjustments['min_confidence'] = 0.9
        elif condition['trend_strength'] < 0.2:  # Weak trend
            adjustments['min_confidence'] = 1.1
        
        # Adjust based on liquidity
        if condition['liquidity'] < 1000:  # Low liquidity
            adjustments['max_trade_amount'] = 0.7
        elif condition['liquidity'] > 10000:  # High liquidity
            adjustments['max_trade_amount'] = 1.2
        
        return adjustments
    
    def save_parameters(self, filepath: str) -> None:
        """Save current parameters to file."""
        params_data = {
            'parameters': asdict(self.current_params),
            'adaptation_count': self.adaptation_count,
            'last_adaptation': self.last_adaptation,
            'timestamp': time.time()
        }
        
        with open(filepath, 'w') as f:
            json.dump(params_data, f, indent=2)
    
    def load_parameters(self, filepath: str) -> None:
        """Load parameters from file."""
        try:
            with open(filepath, 'r') as f:
                params_data = json.load(f)
            
            self.current_params = AdaptiveParameters(**params_data['parameters'])
            self.adaptation_count = params_data.get('adaptation_count', 0)
            self.last_adaptation = params_data.get('last_adaptation', time.time())
        except FileNotFoundError:
            print(f"Parameter file {filepath} not found, using defaults")
        except Exception as e:
            print(f"Error loading parameters: {e}")