from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from bot.binance import BinanceClient
from bot.config import Settings


@dataclass
class TFSignal:
    timeframe: str
    direction: str | None
    delta_pct: float
    confidence: float
    momentum: str
    atr: float
    price: float
    window_open: float
    strength: int


@dataclass
class MultiTFResult:
    consensus_direction: str | None
    consensus_confidence: float
    tf_signals: List[TFSignal]
    conflict_detected: bool
    reason: str
    final_score: int


class MultiTimeframeAnalyzer:
    SUPPORTED_TF = ["1m", "5m", "15m", "1h"]

    def __init__(self, settings: Settings, binance: BinanceClient):
        self.settings = settings
        self.binance = binance

    def analyze_all(self, symbol: str, window_ts: int) -> MultiTFResult:
        tf_signals = []

        for tf in self.SUPPORTED_TF:
            signal = self._analyze_tf(symbol, window_ts, tf)
            if signal:
                tf_signals.append(signal)

        if not tf_signals:
            return MultiTFResult(
                consensus_direction=None,
                consensus_confidence=0.0,
                tf_signals=[],
                conflict_detected=False,
                reason="No TF data available",
                final_score=0
            )

        return self._consolidate_signals(tf_signals)

    def _analyze_tf(self, symbol: str, window_ts: int, tf: str) -> Optional[TFSignal]:
        try:
            current_price = self.binance.price(symbol)
            if current_price <= 0:
                return None

            window_open = self._get_window_open(symbol, window_ts, tf)
            if window_open <= 0:
                return None

            delta = (current_price - window_open) / window_open
            delta_pct = abs(delta) * 100

            if delta_pct < self.settings.delta_skip:
                return None

            atr = self.binance.atr(symbol, window_ts, self.settings.atr_periods)
            if atr > 0:
                candles = self.binance.candles(symbol, tf, 1)
                if candles and isinstance(candles, list) and len(candles) > 0 and len(candles[0]) >= 4:
                    high = float(candles[0][2])
                    low = float(candles[0][3])
                    current_range = high - low
                    if current_range > atr * self.settings.atr_multiplier:
                        return None

            delta_dir = "Up" if delta > 0 else "Down"
            delta_weight = self._delta_weight(abs(delta))

            momentum = self._get_momentum(symbol, tf)

            direction = delta_dir
            confidence = min(abs(delta_weight) / 7.0, 1.0)
            strength = delta_weight if delta > 0 else -delta_weight

            return TFSignal(
                timeframe=tf,
                direction=direction,
                delta_pct=delta_pct,
                confidence=confidence,
                momentum=momentum,
                atr=atr,
                price=current_price,
                window_open=window_open,
                strength=strength
            )

        except Exception:
            return None

    def _get_window_open(self, symbol: str, window_ts: int, tf: str) -> float:
        if tf == "1m":
            candles = self.binance.candles(symbol, "1m", 6)
        elif tf == "5m":
            candles = self.binance.candles(symbol, "5m", 6)
        elif tf == "15m":
            candles = self.binance.candles(symbol, "15m", 4)
        elif tf == "1h":
            candles = self.binance.candles(symbol, "1h", 4)
        else:
            candles = None

        if candles and isinstance(candles, list) and len(candles) > 0 and len(candles[0]) >= 2:
            try:
                return float(candles[0][1])
            except (ValueError, TypeError, IndexError):
                return 0.0
        return 0.0

    def _get_momentum(self, symbol: str, tf: str) -> str:
        candles = self.binance.candles(symbol, tf, 3)
        if isinstance(candles, list) and len(candles) >= 2 and len(candles[-2]) >= 5 and len(candles[-1]) >= 5:
            try:
                prev_close = float(candles[-2][4])
                last_close = float(candles[-1][4])
                momentum_up = last_close > prev_close
                return f"{'up' if momentum_up else 'down'} {last_close}"
            except (ValueError, TypeError, IndexError):
                return "no data"
        return "no data"

    def _delta_weight(self, abs_delta: float) -> int:
        if abs_delta >= self.settings.delta_strong * 5:
            return 7
        if abs_delta >= self.settings.delta_strong:
            return 5
        if abs_delta >= self.settings.delta_weak:
            return 3
        return 1

    def _consolidate_signals(self, tf_signals: List[TFSignal]) -> MultiTFResult:
        up_count = sum(1 for s in tf_signals if s.direction == "Up")
        down_count = sum(1 for s in tf_signals if s.direction == "Down")
        total = len(tf_signals)

        if up_count > down_count and up_count >= 2:
            consensus_direction = "Up"
            avg_confidence = sum(s.confidence for s in tf_signals if s.direction == "Up") / up_count
            total_score = sum(s.strength for s in tf_signals if s.direction == "Up")
            reason = f"Multi-TF bullish: {up_count}/{total} TFs agree (Up)"
            conflict = down_count > 0
        elif down_count > up_count and down_count >= 2:
            consensus_direction = "Down"
            avg_confidence = sum(s.confidence for s in tf_signals if s.direction == "Down") / down_count
            total_score = sum(s.strength for s in tf_signals if s.direction == "Down")
            reason = f"Multi-TF bearish: {down_count}/{total} TFs agree (Down)"
            conflict = up_count > 0
        elif up_count == down_count and total >= 2:
            higher_tf = self._get_higher_tf_signal(tf_signals)
            if higher_tf:
                return MultiTFResult(
                    consensus_direction=higher_tf.direction,
                    consensus_confidence=higher_tf.confidence * 0.8,
                    tf_signals=tf_signals,
                    conflict_detected=True,
                    reason=f"Conflict resolved by {higher_tf.timeframe}: {higher_tf.direction}",
                    final_score=higher_tf.strength
                )
            consensus_direction = None
            avg_confidence = 0.0
            total_score = 0
            reason = f"Multi-TF conflict: {up_count} Up vs {down_count} Down"
            conflict = True
        else:
            consensus_direction = None
            avg_confidence = 0.0
            total_score = 0
            reason = f"Insufficient TF agreement: {up_count} Up, {down_count} Down"
            conflict = up_count > 0 and down_count > 0

        return MultiTFResult(
            consensus_direction=consensus_direction,
            consensus_confidence=avg_confidence,
            tf_signals=tf_signals,
            conflict_detected=conflict,
            reason=reason,
            final_score=total_score
        )

    def _get_higher_tf_signal(self, tf_signals: List[TFSignal]) -> Optional[TFSignal]:
        priority = {"1h": 4, "15m": 3, "5m": 2, "1m": 1}
        best = None
        best_priority = 0

        for signal in tf_signals:
            p = priority.get(signal.timeframe, 0)
            if p > best_priority:
                best_priority = p
                best = signal

        return best