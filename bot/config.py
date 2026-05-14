import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return float(raw)


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return int(raw)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    gamma_api: str = os.getenv("GAMMA_API", "https://gamma-api.polymarket.com")
    clob_api: str = os.getenv("CLOB_API", "https://clob.polymarket.com")
    binance_api: str = os.getenv("BINANCE_API", "https://data-api.binance.vision")

    entry_seconds_max: int = env_int("ENTRY_SECONDS_MAX", 50)
    entry_seconds_min: int = env_int("ENTRY_SECONDS_MIN", 10)
    wake_before: int = env_int("WAKE_BEFORE", 65)
    poll_interval: int = env_int("POLL_INTERVAL", 3)

    price_min: dict[str, float] = field(default_factory=lambda: {
        "BTC": env_float("PRICE_MIN_BTC", 0.52),
        "ETH": env_float("PRICE_MIN_ETH", 0.52),
    })
    price_max: float = env_float("PRICE_MAX", 0.93)
    taker_slippage: float = env_float("TAKER_SLIPPAGE", 0.01)

    delta_skip: float = env_float("DELTA_SKIP", 0.0003)
    delta_weak: float = env_float("DELTA_WEAK", 0.001)
    delta_strong: float = env_float("DELTA_STRONG", 0.002)
    min_confidence: float = env_float("MIN_CONFIDENCE", 0.3)

    atr_periods: int = env_int("ATR_PERIODS", 5)
    atr_multiplier: float = env_float("ATR_MULTIPLIER", 1.5)

    enable_multi_tf: bool = env_bool("ENABLE_MULTI_TF", True)
    multi_tf_min_agreement: int = env_int("MULTI_TF_MIN_AGREEMENT", 2)

    markets: dict[str, str] = field(default_factory=lambda: {
        "btc-updown-5m": "BTC",
        "eth-updown-5m": "ETH",
    })
    binance_symbols: dict[str, str] = field(default_factory=lambda: {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
    })

    private_key: str = os.getenv("POLY_PRIVATE_KEY", "")
    proxy_wallet: str = os.getenv("POLY_PROXY_WALLET", "")

    min_trade_amount: float = env_float("MIN_TRADE_AMOUNT", 0.99)
    bankroll_fraction: float = env_float("BANKROLL_FRACTION", 0.02)
    compound_rate: float = env_float("COMPOUND_RATE", 0.02)
    max_trade_amount: float = env_float("MAX_TRADE_AMOUNT", 25.0)
    max_daily_loss: float = env_float("MAX_DAILY_LOSS", 15.0)
    max_consecutive_live_trades: int = env_int("MAX_CONSECUTIVE_LIVE_TRADES", 24)

    state_path: str = os.getenv("STATE_PATH", "data/state.json")
    healthcheck_url: str = os.getenv("HEALTHCHECK_URL", "")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    heartbeat_every_cycles: int = env_int("HEARTBEAT_EVERY_CYCLES", 1)

    consecutive_error_limit: int = env_int("CONSECUTIVE_ERROR_LIMIT", 10)
    error_sleep_seconds: int = env_int("ERROR_SLEEP_SECONDS", 60)
    wallet_low_sleep_seconds: int = env_int("WALLET_LOW_SLEEP_SECONDS", 3600)
    late_grace_seconds: int = env_int("LATE_GRACE_SECONDS", 5)

    def validate_for_mode(self, paper: bool, dry_run: bool) -> None:
        if not paper and not dry_run and (not self.private_key or not self.proxy_wallet):
            raise ValueError("POLY_PRIVATE_KEY and POLY_PROXY_WALLET required in live mode")
        if self.entry_seconds_min >= self.entry_seconds_max:
            raise ValueError("ENTRY_SECONDS_MIN must be smaller than ENTRY_SECONDS_MAX")
        if self.min_trade_amount <= 0:
            raise ValueError("MIN_TRADE_AMOUNT must be positive")
        if self.max_trade_amount < self.min_trade_amount:
            raise ValueError("MAX_TRADE_AMOUNT must be >= MIN_TRADE_AMOUNT")

