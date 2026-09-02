from dataclasses import dataclass

from bot.binance import BinanceClient
from bot.config import Settings
from bot.multi_timeframe import MultiTimeframeAnalyzer


@dataclass
class Signal:
    confidence: float
    direction: str | None
    reason: str
    score: int = 0
    window_open: float = 0.0
    current_price: float = 0.0
    delta_pct: float = 0.0
    delta_weight: int = 0
    momentum: str = "no data"
    atr: float = 0.0
    current_range: float = 0.0
    multi_tf_enabled: bool = False
    multi_tf_conflict: bool = False

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class SignalEngine:
    def __init__(self, settings: Settings, binance: BinanceClient):
        self.settings = settings
        self.binance = binance
        self.mtf_analyzer = MultiTimeframeAnalyzer(settings, binance)

    def analyze(self, symbol: str, window_ts: int, use_multi_tf: bool = True) -> Signal:
        if use_multi_tf:
            return self._analyze_multi_tf(symbol, window_ts)
        return self._analyze_single_tf(symbol, window_ts)

    def _analyze_multi_tf(self, symbol: str, window_ts: int) -> Signal:
        mtf_result = self.mtf_analyzer.analyze_all(symbol, window_ts)

        if not mtf_result.consensus_direction:
            current_price = self.binance.price(symbol)
            return Signal(
                confidence=0,
                direction=None,
                reason=f"Multi-TF no consensus: {mtf_result.reason}",
                current_price=current_price if current_price > 0 else 0,
                multi_tf_enabled=True,
                multi_tf_conflict=mtf_result.conflict_detected,
            )

        confidence = mtf_result.consensus_confidence
        if mtf_result.conflict_detected:
            confidence *= 0.7

        if confidence < self.settings.min_confidence:
            return Signal(
                confidence=confidence,
                direction=mtf_result.consensus_direction,
                reason=f"Multi-TF low confidence: {mtf_result.reason}",
                score=mtf_result.final_score,
                multi_tf_enabled=True,
                multi_tf_conflict=mtf_result.conflict_detected,
            )

        primary_tf = mtf_result.tf_signals[0] if mtf_result.tf_signals else None

        return Signal(
            score=mtf_result.final_score,
            confidence=confidence,
            direction=mtf_result.consensus_direction,
            window_open=primary_tf.window_open if primary_tf else 0,
            current_price=primary_tf.price if primary_tf else 0,
            delta_pct=primary_tf.delta_pct if primary_tf else 0,
            delta_weight=abs(mtf_result.final_score),
            momentum=primary_tf.momentum if primary_tf else "no data",
            atr=primary_tf.atr if primary_tf else 0,
            reason=mtf_result.reason,
            multi_tf_enabled=True,
            multi_tf_conflict=mtf_result.conflict_detected,
        )

    def _analyze_single_tf(self, symbol: str, window_ts: int) -> Signal:
        current_price = self.binance.price(symbol)
        if current_price <= 0:
            return Signal(confidence=0, direction=None, reason="no Binance price")

        window_open = self.binance.window_open_price(symbol, window_ts)
        if window_open <= 0:
            candles = self.binance.candles(symbol, "1m", 6)
            if not candles or not isinstance(candles, list) or len(candles) == 0 or len(candles[0]) < 2:
                return Signal(confidence=0, direction=None, reason="no open price")
            try:
                window_open = float(candles[0][1])
            except (ValueError, TypeError, IndexError):
                return Signal(confidence=0, direction=None, reason="invalid open price data")

        delta = (current_price - window_open) / window_open
        delta_pct = abs(delta) * 100
        delta_dir = "Up" if delta > 0 else "Down"

        atr = self.binance.atr(symbol, window_ts, self.settings.atr_periods)
        if atr > 0:
            current_candle = self.binance.candles(symbol, "5m", 1)
            if current_candle and isinstance(current_candle, list) and len(current_candle) > 0 and len(current_candle[0]) >= 4:
                try:
                    current_range = float(current_candle[0][2]) - float(current_candle[0][3])
                    if current_range > atr * self.settings.atr_multiplier:
                        return Signal(
                            confidence=0,
                            direction=None,
                            window_open=window_open,
                            current_price=current_price,
                            delta_pct=delta_pct,
                            atr=atr,
                            current_range=current_range,
                            reason=f"ATR skip: range ${current_range:.2f} > {self.settings.atr_multiplier}x ATR ${atr:.2f}",
                        )
                except (ValueError, TypeError, IndexError):
                    pass

        if abs(delta) < self.settings.delta_skip:
            return Signal(
                confidence=0,
                direction=None,
                window_open=window_open,
                current_price=current_price,
                delta_pct=delta_pct,
                atr=atr,
                reason=f"delta {delta_pct:.4f}% < {self.settings.delta_skip * 100:.3f}% - too close to line",
            )

        delta_weight = self._delta_weight(abs(delta))
        score = delta_weight if delta > 0 else -delta_weight
        momentum_str = "no data"

        candles = self.binance.candles(symbol, "1m", 3)
        if isinstance(candles, list) and len(candles) >= 2 and len(candles[-2]) >= 5 and len(candles[-1]) >= 5:
            try:
                prev_close = float(candles[-2][4])
                last_close = float(candles[-1][4])
                momentum_up = last_close > prev_close
                if (delta > 0 and momentum_up) or (delta < 0 and not momentum_up):
                    score += 2 if score > 0 else -2
                    momentum_str = f"{'up' if momentum_up else 'down'} {last_close:.2f} (confirms)"
                else:
                    momentum_str = f"{'up' if momentum_up else 'down'} {last_close:.2f} (contradicts, ignored)"
            except (ValueError, TypeError, IndexError):
                pass

        confidence = min(abs(score) / 9.0, 1.0)
        direction = "Up" if score > 0 else "Down"

        return Signal(
            score=score,
            confidence=confidence,
            direction=direction,
            window_open=window_open,
            current_price=current_price,
            delta_pct=delta_pct,
            delta_weight=delta_weight,
            momentum=momentum_str,
            atr=atr,
            reason=f"delta={delta_pct:.4f}% ({delta_dir}, w={delta_weight}) momentum={momentum_str}",
        )

    def _delta_weight(self, abs_delta: float) -> int:
        if abs_delta >= self.settings.delta_strong * 5:
            return 7
        if abs_delta >= self.settings.delta_strong:
            return 5
        if abs_delta >= self.settings.delta_weak:
            return 3
        return 1

