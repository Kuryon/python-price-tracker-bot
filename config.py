"""Ładowanie konfiguracji z pliku JSON i argumentów CLI."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

NotificationChannel = Literal["discord", "telegram"]
SelectorType = Literal["css", "xpath_text"]


@dataclass
class MonitorTarget:
    """Pojedynczy cel monitorowania (URL + selektor ceny)."""

    url: str
    name: str = "Produkt"
    price_selector: str = ".price"
    selector_type: SelectorType = "css"
    target_price: float | None = None
    availability_selector: str | None = None
    availability_in_stock_text: str = "dostępny"


@dataclass
class AppConfig:
    """Pełna konfiguracja aplikacji."""

    targets: list[MonitorTarget] = field(default_factory=list)
    poll_interval_seconds: int = 15
    notification_channel: NotificationChannel = "discord"
    discord_webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    database_path: str = "tracker_state.db"
    demo_mode: bool = False
    # User-Agent symulujący przeglądarkę
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    request_timeout_seconds: int = 20


def _parse_target(raw: dict[str, Any]) -> MonitorTarget:
    return MonitorTarget(
        url=str(raw["url"]),
        name=str(raw.get("name", "Produkt")),
        price_selector=str(raw.get("price_selector", ".price")),
        selector_type=raw.get("selector_type", "css"),  # type: ignore[arg-type]
        target_price=_optional_float(raw.get("target_price")),
        availability_selector=raw.get("availability_selector"),
        availability_in_stock_text=str(
            raw.get("availability_in_stock_text", "dostępny")
        ),
    )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def load_config_from_file(path: Path) -> AppConfig:
    """Wczytuje config.json."""
    if not path.is_file():
        raise FileNotFoundError(f"Brak pliku konfiguracji: {path}")

    with path.open(encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)

    targets_raw = data.get("targets")
    if not targets_raw:
        single_url = data.get("url")
        if single_url:
            targets_raw = [
                {
                    "url": single_url,
                    "name": data.get("name", "Produkt"),
                    "price_selector": data.get("price_selector", ".price"),
                    "target_price": data.get("target_price"),
                }
            ]
        else:
            targets_raw = []

    targets = [_parse_target(t) for t in targets_raw]

    channel = data.get("notification_channel", "discord")
    if channel not in ("discord", "telegram"):
        channel = "discord"

    return AppConfig(
        targets=targets,
        poll_interval_seconds=int(data.get("poll_interval_seconds", 15)),
        notification_channel=channel,  # type: ignore[arg-type]
        discord_webhook_url=data.get("discord_webhook_url"),
        telegram_bot_token=data.get("telegram_bot_token"),
        telegram_chat_id=data.get("telegram_chat_id"),
        database_path=str(data.get("database_path", "tracker_state.db")),
        demo_mode=bool(data.get("demo_mode", False)),
        user_agent=str(data.get("user_agent", AppConfig().user_agent)),
        request_timeout_seconds=int(data.get("request_timeout_seconds", 20)),
    )


def merge_cli_overrides(
    config: AppConfig,
    *,
    url: str | None,
    name: str | None,
    price_selector: str | None,
    target_price: float | None,
    poll_interval: int | None,
    discord_webhook: str | None,
    telegram_token: str | None,
    telegram_chat_id: str | None,
    channel: str | None,
) -> AppConfig:
    """Nadpisuje pola konfiguracji argumentami z linii poleceń."""
    if url:
        target = MonitorTarget(
            url=url,
            name=name or "Produkt",
            price_selector=price_selector or ".price",
            target_price=target_price,
        )
        config.targets = [target]

    if target_price is not None and config.targets:
        config.targets[0].target_price = target_price

    if poll_interval is not None:
        config.poll_interval_seconds = poll_interval

    if discord_webhook:
        config.discord_webhook_url = discord_webhook
        config.notification_channel = "discord"

    if telegram_token:
        config.telegram_bot_token = telegram_token
    if telegram_chat_id:
        config.telegram_chat_id = telegram_chat_id
    if channel in ("discord", "telegram"):
        config.notification_channel = channel  # type: ignore[assignment]

    return config
