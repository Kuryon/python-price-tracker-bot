"""Silnik pobierania stron (requests + BeautifulSoup)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from price_tracker.config import MonitorTarget

logger = logging.getLogger(__name__)

_PRICE_PATTERN = re.compile(r"[\d.,]+")


@dataclass
class PageSnapshot:
    """Wynik parsowania pojedynczej strony."""

    url: str
    price: float | None
    raw_price_text: str | None
    availability: str | None
    parse_error: str | None = None


class PageFetcher:
    """Pobiera HTML i wyciąga cenę oraz opcjonalnie dostępność."""

    def __init__(self, user_agent: str, timeout_seconds: int = 20) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
        self._timeout = timeout_seconds

    def fetch(self, target: MonitorTarget) -> PageSnapshot:
        """Pobiera stronę i parsuje dane. Nie rzuca wyjątków na zewnątrz."""
        try:
            response = self._session.get(target.url, timeout=self._timeout)
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.error("Błąd połączenia dla %s: %s", target.url, exc)
            return PageSnapshot(
                url=target.url,
                price=None,
                raw_price_text=None,
                availability=None,
                parse_error=str(exc),
            )

        try:
            return self._parse_html(target, response.text)
        except Exception as exc:  # noqa: BLE001 — odporność na zmianę struktury strony
            logger.error(
                "Błąd parsowania HTML dla %s: %s", target.url, exc, exc_info=True
            )
            return PageSnapshot(
                url=target.url,
                price=None,
                raw_price_text=None,
                availability=None,
                parse_error=str(exc),
            )

    def _parse_html(self, target: MonitorTarget, html: str) -> PageSnapshot:
        soup = BeautifulSoup(html, "html.parser")

        price_element = soup.select_one(target.price_selector)
        if price_element is None:
            raise ValueError(
                f"Nie znaleziono selektora ceny: '{target.price_selector}'"
            )

        raw_price = price_element.get_text(strip=True)
        price = parse_price(raw_price)

        availability: str | None = None
        if target.availability_selector:
            avail_el = soup.select_one(target.availability_selector)
            if avail_el is not None:
                availability = avail_el.get_text(strip=True).lower()

        return PageSnapshot(
            url=target.url,
            price=price,
            raw_price_text=raw_price,
            availability=availability,
        )

    def close(self) -> None:
        self._session.close()


def parse_price(text: str) -> float | None:
    """Wyciąga liczbę z tekstu typu '1 299,99 zł' lub '49.99'."""
    match = _PRICE_PATTERN.search(text.replace("\xa0", " ").replace(" ", ""))
    if not match:
        return None

    token = match.group(0)
    # Format PL: 1.299,99 → 1299.99
    if "," in token and "." in token:
        token = token.replace(".", "").replace(",", ".")
    elif "," in token:
        token = token.replace(",", ".")
    else:
        # Może być separator tysięcy: 1.299
        parts = token.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            token = token.replace(".", "")

    try:
        return float(token)
    except ValueError:
        return None
