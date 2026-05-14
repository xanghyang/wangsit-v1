"""
crypto_bot.py — ETH/BTC Up/Down 5min Trading Bot with Window Delta
Strategy:
  - Calculates Window Delta (current ETH price vs period-open price) from Binance
  - Only enters if the delta is large enough (near-certain outcome)
  - Enters between 10–50 seconds before close when Polymarket price >= 0.92

Improvements over previous version:
  - Binance Window Delta as primary filter (avoids entering near the line)
  - Micro momentum (direction of last 2 1min candles)
  - Composite score → configurable minimum confidence
  - Dry run mode (real data, no trades executed)

Usage:
    python crypto_bot.py --paper
    python crypto_bot.py --live
    python crypto_bot.py --dry-run      # real data, no trades
    python crypto_bot.py --live --amount 10
"""

import time
import json
import argparse
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────
GAMMA_API         = "https://gamma-api.polymarket.com"
CLOB_API          = "https://clob.polymarket.com"
BINANCE_API       = "https://data-api.binance.vision"

ENTRY_SECONDS_MAX = 50
ENTRY_SECONDS_MIN = 10
PRICE_MIN         = {          # minimum price per crypto — BTC stricter due to higher volatility
    "BTC": 0.52,
    "ETH": 0.52,
}
PRICE_MAX         = 0.93   # maximum price — CLOB accepts up to 0.93

WAKE_BEFORE       = 65
POLL_INTERVAL     = 3

# Window Delta thresholds (current price vs period-open price)
DELTA_SKIP        = 0.0003  # < 0.03% → too close to the line, skip
DELTA_WEAK        = 0.001   # 0.05–0.10% → weak signal
DELTA_STRONG      = 0.002   # > 0.20% → strong signal

# Minimum confidence to enter (0.0 – 1.0)
MIN_CONFIDENCE    = 0.3

# ATR — volatility filter
ATR_PERIODS       = 5     # last 5 periods of 5min
ATR_MULTIPLIER    = 1.5   # if current range > 1.5x ATR → skip

# Binance symbols
BINANCE_SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
}

MARKETS = {
    "btc-updown-5m": "BTC",
    "eth-updown-5m": "ETH",
}

# ─── UTILS ─────────────────────────────────────────────────────────────────────
def ts_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def log(msg):
    print(f"[{ts_str()}] {msg}")

def now_unix():
    return int(time.time())

def next_close_ts():
    return ((now_unix() // 300) + 1) * 300

def window_open_ts():
    """Timestamp of the current period's open (multiple of 300)."""
    return (now_unix() // 300) * 300

# ─── BINANCE API ───────────────────────────────────────────────────────────────
def get_binance_candles(symbol: str, interval: str = "1m", limit: int = 6) -> list:
    """Fetches the last N candles from Binance."""
    try:
        r = requests.get(
            f"{BINANCE_API}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=3
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"[BINANCE ERROR] {e}")
        return []

def get_binance_price(symbol: str) -> float:
    """Current price from Binance."""
    try:
        r = requests.get(
            f"{BINANCE_API}/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=2
        )
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception:
        return 0.0

def get_window_open_price(symbol: str, window_ts: int) -> float:
    """
    Fetches the open price of the current period from Binance.
    window_ts is the Unix timestamp of the 5-minute period start.
    """
    try:
        # Fetch the 5min candle corresponding to the period start
        r = requests.get(
            f"{BINANCE_API}/api/v3/klines",
            params={
                "symbol":    symbol,
                "interval":  "5m",
                "startTime": window_ts * 1000,  # Binance uses milliseconds
                "limit":     1,
            },
            timeout=3
        )
        r.raise_for_status()
        candles = r.json()
        if candles:
            return float(candles[0][1])  # open price
        return 0.0
    except Exception:
        return 0.0

# ─── TECHNICAL ANALYSIS ────────────────────────────────────────────────────────

def get_atr(symbol: str, window_ts: int, periods: int = 5) -> float:
    """
    Calculates ATR (Average True Range) over the last N 5min periods.
    Returns the average range in USDC.
    """
    try:
        # Fetch periods candles ending at the current period start
        r = requests.get(
            f"{BINANCE_API}/api/v3/klines",
            params={
                "symbol":   symbol,
                "interval": "5m",
                "endTime":  window_ts * 1000,  # up to the current period start
                "limit":    periods,
            },
            timeout=3
        )
        r.raise_for_status()
        candles = r.json()
        if not candles:
            return 0.0
        ranges = [float(c[2]) - float(c[3]) for c in candles]  # high - low
        return sum(ranges) / len(ranges)
    except Exception:
        return 0.0

def analyze(symbol: str, window_ts: int) -> dict:
    """
    Calculates a composite score based on:
    1. Window Delta (weight 5–7) — difference between current price and period open
    2. Micro momentum (weight 2) — direction of last 2 1min candles

    Returns: {score, confidence, direction, window_open, current_price, delta_pct, reason}
    """
    # Current price
    current_price = get_binance_price(symbol)
    if current_price <= 0:
        return {"confidence": 0, "direction": None, "reason": "no Binance price"}

    # Period open price
    window_open = get_window_open_price(symbol, window_ts)
    if window_open <= 0:
        # Fallback: use the open of the first 1min candle in the period
        candles = get_binance_candles(symbol, "1m", 6)
        if candles:
            window_open = float(candles[0][1])
        else:
            return {"confidence": 0, "direction": None, "reason": "no open price"}

    # 1. Window Delta
    delta = (current_price - window_open) / window_open
    delta_pct = abs(delta) * 100
    delta_dir = "Up" if delta > 0 else "Down"

    # ATR — volatility filter
    # If the current period range already exceeds 1.5x historical ATR → too volatile
    atr = get_atr(symbol, window_ts, ATR_PERIODS)
    if atr > 0:
        candles_5m = get_binance_candles(symbol, "5m", 1)
        if candles_5m:
            current_range = float(candles_5m[0][2]) - float(candles_5m[0][3])  # high - low
            if current_range > atr * ATR_MULTIPLIER:
                return {
                    "confidence":    0,
                    "direction":     None,
                    "window_open":   window_open,
                    "current_price": current_price,
                    "delta_pct":     delta_pct,
                    "atr":           atr,
                    "current_range": current_range,
                    "reason":        f"ATR skip: range ${current_range:.2f} > {ATR_MULTIPLIER}x ATR ${atr:.2f}",
                }

    if abs(delta) < DELTA_SKIP:
        return {
            "confidence":    0,
            "direction":     None,
            "window_open":   window_open,
            "current_price": current_price,
            "delta_pct":     delta_pct,
            "reason":        f"delta {delta_pct:.4f}% < {DELTA_SKIP*100:.3f}% — too close to the line",
        }

    # Delta weight
    if abs(delta) >= DELTA_STRONG * 5:  # > 1%
        delta_weight = 7
    elif abs(delta) >= DELTA_STRONG:    # > 0.2%
        delta_weight = 5
    elif abs(delta) >= DELTA_WEAK:      # > 0.1%
        delta_weight = 3
    else:                                # > 0.05%
        delta_weight = 1

    score = delta_weight if delta > 0 else -delta_weight

    # 2. Micro momentum (last 2 1min candles)
    # Momentum only reinforces the delta — never reverses it
    candles = get_binance_candles(symbol, "1m", 3)
    if len(candles) >= 2:
        prev_close   = float(candles[-2][4])
        last_close   = float(candles[-1][4])
        momentum_up  = last_close > prev_close
        # Only adds if momentum aligns with the delta direction
        if (delta > 0 and momentum_up) or (delta < 0 and not momentum_up):
            score += 2
            momentum_str = f"↑ {last_close:.2f} (confirms)" if momentum_up else f"↓ {last_close:.2f} (confirms)"
        else:
            momentum_str = f"{'↑' if momentum_up else '↓'} {last_close:.2f} (contradicts, ignored)"
    else:
        momentum_str = "no data"

    # Confidence (normalized over 9 = max possible)
    confidence = min(abs(score) / 9.0, 1.0)
    direction  = "Up" if score > 0 else "Down"

    return {
        "score":         score,
        "confidence":    confidence,
        "direction":     direction,
        "window_open":   window_open,
        "current_price": current_price,
        "delta_pct":     delta_pct,
        "delta_weight":  delta_weight,
        "momentum":      momentum_str,
        "atr":           atr if 'atr' in locals() else 0,
        "reason":        f"delta={delta_pct:.4f}% ({delta_dir}, w={delta_weight}) momentum={momentum_str}",
    }

# ─── POLYMARKET API ────────────────────────────────────────────────────────────
def get_market_for_close(slug_prefix: str, close_ts: int) -> dict | None:
    start_ts = close_ts - 300
    slug = f"{slug_prefix}-{start_ts}"
    try:
        r = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=3)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        event = data[0]
    except Exception:
        return None

    if not event.get("active") or event.get("closed"):
        return None

    markets = event.get("markets", [])
    if not markets:
        return None

    market = markets[0]
    outcome_prices = json.loads(market.get("outcomePrices", "[]"))
    outcomes       = json.loads(market.get("outcomes", "[]"))
    clob_token_ids = json.loads(market.get("clobTokenIds", "[]"))

    if len(outcome_prices) < 2 or len(clob_token_ids) < 2:
        return None

    prices = [float(p) for p in outcome_prices]
    winner_idx = 0 if prices[0] >= prices[1] else 1

    return {
        "slug":         slug,
        "slug_prefix":  slug_prefix,
        "crypto":       MARKETS[slug_prefix],
        "title":        event.get("title", ""),
        "close_ts":     close_ts,
        "winner_side":  outcomes[winner_idx],
        "winner_price": prices[winner_idx],
        "winner_token": clob_token_ids[winner_idx],
        "loser_price":  prices[1 - winner_idx],
        "condition_id": market.get("conditionId", ""),
        "liquidity":    float(event.get("liquidity", 0)),
    }

def get_clob_price(token_id: str) -> float:
    try:
        r = requests.get(f"{CLOB_API}/midpoint", params={"token_id": token_id}, timeout=2)
        r.raise_for_status()
        return float(r.json().get("mid", 0))
    except Exception:
        return 0.0

def execute_buy(token_id: str, amount_usdc: float, price: float,
                private_key: str, proxy_wallet: str) -> bool:
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.order_builder.constants import BUY

        client = ClobClient(
            host=CLOB_API,
            key=private_key,
            chain_id=137,
            signature_type=1,
            funder=proxy_wallet,
        )
        client.set_api_creds(client.create_or_derive_api_creds())

        taker_price = min(round(price + 0.01, 2), 0.99)  # multiple of 0.01, max 0.99
        size        = round(amount_usdc / price, 2)

        resp = client.create_and_post_order(OrderArgs(
            token_id=token_id,
            price=taker_price,
            size=size,
            side=BUY,
        ))
        log(f"   ✅ BUY OK: {resp.get('status')} | order {resp.get('orderID','')[:20]}...")
        return True
    except Exception as e:
        log(f"   ❌ BUY failed: {e}")
        return False

# ─── BOT ───────────────────────────────────────────────────────────────────────
class CryptoBot:

    def __init__(self, paper: bool, dry_run: bool, amount: float):
        self.paper        = paper
        self.dry_run      = dry_run  # real data, no execution
        self.amount       = amount
        self.traded_slugs = set()
        self.trades       = []
        self.private_key  = os.getenv("POLY_PRIVATE_KEY", "")
        self.proxy_wallet = os.getenv("POLY_PROXY_WALLET", "")
        # --- MUTANS COMPOUND v0.1 (student china $0.99) ---
        self.base_amount = max(0.99, amount)  # floor $0.99
        self.compound_rate = 0.02  # 2% growth per trade

        if not paper and not dry_run and (not self.private_key or not self.proxy_wallet):
            raise ValueError("POLY_PRIVATE_KEY and POLY_PROXY_WALLET required in .env")

        mode = "DRY RUN" if dry_run else ("PAPER" if paper else "🔴 LIVE")
        log("=" * 60)
        log(f"Crypto Up/Down Bot | {mode} | start ${amount:.2f}/trade | MUTANS VPS v0.1")
        log(f"Markets: {', '.join(MARKETS.values())}")
        log(f"Entry window: {ENTRY_SECONDS_MIN}-{ENTRY_SECONDS_MAX}s | "
            f"Price: BTC>={PRICE_MIN['BTC']} ETH>={PRICE_MIN['ETH']} max={PRICE_MAX}")
        log(f"Min delta: {DELTA_SKIP*100:.3f}% | Min confidence: {MIN_CONFIDENCE*100:.0f}%")
        log("Auto-restart: exit after 10 errors | Wallet-zero sleep: 1h")
        log("=" * 60)

    def run(self):
        consecutive_errors = 0
        while True:
            try:
                self._cycle()
                consecutive_errors = 0  # reset on success
            except KeyboardInterrupt:
                log("Stopped.")
                self._print_summary()
                break
            except Exception as e:
                consecutive_errors += 1
                log(f"Error #{consecutive_errors}: {e}")
                if consecutive_errors > 10:
                    log("Too many consecutive errors — exiting for Railway/VPS auto-restart")
                    self._print_summary()
                    break
                time.sleep(5)

    def _cycle(self):
        # --- VPS SAFETY: wallet zero check ---
        if not self.paper and not self.dry_run and self.amount < 0.99:
            log(f"💰 Wallet base below $0.99 (${self.amount:.2f}) — sleeping 1h to avoid dust trades")
            time.sleep(3600)
            return

        close_ts   = next_close_ts()
        sleep_secs = close_ts - now_unix() - WAKE_BEFORE

        if sleep_secs > 0:
            log(f"💤 Sleeping {sleep_secs:.0f}s → next close "
                f"{datetime.fromtimestamp(close_ts, tz=timezone.utc).strftime('%H:%M:%S')} UTC")
            time.sleep(sleep_secs)

        if now_unix() >= close_ts + 5:
            log(f"⚠️  Arrived too late, skipping close "
                f"{datetime.fromtimestamp(close_ts, tz=timezone.utc).strftime('%H:%M:%S')} UTC")
            for prefix in MARKETS:
                self.traded_slugs.add(f"{prefix}-{close_ts - 300}")
            return

        log(f"⚡ Active window — close "
            f"{datetime.fromtimestamp(close_ts, tz=timezone.utc).strftime('%H:%M:%S')} UTC")

        entered_slugs = set()

        while True:
            seconds_left = close_ts - now_unix()

            if seconds_left <= 0:
                log("⏰ Market closed.")
                for prefix in MARKETS:
                    self.traded_slugs.add(f"{prefix}-{close_ts - 300}")
                break

            pending = [
                prefix for prefix in MARKETS
                if f"{prefix}-{close_ts - 300}" not in self.traded_slugs
                and f"{prefix}-{close_ts - 300}" not in entered_slugs
            ]

            if not pending:
                time.sleep(POLL_INTERVAL)
                continue

            # Query Polymarket and Binance in parallel
            def fetch_all(prefix):
                market = get_market_for_close(prefix, close_ts)
                if not market:
                    return prefix, None, None
                clob_price = get_clob_price(market["winner_token"])
                if clob_price > 0:
                    market["winner_price"] = clob_price
                # Technical analysis with Binance — correct symbol per crypto
                w_ts = close_ts - 300
                crypto_name = MARKETS[prefix]
                binance_sym = BINANCE_SYMBOLS.get(crypto_name, "BTCUSDT")
                ta = analyze(binance_sym, w_ts)
                return prefix, market, ta

            with ThreadPoolExecutor(max_workers=len(pending)) as executor:
                futures = {executor.submit(fetch_all, p): p for p in pending}
                results = []
                for future in as_completed(futures):
                    results.append(future.result())

            seconds_left = close_ts - now_unix()

            for prefix, market, ta in results:
                if not market or not ta:
                    continue

                slug   = market["slug"]
                crypto = market["crypto"]

                if slug in self.traded_slugs or slug in entered_slugs:
                    continue

                # Log monitoring info when still outside entry window
                if seconds_left > ENTRY_SECONDS_MAX + 5:
                    log(f"   [{crypto}] {seconds_left:.0f}s | "
                        f"PM:{market['winner_side']}@{market['winner_price']:.3f} | "
                        f"Price:{ta.get('current_price',0):.2f} | "
                        f"delta:{ta.get('delta_pct',0):.4f}% | "
                        f"conf:{ta.get('confidence',0):.0%}")
                    continue

                log(f"🎯 [{crypto}] {seconds_left:.1f}s | "
                    f"PM:{market['winner_side']}@{market['winner_price']:.3f} | "
                    f"delta:{ta.get('delta_pct',0):.4f}% | "
                    f"conf:{ta.get('confidence',0):.0%} | "
                    f"{ta.get('reason','')[:50]}")

                if ENTRY_SECONDS_MIN <= seconds_left <= ENTRY_SECONDS_MAX:
                    self._evaluate_entry(market, ta, seconds_left, entered_slugs)

            time.sleep(POLL_INTERVAL)

    def _evaluate_entry(self, market, ta, seconds_left, entered_slugs):
        slug      = market["slug"]
        crypto    = market["crypto"]
        price_min = PRICE_MIN.get(crypto, 0.92)

        # Filter 1: minimum price per crypto
        if market["winner_price"] < price_min:
            log(f"   [{crypto}] SKIP — PM price {market['winner_price']:.3f} < {price_min}")
            return

        # Filter 1b: maximum price
        if market["winner_price"] > PRICE_MAX:
            log(f'   [{crypto}] SKIP — PM price {market["winner_price"]:.3f} > {PRICE_MAX} (minimal upside)')
            return

        # Filter 2: minimum confidence
        confidence = ta.get("confidence", 0)
        if confidence < MIN_CONFIDENCE:
            log(f"   [{crypto}] SKIP — confidence {confidence:.0%} < {MIN_CONFIDENCE:.0%}")
            return

        # Filter 3: direction must match between Binance and Polymarket
        ta_dir  = ta.get("direction")
        pm_side = market["winner_side"]
        if ta_dir and ta_dir != pm_side:
            log(f"   [{crypto}] SKIP — Binance says {ta_dir} but PM says {pm_side}")
            return

        # Filter 4: minimum delta
        delta_pct = ta.get("delta_pct", 0)
        if delta_pct < DELTA_SKIP * 100:
            log(f"   [{crypto}] SKIP — delta {delta_pct:.4f}% too small")
            return

        self._enter(market, ta, seconds_left)
        entered_slugs.add(slug)
        self.traded_slugs.add(slug)

    def _enter(self, market: dict, ta: dict, seconds_left: float):
        price        = market["winner_price"]
        crypto       = market["crypto"]
        confidence   = ta.get("confidence", MIN_CONFIDENCE)

        # --- MUTANS COMPOUND: hitung bet size dinamis ---
        # base = 2% dari amount saat ini, floor $0.99, scale dengan confidence
        dynamic_amount = max(0.99, self.amount * (confidence / MIN_CONFIDENCE))
        
        # mode LIVE: coba ambil balance real USDC untuk auto-compound presisi
        if not self.paper and not self.dry_run:
            try:
                from py_clob_client.client import ClobClient
                _c = ClobClient(host=CLOB_API, key=self.private_key, chain_id=137, signature_type=1, funder=self.proxy_wallet)
                _c.set_api_creds(_c.create_or_derive_api_creds())
                # get_balance() kadang return float, kadang dict
                bal = _c.get_balance()
                usdc = float(bal['usdc']) if isinstance(bal, dict) and 'usdc' in bal else float(bal) if bal else self.amount
                if usdc >= 0.99:
                    # student china: 2% dari bankroll, dikali confidence boost
                    dynamic_amount = max(0.99, usdc * 0.02 * (confidence / MIN_CONFIDENCE))
            except Exception:
                # fallback ke in-memory compound kalau API gagal
                pass

        dynamic_amount = round(dynamic_amount, 2)
        expected_pnl = (dynamic_amount / price) - dynamic_amount
        expected_pct = expected_pnl / dynamic_amount * 100

        log(f"🟢 ENTERING [{crypto} {market['winner_side']}] {market['title'][:45]}")
        log(f"   price={price:.3f} | time_left={seconds_left:.1f}s | "
            f"invested=${dynamic_amount:.2f} | expected_pnl=+${expected_pnl:.2f} (+{expected_pct:.1f}%)")
        log(f"   Price:{ta.get('current_price',0):.2f} | "
            f"delta:{ta.get('delta_pct',0):.4f}% | "
            f"conf:{confidence:.0%} | compound_base=${self.amount:.2f}")

        if self.paper or self.dry_run:
            mode = "📄 PAPER" if self.paper else "🔍 DRY RUN"
            log(f"   {mode} — not executed on chain")
            executed = True
        else:
            executed = execute_buy(
                market["winner_token"], dynamic_amount, price,
                self.private_key, self.proxy_wallet
            )

        if executed:
            self.trades.append({
                "crypto":       crypto,
                "title":        market["title"],
                "side":         market["winner_side"],
                "price_entry":  price,
                "amount":       dynamic_amount,
                "seconds_left": seconds_left,
                "pnl_expected": expected_pnl,
                "delta_pct":    ta.get("delta_pct", 0),
                "confidence":   confidence,
                "timestamp":    ts_str(),
            })
            # --- update compound base untuk trade berikutnya ---
            self.amount = max(0.99, dynamic_amount * (1 + self.compound_rate))
            log(f"   ✅ Trade #{len(self.trades)} recorded [{crypto}] | next_base=${self.amount:.2f}")

    def _print_summary(self):
        log("─" * 60)
        log(f"SUMMARY — {len(self.trades)} trades")
        total_invested = sum(t["amount"] for t in self.trades)
        total_expected = sum(t["pnl_expected"] for t in self.trades)
        for t in self.trades:
            log(f"  [{t['crypto']}] {t['title'][:35]} | {t['side']} @ "
                f"{t['price_entry']:.3f} | {t['seconds_left']:.0f}s | "
                f"delta:{t['delta_pct']:.4f}% | conf:{t['confidence']:.0%} | "
                f"+${t['pnl_expected']:.2f}")
        if self.trades:
            log(f"  Total invested: ${total_invested:.2f}")
            log(f"  Expected PnL:   +${total_expected:.2f} "
                f"(+{total_expected/total_invested*100:.1f}%)")
        log("─" * 60)


# ─── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto Up/Down 5min Bot with Window Delta")
    parser.add_argument("--paper",    action="store_true", help="Paper trading mode (simulated)")
    parser.add_argument("--live",     action="store_true", help="Live trading mode (real funds)")
    parser.add_argument("--dry-run",  action="store_true", help="Dry run — real data, no trades executed")
    parser.add_argument("--amount",   type=float, default=0.99, help="USDC per trade (start $0.99 student china)")
    args = parser.parse_args()

    dry_run = args.dry_run
    paper   = args.paper or (not args.live and not dry_run)

    bot = CryptoBot(paper=paper, dry_run=dry_run, amount=args.amount)
    bot.run()