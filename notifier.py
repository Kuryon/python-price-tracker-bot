"""Uniwersalne powiadomienia: Discord (Embeds) i Telegram."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import requests

from price_tracker.config import AppConfig, NotificationChannel

logger = logging.getLogger(__name__)


class AlertKind(str, Enum):
    """Typ zdarzenia monitorowania."""

    PRICE_DROP = "price_drop"
    PRICE_CHANGE = "price_change"
    TARGET_REACHED = "target_reached"
    AVAILABILITY = "availability"
    DEMO = "demo"


@dataclass
class AlertPayload:
    """Dane do sformatowanego alertu."""

    title: str
    message: str
    product_name: str
    url: str
    old_price: float | None
    new_price: float | None
    kind: AlertKind
    extra_fields: dict[str, str] | None = None


# Kolory embedów Discord (decimal)
_DISCORD_COLORS: dict[AlertKind, int] = {
    AlertKind.PRICE_DROP: 0x2ECC71,      # zielony
    AlertKind.TARGET_REACHED: 0x3498DB,  # niebieski
    AlertKind.PRICE_CHANGE: 0xF39C12,    # pomarańczowy
    AlertKind.AVAILABILITY: 0x9B59B6,    # fiolet
    AlertKind.DEMO: 0xE74C3C,            # czerwony (demo)
}


class NotificationService:
    """Wysyła alerty na wybrany kanał (Discord lub Telegram)."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._session = requests.Session()

    def send(self, alert: AlertPayload) -> bool:
        """Uniwersalna funkcja wysyłki — wybiera kanał z konfiguracji."""
        channel = self._config.notification_channel
        try:
            if channel == "discord":
                return self._send_discord(alert)
            return self._send_telegram(alert)
        except requests.exceptions.RequestException as exc:
            logger.error("Nie udało się wysłać powiadomienia: %s", exc)
            return False

    def _send_discord(self, alert: AlertPayload) -> bool:
        webhook = self._config.discord_webhook_url
        if not webhook:
            logger.warning(
                "Brak discord_webhook_url — alert tylko w logu: %s", alert.title
            )
            return False

        fields: list[dict[str, Any]] = [
            {"name": "Produkt", "value": alert.product_name, "inline": True},
        ]
        if alert.old_price is not None:
            fields.append(
                {
                    "name": "Poprzednia cena",
                    "value": f"{alert.old_price:.2f} zł",
                    "inline": True,
                }
            )
        if alert.new_price is not None:
            fields.append(
                {"name": "Aktualna cena", "value": f"{alert.new_price:.2f} zł", "inline": True}
            )
        fields.append({"name": "Link", "value": alert.url, "inline": False})

        if alert.extra_fields:
            for key, value in alert.extra_fields.items():
                fields.append({"name": key, "value": value, "inline": True})

        embed = {
            "title": alert.title,
            "description": alert.message,
            "color": _DISCORD_COLORS.get(alert.kind, 0x95A5A6),
            "fields": fields,
            "footer": {"text": "Inteligentny Bot-Monitorujący • Portfolio"},
        }

        payload = {
            "username": "Price Tracker",
            "embeds": [embed],
        }

        response = self._session.post(webhook, json=payload, timeout=15)
        response.raise_for_status()
        logger.info("Wysłano alert Discord: %s", alert.title)
        return True

    def _send_telegram(self, alert: AlertPayload) -> bool:
        token = self._config.telegram_bot_token
        chat_id = self._config.telegram_chat_id
        if not token or not chat_id:
            logger.warning(
                "Brak telegram_bot_token/chat_id — alert tylko w logu: %s",
                alert.title,
            )
            return False

        lines = [
            f"<b>{self._escape_html(alert.title)}</b>",
            self._escape_html(alert.message),
            "",
            f"Produkt: {self._escape_html(alert.product_name)}",
        ]
        if alert.old_price is not None:
            lines.append(f"Poprzednia: {alert.old_price:.2f} zł")
        if alert.new_price is not None:
            lines.append(f"Aktualna: {alert.new_price:.2f} zł")
        lines.append(f'<a href="{alert.url}">Otwórz stronę</a>')

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        response = self._session.post(
            url,
            json={
                "chat_id": chat_id,
                "text": "\n".join(lines),
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        response.raise_for_status()
        logger.info("Wysłano alert Telegram: %s", alert.title)
        return True

    @staticmethod
    def _escape_html(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def close(self) -> None:
        self._session.close()
