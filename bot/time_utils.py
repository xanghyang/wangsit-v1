import time
from datetime import datetime, timezone


def ts_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_unix() -> int:
    return int(time.time())


def close_ts_after(ts: int) -> int:
    return ((ts // 300) + 1) * 300


def next_close_ts() -> int:
    return close_ts_after(now_unix())


def format_utc(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")

