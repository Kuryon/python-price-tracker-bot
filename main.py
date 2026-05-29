#!/usr/bin/env python3
"""
Inteligentny Bot-Monitorujący (Price & Availability Tracker).

Śledzi zmiany cen/dostępności na stronach WWW i wysyła alerty na Discord/Telegram.

Uruchomienie demo (bez URL):
    python -m price_tracker.main --discord-webhook "https://discord.com/api/webhooks/..."

Konfiguracja z pliku:
    python -m price_tracker.main --config config.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from price_tracker.config import AppConfig, MonitorTarget, load_config_from_file, merge_cli_overrides
from price_tracker.database import StateDatabase
from price_tracker.demo_server import DEFAULT_HOST, DEFAULT_PORT, DEMO_PRODUCT_NAME, DemoServer
from price_tracker.fetcher import PageFetcher
from price_tracker.monitor import PriceMonitor
from price_tracker.notifier import NotificationService

logger = logging.getLogger(__name__)


def configure_logging(verbose: bool) -> None:
    """Konfiguracja modułu logging (zamiast print)."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inteligentny Bot-Monitorujący — śledzenie cen i alerty "
            "Discord/Telegram."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Przykłady:
  Demo (automatyczny serwer testowy):
    python -m price_tracker.main --discord-webhook URL

  Własny URL:
    python -m price_tracker.main --url "https://sklep.pl/produkt" \\
        --price-selector ".product-price" --target-price 999 \\
        --discord-webhook URL

  Z pliku config.json:
    python -m price_tracker.main --config config.json
        """,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Ścieżka do config.json (domyślnie: config.json w katalogu roboczym)",
    )
    parser.add_argument("--url", help="URL strony produktu do monitorowania")
    parser.add_argument("--name", default="Produkt", help="Nazwa produktu w alertach")
    parser.add_argument(
        "--price-selector",
        default=".price",
        help="Selektor CSS elementu z ceną (BeautifulSoup)",
    )
    parser.add_argument(
        "--target-price",
        type=float,
        default=None,
        help="Alert gdy cena spadnie do tej wartości lub poniżej",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Interwał sprawdzania w sekundach (domyślnie 15)",
    )
    parser.add_argument(
        "--discord-webhook",
        help="URL webhooka Discord",
    )
    parser.add_argument(
        "--telegram-token",
        help="Token bota Telegram",
    )
    parser.add_argument(
        "--telegram-chat-id",
        help="ID czatu Telegram",
    )
    parser.add_argument(
        "--channel",
        choices=["discord", "telegram"],
        help="Kanał powiadomień",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Wymuś tryb demo (wbudowany serwer HTTP)",
    )
    parser.add_argument(
        "--demo-port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port serwera demo (domyślnie {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Ścieżka do pliku SQLite ze stanem",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Logi DEBUG")
    return parser


def resolve_config(args: argparse.Namespace) -> AppConfig:
    """Scala config.json z argumentami CLI."""
    config_path = args.config
    if config_path is None and Path("config.json").is_file():
        config_path = Path("config.json")

    if config_path is not None and config_path.is_file():
        config = load_config_from_file(config_path)
        logger.info("Wczytano konfigurację z %s", config_path)
    else:
        config = AppConfig()

    config = merge_cli_overrides(
        config,
        url=args.url,
        name=args.name,
        price_selector=args.price_selector,
        target_price=args.target_price,
        poll_interval=args.interval,
        discord_webhook=args.discord_webhook,
        telegram_token=args.telegram_token,
        telegram_chat_id=args.telegram_chat_id,
        channel=args.channel,
    )

    if args.db:
        config.database_path = args.db

    # Tryb demo: brak URL lub flaga --demo
    if args.demo or not config.targets:
        config.demo_mode = True

    return config


def setup_demo_target(config: AppConfig, port: int) -> tuple[AppConfig, DemoServer]:
    """Uruchamia serwer demo i ustawia cel monitorowania."""
    demo = DemoServer(host=DEFAULT_HOST, port=port)
    demo.start()

    config.targets = [
        MonitorTarget(
            url=demo.product_url,
            name=DEMO_PRODUCT_NAME,
            price_selector=".price",
            target_price=config.targets[0].target_price if config.targets else 999.0,
            availability_selector=".availability",
            availability_in_stock_text="dostępny",
        ),
    ]
    if config.targets[0].target_price is None:
        config.targets[0].target_price = 999.0

    config.poll_interval_seconds = min(config.poll_interval_seconds, 10)

    logger.info(
        "=== TRYB DEMO ===\n"
        "Sklep testowy: %s\n"
        "Cena zmienia się losowo co ~15 s. Ustaw webhook Discord, "
        "aby zobaczyć alerty na kanale.",
        demo.product_url,
    )
    return config, demo


def validate_config(config: AppConfig) -> list[str]:
    """Zwraca listę ostrzeżeń (nie blokuje demo bez webhooka)."""
    warnings: list[str] = []
    if config.notification_channel == "discord" and not config.discord_webhook_url:
        warnings.append(
            "Brak --discord-webhook / discord_webhook_url — alerty tylko w konsoli."
        )
    if config.notification_channel == "telegram" and (
        not config.telegram_bot_token or not config.telegram_chat_id
    ):
        warnings.append("Brak danych Telegram — alerty tylko w konsoli.")
    return warnings


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    configure_logging(args.verbose)

    try:
        config = resolve_config(args)
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.error("Błąd konfiguracji: %s", exc)
        return 1

    demo_server: DemoServer | None = None
    if config.demo_mode:
        config, demo_server = setup_demo_target(config, args.demo_port)

    for warning in validate_config(config):
        logger.warning(warning)

    fetcher = PageFetcher(
        user_agent=config.user_agent,
        timeout_seconds=config.request_timeout_seconds,
    )
    database = StateDatabase(config.database_path)
    notifier = NotificationService(config)
    monitor = PriceMonitor(config, fetcher, database, notifier)

    try:
        monitor.run_forever()
    finally:
        monitor.stop()
        fetcher.close()
        notifier.close()
        if demo_server is not None:
            demo_server.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
