from bot.time_utils import ts_str


def log(msg: str) -> None:
    print(f"[{ts_str()}] {msg}", flush=True)

