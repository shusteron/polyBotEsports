"""CLI entry point: python main.py --mode [scan|report|resolve|status]"""
import argparse
import sys
from pathlib import Path

import yaml
from loguru import logger


def load_config() -> dict:
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def setup_logging(cfg: dict) -> None:
    logger.remove()
    logger.add(sys.stderr, level=cfg.get("logging", {}).get("level", "INFO"))
    log_file = cfg.get("logging", {}).get("file", "data/bot.log")
    Path(log_file).parent.mkdir(exist_ok=True)
    logger.add(log_file, rotation="10 MB", retention="30 days", level="DEBUG")


def main() -> None:
    parser = argparse.ArgumentParser(description="LoL Esports Prediction Bot")
    parser.add_argument("--mode", choices=["scan", "report", "resolve", "status"], required=True)
    args = parser.parse_args()

    cfg = load_config()
    setup_logging(cfg)

    # Load .env if present (for CITO_API_KEY during local testing)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from src.bot import EsportsBot
    bot = EsportsBot(cfg)

    if args.mode == "scan":
        bot.run_scan_cycle()
    elif args.mode == "report":
        bot.export_report()
    elif args.mode == "resolve":
        bot.resolve_expired_markets()
    elif args.mode == "status":
        bot.print_status()


if __name__ == "__main__":
    main()
