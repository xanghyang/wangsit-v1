import argparse

from bot.runner import CryptoBot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crypto Up/Down 5min Bot with Window Delta")
    parser.add_argument("--paper", action="store_true", help="Paper trading mode (simulated)")
    parser.add_argument("--live", action="store_true", help="Live trading mode (real funds)")
    parser.add_argument("--dry-run", action="store_true", help="Dry run - real data, no trades executed")
    parser.add_argument("--amount", type=float, default=0.99, help="Starting compound base in USDC")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dry_run = args.dry_run
    paper = args.paper or (not args.live and not dry_run)
    bot = CryptoBot(paper=paper, dry_run=dry_run, amount=args.amount)
    bot.run()


if __name__ == "__main__":
    main()

