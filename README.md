# Wangsit V1 - Polymarket 5m Crypto Bot

Production-oriented Python worker for BTC/ETH Up/Down 5-minute prediction markets on Polymarket. The bot uses Binance price data for signal generation, Polymarket Gamma/CLOB data for market selection, and a guarded auto-compound sizing model for live execution.

This repo is designed to run as a long-lived worker on Railway or a VPS.

## What It Does

- Trades BTC/ETH 5-minute Up/Down markets near the end of each window.
- Uses window delta, micro momentum, and ATR filtering.
- Confirms that Binance direction matches Polymarket's leading side.
- Keeps auto-compound sizing, bounded by production risk guards.
- Persists runtime state to avoid duplicate entries after restart.
- Exits non-zero after repeated errors so Railway/VPS can restart it.
- Supports Healthchecks.io and Telegram alerts through environment variables.

## Current Architecture

```text
wangsit-v1/
|-- crypto_bot.py              # Compatibility entrypoint
|-- bot/
|   |-- main.py                # CLI parsing
|   |-- runner.py              # Main bot loop and orchestration
|   |-- config.py              # Environment-driven settings
|   |-- binance.py             # Binance public API client
|   |-- polymarket.py          # Polymarket Gamma/CLOB read client
|   |-- signal.py              # Window delta, momentum, ATR signal engine
|   |-- risk.py                # Auto-compound and risk guards
|   |-- execution.py           # Polymarket CLOB execution client
|   |-- state.py               # Persistent JSON state
|   |-- notify.py              # Healthcheck and Telegram hooks
|   `-- time_utils.py          # Time helpers
|-- tests/                     # Unit tests
|-- Procfile                   # Railway worker command
|-- railway.json               # Railway restart policy
|-- requirements.txt
`-- .env.example
```

## Run Modes

```bash
# Paper mode, default if no mode is provided
python crypto_bot.py --paper

# Dry run, real data but no on-chain execution
python crypto_bot.py --dry-run

# Live mode, real funds
python crypto_bot.py --live

# Live mode with starting compound base
python crypto_bot.py --live --amount 5
```

## Required Railway Variables

For live trading, only these two are strictly required:

```text
POLY_PRIVATE_KEY
POLY_PROXY_WALLET
```

In Railway's Variables UI, enter them as separate name/value pairs:

```text
Name  : POLY_PRIVATE_KEY
Value : your_private_key

Name  : POLY_PROXY_WALLET
Value : your_polymarket_proxy_or_funder_wallet
```

## Recommended Production Variables

These are optional because the code has defaults, but they are recommended for production:

```text
STATE_PATH=data/state.json
HEALTHCHECK_URL=https://hc-ping.com/your-healthchecks-id
MAX_TRADE_AMOUNT=25
BANKROLL_FRACTION=0.02
MIN_TRADE_AMOUNT=0.99
MAX_DAILY_LOSS=15
MAX_CONSECUTIVE_LIVE_TRADES=24
```

Telegram alerts are optional:

```text
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### About `STATE_PATH`

Default:

```text
STATE_PATH=data/state.json
```

This stores:

- traded market slugs
- trade attempts
- executed trade records
- current compound base
- daily live trade count
- heartbeat cycle counter

On Railway without a mounted volume, this file is useful across short restarts but may disappear on redeploy. If you attach a Railway Volume mounted at `/data`, use:

```text
STATE_PATH=/data/state.json
```

## Strategy Defaults

The runtime defaults live in `bot/config.py` and can be overridden with environment variables.

| Setting | Default | Meaning |
|---|---:|---|
| `ENTRY_SECONDS_MIN` | `10` | Latest acceptable seconds before market close |
| `ENTRY_SECONDS_MAX` | `50` | Earliest acceptable seconds before market close |
| `WAKE_BEFORE` | `65` | Wake before close |
| `POLL_INTERVAL` | `3` | Polling interval during active window |
| `PRICE_MIN_BTC` | `0.52` | Minimum Polymarket leading-side price for BTC |
| `PRICE_MIN_ETH` | `0.52` | Minimum Polymarket leading-side price for ETH |
| `PRICE_MAX` | `0.93` | Maximum Polymarket entry price |
| `DELTA_SKIP` | `0.0003` | Skip if delta is below this absolute threshold |
| `DELTA_WEAK` | `0.001` | Weak delta threshold |
| `DELTA_STRONG` | `0.002` | Strong delta threshold |
| `MIN_CONFIDENCE` | `0.3` | Minimum signal confidence |
| `ATR_PERIODS` | `5` | ATR lookback in 5-minute candles |
| `ATR_MULTIPLIER` | `1.5` | Volatility skip threshold |

## Auto-Compound Risk Model

Live sizing uses real CLOB balance when available:

```text
amount = balance * BANKROLL_FRACTION * (confidence / MIN_CONFIDENCE)
```

Then it is bounded by:

- `MIN_TRADE_AMOUNT`
- `MAX_TRADE_AMOUNT`
- available balance
- `MAX_DAILY_LOSS`
- `MAX_CONSECUTIVE_LIVE_TRADES`

After an executed trade, the next in-memory compound base becomes:

```text
executed_amount * (1 + COMPOUND_RATE)
```

In paper/dry-run mode, the bot uses the persistent compound base because no live balance is available.

## Railway Deployment

1. Push this repo to GitHub.
2. Create a Railway project from the GitHub repo.
3. Railway will use the `Procfile`:

```text
worker: python crypto_bot.py --live
```

4. Add required variables:

```text
POLY_PRIVATE_KEY
POLY_PROXY_WALLET
```

5. Add recommended variables such as `STATE_PATH` and `HEALTHCHECK_URL`.
6. Deploy.

The bot is a worker process, not a web server. Do not use the Railway app URL as `HEALTHCHECK_URL`. Use a Healthchecks.io ping URL, for example:

```text
https://hc-ping.com/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

## Local Development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python crypto_bot.py --dry-run
```

Run tests:

```bash
python -m unittest discover -s tests
```

Syntax check without writing `.pyc` files:

```bash
python -c "import pathlib; [compile(p.read_text(encoding='utf-8'), str(p), 'exec') for p in [pathlib.Path('crypto_bot.py'), *pathlib.Path('bot').glob('*.py'), *pathlib.Path('tests').glob('*.py')]]"
```

## Production Behavior

- Recoverable API failures are skipped or logged.
- Consecutive top-level errors trigger `sys.exit(1)` after the configured limit.
- Railway/VPS supervisor should restart the worker on non-zero exit.
- Duplicate market slugs are blocked through persistent state.
- Heartbeat pings are sent when `HEALTHCHECK_URL` is configured.
- Telegram messages are sent when both Telegram variables are configured.

## Disclaimer

This software is experimental and not financial advice. Prediction markets and crypto execution involve real financial risk. You can lose your entire balance. Always test with `--paper` or `--dry-run` before live mode, and keep risk limits conservative.
