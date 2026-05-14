import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from bot.binance import BinanceClient
from bot.config import Settings
from bot.execution import ExecutionClient
from bot.logging_setup import log
from bot.notify import Notifier
from bot.polymarket import PolymarketClient
from bot.risk import RiskManager
from bot.signal import SignalEngine
from bot.state import BotState
from bot.time_utils import format_utc, next_close_ts, now_unix, ts_str


class CryptoBot:
    def __init__(self, paper: bool, dry_run: bool, amount: float, settings: Settings | None = None):
        self.paper = paper
        self.dry_run = dry_run
        self.settings = settings or Settings()
        self.settings.validate_for_mode(paper=paper, dry_run=dry_run)

        default_base = max(self.settings.min_trade_amount, amount)
        self.state = BotState.load(self.settings.state_path, default_base)
        self.state.compound_base = max(self.settings.min_trade_amount, self.state.compound_base)

        self.binance = BinanceClient(self.settings)
        self.polymarket = PolymarketClient(self.settings)
        self.signal_engine = SignalEngine(self.settings, self.binance)
        self.risk = RiskManager(self.settings)
        self.notifier = Notifier(self.settings)
        self.execution = None if self.paper or self.dry_run else ExecutionClient(self.settings)

        mode = "DRY RUN" if dry_run else ("PAPER" if paper else "LIVE")
        log("=" * 60)
        log(f"Crypto Up/Down Bot | {mode} | compound_base=${self.state.compound_base:.2f}")
        log(f"Markets: {', '.join(self.settings.markets.values())}")
        log(
            f"Entry window: {self.settings.entry_seconds_min}-{self.settings.entry_seconds_max}s | "
            f"Price: BTC>={self.settings.price_min['BTC']} ETH>={self.settings.price_min['ETH']} "
            f"max={self.settings.price_max}"
        )
        log(
            f"Compound: fraction={self.settings.bankroll_fraction:.2%} "
            f"min=${self.settings.min_trade_amount:.2f} max=${self.settings.max_trade_amount:.2f}"
        )
        log("Auto-restart: sys.exit(1) after consecutive error limit")
        log("=" * 60)
        self.notifier.heartbeat(f"Wangsit bot started | mode={mode}")

    def run(self) -> None:
        consecutive_errors = 0
        while True:
            try:
                self.state.reset_daily_if_needed()
                self._cycle()
                consecutive_errors = 0
                self._save_state()
            except KeyboardInterrupt:
                log("Stopped.")
                self._print_summary()
                self._save_state()
                return
            except Exception as exc:
                consecutive_errors += 1
                log(f"Error #{consecutive_errors}: {exc}")
                self._save_state()
                if consecutive_errors > self.settings.consecutive_error_limit:
                    log("Too many consecutive errors - exiting non-zero for Railway/VPS restart")
                    self._print_summary()
                    self.notifier.heartbeat(f"Wangsit bot exiting after {consecutive_errors} errors: {exc}")
                    sys.exit(1)
                time.sleep(self.settings.error_sleep_seconds)

    def _cycle(self) -> None:
        self._maybe_heartbeat()

        if not self.paper and not self.dry_run:
            balance = self.execution.balance() if self.execution else None
            if balance is not None and balance < self.settings.min_trade_amount:
                log(f"Wallet balance ${balance:.2f} below minimum - sleeping 1h")
                time.sleep(self.settings.wallet_low_sleep_seconds)
                return

        close_ts = next_close_ts()
        sleep_secs = close_ts - now_unix() - self.settings.wake_before
        if sleep_secs > 0:
            log(f"Sleeping {sleep_secs:.0f}s -> next close {format_utc(close_ts)} UTC")
            time.sleep(sleep_secs)

        if now_unix() >= close_ts + self.settings.late_grace_seconds:
            log(f"Arrived too late, marking close {format_utc(close_ts)} UTC as skipped")
            for prefix in self.settings.markets:
                self._mark_traded(f"{prefix}-{close_ts - 300}")
            return

        log(f"Active window - close {format_utc(close_ts)} UTC")
        entered_slugs: set[str] = set()

        while True:
            seconds_left = close_ts - now_unix()
            if seconds_left <= 0:
                log("Market closed.")
                for prefix in self.settings.markets:
                    self._mark_traded(f"{prefix}-{close_ts - 300}")
                break

            pending = [
                prefix for prefix in self.settings.markets
                if f"{prefix}-{close_ts - 300}" not in self.state.traded_slugs
                and f"{prefix}-{close_ts - 300}" not in entered_slugs
            ]
            if not pending:
                time.sleep(self.settings.poll_interval)
                continue

            results = self._fetch_window_data(pending, close_ts)
            seconds_left = close_ts - now_unix()

            for prefix, market, signal in results:
                if not market or not signal:
                    continue

                slug = market["slug"]
                crypto = market["crypto"]
                if slug in self.state.traded_slugs or slug in entered_slugs:
                    continue

                if seconds_left > self.settings.entry_seconds_max + 5:
                    if signal.multi_tf_enabled:
                        conflict_flag = " [CONFLICT]" if signal.multi_tf_conflict else ""
                        log(
                            f"   [{crypto}] {seconds_left:.0f}s | "
                            f"PM:{market['winner_side']}@{market['winner_price']:.3f} | "
                            f"Price:{signal.current_price:.2f} | delta:{signal.delta_pct:.4f}% | "
                            f"conf:{signal.confidence:.0%}{conflict_flag}"
                        )
                    else:
                        log(
                            f"   [{crypto}] {seconds_left:.0f}s | "
                            f"PM:{market['winner_side']}@{market['winner_price']:.3f} | "
                            f"Price:{signal.current_price:.2f} | delta:{signal.delta_pct:.4f}% | "
                            f"conf:{signal.confidence:.0%}"
                        )
                    continue

                log(
                    f"Target [{crypto}] {seconds_left:.1f}s | "
                    f"PM:{market['winner_side']}@{market['winner_price']:.3f} | "
                    f"delta:{signal.delta_pct:.4f}% | conf:{signal.confidence:.0%} | "
                    f"{signal.reason[:70]}"
                )

                if self.settings.entry_seconds_min <= seconds_left <= self.settings.entry_seconds_max:
                    if self._evaluate_entry(market, signal.as_dict(), seconds_left):
                        entered_slugs.add(slug)

            time.sleep(self.settings.poll_interval)

    def _fetch_window_data(self, pending: list[str], close_ts: int) -> list[tuple[str, dict | None, object | None]]:
        def fetch_all(prefix: str):
            market = self.polymarket.market_for_close(prefix, close_ts)
            if not market:
                return prefix, None, None
            clob_price = self.polymarket.midpoint(market["winner_token"])
            if clob_price > 0:
                market["winner_price"] = clob_price
            crypto_name = self.settings.markets[prefix]
            binance_symbol = self.settings.binance_symbols.get(crypto_name, "BTCUSDT")
            signal = self.signal_engine.analyze(binance_symbol, close_ts - 300, use_multi_tf=self.settings.enable_multi_tf)
            return prefix, market, signal

        with ThreadPoolExecutor(max_workers=len(pending)) as executor:
            futures = {executor.submit(fetch_all, p): p for p in pending}
            return [future.result() for future in as_completed(futures)]

    def _evaluate_entry(self, market: dict, signal: dict, seconds_left: float) -> bool:
        slug = market["slug"]
        crypto = market["crypto"]
        price_min = self.settings.price_min.get(crypto, self.settings.min_trade_amount)

        if market["winner_price"] < price_min:
            log(f"   [{crypto}] SKIP - PM price {market['winner_price']:.3f} < {price_min}")
            return False

        if market["winner_price"] > self.settings.price_max:
            log(f"   [{crypto}] SKIP - PM price {market['winner_price']:.3f} > {self.settings.price_max}")
            return False

        confidence = signal.get("confidence", 0)
        if confidence < self.settings.min_confidence:
            log(f"   [{crypto}] SKIP - confidence {confidence:.0%} < {self.settings.min_confidence:.0%}")
            return False

        ta_dir = signal.get("direction")
        pm_side = market["winner_side"]
        if ta_dir and ta_dir != pm_side:
            log(f"   [{crypto}] SKIP - Binance says {ta_dir} but PM says {pm_side}")
            return False

        delta_pct = signal.get("delta_pct", 0)
        if delta_pct < self.settings.delta_skip * 100:
            log(f"   [{crypto}] SKIP - delta {delta_pct:.4f}% too small")
            return False

        if self._enter(market, signal, seconds_left):
            self._mark_traded(slug)
            return True
        return False

    def _enter(self, market: dict, signal: dict, seconds_left: float) -> bool:
        price = market["winner_price"]
        crypto = market["crypto"]
        confidence = signal.get("confidence", self.settings.min_confidence)
        live_balance = None
        if not self.paper and not self.dry_run and self.execution:
            live_balance = self.execution.balance()

        decision = self.risk.size_trade(
            base_amount=self.state.compound_base,
            confidence=confidence,
            balance=live_balance,
            daily_loss=self.state.daily_loss,
            live_trades_today=self.state.live_trades_today,
            current_drawdown=self.state.daily_loss,
        )
        if not decision.allowed:
            log(f"   [{crypto}] SKIP - risk guard: {decision.reason}")
            return False

        dynamic_amount = decision.amount
        expected_pnl = (dynamic_amount / price) - dynamic_amount
        expected_pct = expected_pnl / dynamic_amount * 100

        log(f"ENTERING [{crypto} {market['winner_side']}] {market['title'][:45]}")
        log(
            f"   price={price:.3f} | time_left={seconds_left:.1f}s | "
            f"invested=${dynamic_amount:.2f} | expected_pnl=+${expected_pnl:.2f} (+{expected_pct:.1f}%)"
        )
        log(
            f"   Price:{signal.get('current_price', 0):.2f} | "
            f"delta:{signal.get('delta_pct', 0):.4f}% | conf:{confidence:.0%} | "
            f"compound_base=${self.state.compound_base:.2f}"
        )

        execution_result = None
        if self.paper or self.dry_run:
            mode = "PAPER" if self.paper else "DRY RUN"
            log(f"   {mode} - not executed on chain")
            executed = True
        else:
            execution_result = self.execution.buy(market["winner_token"], dynamic_amount, price) if self.execution else None
            executed = bool(execution_result and execution_result.ok)

        self._record_attempt(
            market=market,
            signal=signal,
            seconds_left=seconds_left,
            amount=dynamic_amount,
            expected_pnl=expected_pnl,
            executed=executed,
            execution_result=execution_result,
        )

        if executed:
            self.state.compound_base = self.risk.next_compound_base(dynamic_amount)
            if not self.paper and not self.dry_run:
                self.state.live_trades_today += 1
            log(f"   Trade recorded [{crypto}] | next_base=${self.state.compound_base:.2f}")
            self.notifier.heartbeat(
                f"Wangsit trade {crypto} {market['winner_side']} ${dynamic_amount:.2f} "
                f"@ {price:.3f} conf={confidence:.0%}"
            )
            self._save_state()
            return True

        self._save_state()
        return False

    def _record_attempt(self, *, market: dict, signal: dict, seconds_left: float,
                        amount: float, expected_pnl: float, executed: bool,
                        execution_result) -> None:
        self.state.trades.append({
            "crypto": market["crypto"],
            "slug": market["slug"],
            "title": market["title"],
            "side": market["winner_side"],
            "price_entry": market["winner_price"],
            "amount": amount,
            "seconds_left": seconds_left,
            "pnl_expected": expected_pnl,
            "delta_pct": signal.get("delta_pct", 0),
            "confidence": signal.get("confidence", 0),
            "signal": signal,
            "executed": executed,
            "execution": execution_result.__dict__ if execution_result else None,
            "timestamp": ts_str(),
        })

    def _mark_traded(self, slug: str) -> None:
        self.state.traded_slugs.add(slug)
        self._save_state()

    def _maybe_heartbeat(self) -> None:
        self.state.heartbeat_cycles += 1
        if self.state.heartbeat_cycles % max(1, self.settings.heartbeat_every_cycles) == 0:
            self.notifier.heartbeat(
                f"Wangsit heartbeat | trades={len(self.state.trades)} "
                f"base=${self.state.compound_base:.2f}"
            )

    def _save_state(self) -> None:
        self.state.save(self.settings.state_path)

    def _print_summary(self) -> None:
        log("-" * 60)
        log(f"SUMMARY - {len(self.state.trades)} attempts")
        executed = [t for t in self.state.trades if t.get("executed")]
        total_invested = sum(t["amount"] for t in executed)
        total_expected = sum(t["pnl_expected"] for t in executed)
        for trade in executed[-20:]:
            log(
                f"  [{trade['crypto']}] {trade['title'][:35]} | {trade['side']} @ "
                f"{trade['price_entry']:.3f} | {trade['seconds_left']:.0f}s | "
                f"delta:{trade['delta_pct']:.4f}% | conf:{trade['confidence']:.0%} | "
                f"+${trade['pnl_expected']:.2f}"
            )
        if total_invested:
            log(f"  Total invested: ${total_invested:.2f}")
            log(f"  Expected PnL: +${total_expected:.2f} (+{total_expected / total_invested * 100:.1f}%)")
        log("-" * 60)

