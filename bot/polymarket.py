import json

from bot.config import Settings
from bot.http import HttpClient


class PolymarketClient:
    def __init__(self, settings: Settings, http: HttpClient | None = None):
        self.settings = settings
        self.http = http or HttpClient(retries=1)

    def market_for_close(self, slug_prefix: str, close_ts: int) -> dict | None:
        start_ts = close_ts - 300
        slug = f"{slug_prefix}-{start_ts}"
        try:
            data = self.http.get_json(
                f"{self.settings.gamma_api}/events",
                params={"slug": slug},
                timeout=3,
            )
            if not data or not isinstance(data, list):
                return None

            event = data[0]
            if not isinstance(event, dict) or not event.get("active") or event.get("closed"):
                return None

            markets = event.get("markets", [])
            if not markets or not isinstance(markets, list):
                return None

            market = markets[0]
            if not isinstance(market, dict):
                return None

            raw_outcome_prices = market.get("outcomePrices", "[]")
            raw_outcomes = market.get("outcomes", "[]")
            raw_clob_token_ids = market.get("clobTokenIds", "[]")

            outcome_prices = json.loads(raw_outcome_prices) if isinstance(raw_outcome_prices, str) else raw_outcome_prices
            outcomes = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else raw_outcomes
            clob_token_ids = json.loads(raw_clob_token_ids) if isinstance(raw_clob_token_ids, str) else raw_clob_token_ids

            if not isinstance(outcome_prices, list) or not isinstance(outcomes, list) or not isinstance(clob_token_ids, list):
                return None

            if len(outcome_prices) < 2 or len(outcomes) < 2 or len(clob_token_ids) < 2:
                return None

            prices = [float(p) for p in outcome_prices]
            winner_idx = 0 if prices[0] >= prices[1] else 1
            liquidity = event.get("liquidity", 0) or 0

            return {
                "slug": slug,
                "slug_prefix": slug_prefix,
                "crypto": self.settings.markets.get(slug_prefix, ""),
                "title": event.get("title", ""),
                "close_ts": close_ts,
                "winner_side": outcomes[winner_idx],
                "winner_price": prices[winner_idx],
                "winner_token": clob_token_ids[winner_idx],
                "loser_price": prices[1 - winner_idx],
                "condition_id": market.get("conditionId", ""),
                "liquidity": float(liquidity),
            }
        except Exception:
            return None

    def midpoint(self, token_id: str) -> float:
        try:
            data = self.http.get_json(
                f"{self.settings.clob_api}/midpoint",
                params={"token_id": token_id},
                timeout=2,
            )
            return float(data.get("mid", 0))
        except Exception:
            return 0.0

