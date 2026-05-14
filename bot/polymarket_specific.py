"""Polymarket-specific features for enhanced trading."""

import json
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

from bot.config import Settings
from bot.polymarket import PolymarketClient


@dataclass
class LiquidityData:
    slug: str
    market_id: str
    total_liquidity: float
    buy_liquidity: float
    sell_liquidity: float
    liquidity_score: float
    timestamp: float


@dataclass
class PredictionHistory:
    slug: str
    market_id: str
    historical_accuracy: float
    recent_performance: List[Dict[str, Any]]
    prediction_bias: str
    confidence_boost: float


@dataclass
class MarketSentiment:
    slug: str
    market_id: str
    bullish_percentage: float
    bearish_percentage: float
    sentiment_score: float
    volume_trend: str
    timestamp: float


class PolymarketAnalyzer:
    def __init__(self, settings: Settings, polymarket_client: PolymarketClient):
        self.settings = settings
        self.polymarket = polymarket_client
        self.liquidity_cache = {}
        self.prediction_cache = {}
        self.sentiment_cache = {}
        
    def analyze_liquidity(self, market: Dict[str, Any]) -> LiquidityData:
        """Analyze liquidity conditions for a Polymarket."""
        slug = market.get('slug', '')
        market_id = market.get('id', '')
        
        try:
            # Get market liquidity data
            liquidity_info = self.polymarket.get_market_liquidity(market_id)
            
            if not liquidity_info:
                return LiquidityData(
                    slug=slug,
                    market_id=market_id,
                    total_liquidity=0,
                    buy_liquidity=0,
                    sell_liquidity=0,
                    liquidity_score=0,
                    timestamp=time.time()
                )
            
            total_liquidity = float(liquidity_info.get('total_liquidity', 0))
            buy_liquidity = float(liquidity_info.get('buy_liquidity', 0))
            sell_liquidity = float(liquidity_info.get('sell_liquidity', 0))
            
            # Calculate liquidity score (0-1)
            liquidity_score = self._calculate_liquidity_score(
                total_liquidity, buy_liquidity, sell_liquidity
            )
            
            return LiquidityData(
                slug=slug,
                market_id=market_id,
                total_liquidity=total_liquidity,
                buy_liquidity=buy_liquidity,
                sell_liquidity=sell_liquidity,
                liquidity_score=liquidity_score,
                timestamp=time.time()
            )
            
        except Exception as e:
            # Return default data on error
            return LiquidityData(
                slug=slug,
                market_id=market_id,
                total_liquidity=0,
                buy_liquidity=0,
                sell_liquidity=0,
                liquidity_score=0,
                timestamp=time.time()
            )
    
    def analyze_prediction_history(self, market: Dict[str, Any]) -> PredictionHistory:
        """Analyze historical prediction accuracy for a market."""
        slug = market.get('slug', '')
        market_id = market.get('id', '')
        
        try:
            # Get historical data
            history = self.polymarket.get_market_history(market_id)
            
            if not history:
                return PredictionHistory(
                    slug=slug,
                    market_id=market_id,
                    historical_accuracy=0.5,
                    recent_performance=[],
                    prediction_bias="neutral",
                    confidence_boost=1.0
                )
            
            # Calculate historical accuracy
            historical_accuracy = self._calculate_historical_accuracy(history)
            
            # Analyze recent performance
            recent_performance = self._analyze_recent_performance(history)
            
            # Determine prediction bias
            prediction_bias = self._determine_prediction_bias(history)
            
            # Calculate confidence boost
            confidence_boost = self._calculate_confidence_boost(historical_accuracy, recent_performance)
            
            return PredictionHistory(
                slug=slug,
                market_id=market_id,
                historical_accuracy=historical_accuracy,
                recent_performance=recent_performance,
                prediction_bias=prediction_bias,
                confidence_boost=confidence_boost
            )
            
        except Exception as e:
            # Return default data on error
            return PredictionHistory(
                slug=slug,
                market_id=market_id,
                historical_accuracy=0.5,
                recent_performance=[],
                prediction_bias="neutral",
                confidence_boost=1.0
            )
    
    def analyze_market_sentiment(self, market: Dict[str, Any]) -> MarketSentiment:
        """Analyze market sentiment for a prediction market."""
        slug = market.get('slug', '')
        market_id = market.get('id', '')
        
        try:
            # Get market positions
            positions = self.polymarket.get_market_positions(market_id)
            
            if not positions:
                return MarketSentiment(
                    slug=slug,
                    market_id=market_id,
                    bullish_percentage=50.0,
                    bearish_percentage=50.0,
                    sentiment_score=0.0,
                    volume_trend="neutral",
                    timestamp=time.time()
                )
            
            # Calculate sentiment percentages
            bullish_count = sum(1 for pos in positions if pos.get('side') == 'YES')
            bearish_count = sum(1 for pos in positions if pos.get('side') == 'NO')
            total_count = len(positions)
            
            bullish_percentage = (bullish_count / total_count) * 100 if total_count > 0 else 50.0
            bearish_percentage = (bearish_count / total_count) * 100 if total_count > 0 else 50.0
            
            # Calculate sentiment score (-1 to 1)
            sentiment_score = (bullish_percentage - bearish_percentage) / 100
            
            # Determine volume trend
            volume_trend = self._determine_volume_trend(positions)
            
            return MarketSentiment(
                slug=slug,
                market_id=market_id,
                bullish_percentage=bullish_percentage,
                bearish_percentage=bearish_percentage,
                sentiment_score=sentiment_score,
                volume_trend=volume_trend,
                timestamp=time.time()
            )
            
        except Exception as e:
            # Return default data on error
            return MarketSentiment(
                slug=slug,
                market_id=market_id,
                bullish_percentage=50.0,
                bearish_percentage=50.0,
                sentiment_score=0.0,
                volume_trend="neutral",
                timestamp=time.time()
            )
    
    def get_market_quality_score(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate overall market quality score."""
        liquidity_data = self.analyze_liquidity(market)
        prediction_data = self.analyze_prediction_history(market)
        sentiment_data = self.analyze_market_sentiment(market)
        
        # Calculate weighted quality score
        liquidity_weight = 0.4
        prediction_weight = 0.3
        sentiment_weight = 0.3
        
        quality_score = (
            liquidity_data.liquidity_score * liquidity_weight +
            prediction_data.historical_accuracy * prediction_weight +
            abs(sentiment_data.sentiment_score) * sentiment_weight
        )
        
        return {
            'market_id': market.get('id'),
            'slug': market.get('slug'),
            'quality_score': quality_score,
            'liquidity_score': liquidity_data.liquidity_score,
            'prediction_accuracy': prediction_data.historical_accuracy,
            'sentiment_strength': abs(sentiment_data.sentiment_score),
            'liquidity_data': asdict(liquidity_data),
            'prediction_data': asdict(prediction_data),
            'sentiment_data': asdict(sentiment_data)
        }
    
    def should_trade_market(self, market: Dict[str, Any], confidence_threshold: float = 0.7) -> Dict[str, Any]:
        """Determine if a market should be traded based on quality metrics."""
        quality = self.get_market_quality_score(market)
        
        # Check if market meets quality thresholds
        liquidity_ok = quality['liquidity_score'] >= 0.6
        prediction_ok = quality['prediction_accuracy'] >= 0.6
        sentiment_ok = quality['sentiment_strength'] >= 0.3
        
        overall_quality = quality['quality_score']
        
        recommendation = "trade" if overall_quality >= confidence_threshold else "skip"
        
        return {
            'market_id': market.get('id'),
            'slug': market.get('slug'),
            'recommendation': recommendation,
            'quality_score': overall_quality,
            'liquidity_ok': liquidity_ok,
            'prediction_ok': prediction_ok,
            'sentiment_ok': sentiment_ok,
            'breakdown': quality
        }
    
    def _calculate_liquidity_score(self, total_liquidity: float, buy_liquidity: float, sell_liquidity: float) -> float:
        """Calculate liquidity score from 0 to 1."""
        if total_liquidity == 0:
            return 0.0
        
        # Balance score (equal buy/sell liquidity is better)
        balance_ratio = min(buy_liquidity, sell_liquidity) / max(buy_liquidity, sell_liquidity, 1)
        balance_score = min(balance_ratio, 1.0)
        
        # Volume score (more liquidity is better)
        volume_score = min(total_liquidity / 1000, 1.0)  # Normalize to 1000 as baseline
        
        # Combined score
        liquidity_score = (balance_score * 0.6 + volume_score * 0.4)
        
        return min(liquidity_score, 1.0)
    
    def _calculate_historical_accuracy(self, history: List[Dict[str, Any]]) -> float:
        """Calculate historical prediction accuracy."""
        if not history:
            return 0.5
        
        correct_predictions = 0
        total_predictions = 0
        
        for record in history:
            if record.get('resolved') and record.get('outcome_predicted'):
                total_predictions += 1
                if record.get('actual_outcome') == record.get('outcome_predicted'):
                    correct_predictions += 1
        
        if total_predictions == 0:
            return 0.5
        
        return correct_predictions / total_predictions
    
    def _analyze_recent_performance(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Analyze recent prediction performance."""
        recent = history[-10:] if len(history) > 10 else history
        
        performance = []
        for record in recent:
            if record.get('resolved'):
                performance.append({
                    'predicted': record.get('outcome_predicted'),
                    'actual': record.get('actual_outcome'),
                    'correct': record.get('actual_outcome') == record.get('outcome_predicted'),
                    'timestamp': record.get('timestamp')
                })
        
        return performance
    
    def _determine_prediction_bias(self, history: List[Dict[str, Any]]) -> str:
        """Determine if market has prediction bias."""
        if not history:
            return "neutral"
        
        correct_count = sum(1 for record in history if record.get('resolved') and record.get('outcome_predicted'))
        total_count = sum(1 for record in history if record.get('resolved'))
        
        if total_count == 0:
            return "neutral"
        
        accuracy = correct_count / total_count
        
        if accuracy > 0.6:
            return "reliable"
        elif accuracy < 0.4:
            return "unreliable"
        else:
            return "neutral"
    
    def _calculate_confidence_boost(self, historical_accuracy: float, recent_performance: List[Dict[str, Any]]) -> float:
        """Calculate confidence boost factor based on historical accuracy."""
        # Base confidence from historical accuracy
        base_confidence = historical_accuracy
        
        # Recent performance adjustment
        if recent_performance:
            recent_correct = sum(1 for perf in recent_performance if perf['correct'])
            recent_accuracy = recent_correct / len(recent_performance)
            
            # Weighted average
            confidence_boost = (base_confidence * 0.7 + recent_accuracy * 0.3)
        else:
            confidence_boost = base_confidence
        
        return max(0.5, min(1.5, confidence_boost))  # Clamp between 0.5 and 1.5
    
    def _determine_volume_trend(self, positions: List[Dict[str, Any]]) -> str:
        """Determine volume trend from recent positions."""
        if not positions:
            return "neutral"
        
        # Sort by timestamp
        sorted_positions = sorted(positions, key=lambda x: x.get('timestamp', 0))
        recent_positions = sorted_positions[-20:] if len(sorted_positions) > 20 else sorted_positions
        
        # Calculate volume trend
        if len(recent_positions) < 2:
            return "neutral"
        
        # Simple trend analysis (could be enhanced with more sophisticated analysis)
        volume_change = 0
        for i in range(1, len(recent_positions)):
            current_volume = recent_positions[i].get('amount', 0)
            prev_volume = recent_positions[i-1].get('amount', 0)
            volume_change += current_volume - prev_volume
        
        if volume_change > 0:
            return "increasing"
        elif volume_change < 0:
            return "decreasing"
        else:
            return "neutral"