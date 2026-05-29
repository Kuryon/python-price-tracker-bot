"""Logika monitorowania — porównanie stanów i decyzja o alercie."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from price_tracker.config import AppConfig, MonitorTarget
from price_tracker.database import StateDatabase, StoredSnapshot
from price_tracker.fetcher import PageFetcher, PageSnapshot
from price_tracker.notifier import AlertKind, AlertPayload, NotificationService

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Wynik pojedynczego sprawdzenia."""

    target_name: str
    url: str
    price: float | None
    alerted: bool
    reason: str


class PriceMonitor:
    """Główny silnik monitorujący — pętla sprawdzeń z anty-spamem."""

    def __init__(
        self,
        config: AppConfig,
        fetcher: PageFetcher,
        database: StateDatabase,
        notifier: NotificationService,
    ) -> None:
        self._config = config
        self._fetcher = fetcher
        self._db = database
        self._notifier = notifier
        self._running = False

    def run_forever(self) -> None:
        """Nieskończona pętla monitorowania (Ctrl+C aby zatrzymać)."""
        self._running = True
        interval = self._config.poll_interval_seconds
        logger.info(
            "Monitorowanie %d cel(ów), interwał %d s",
            len(self._config.targets),
            interval,
        )

        while self._running:
            for target in self._config.targets:
                result = self.check_target(target)
                self._log_check_result(result)

            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                logger.info("Zatrzymano przez użytkownika (Ctrl+C)")
                self._running = False
                break

    def check_target(self, target: MonitorTarget) -> CheckResult:
        """Jedno sprawdzenie URL — porównanie z bazą i ewentualny alert."""
        snapshot = self._fetcher.fetch(target)

        if snapshot.parse_error:
            return CheckResult(
                target_name=target.name,
                url=target.url,
                price=None,
                alerted=False,
                reason=f"Błąd: {snapshot.parse_error}",
            )

        stored = self._db.get_snapshot(target.url)
        alerted, reason = self._evaluate_and_notify(target, snapshot, stored)

        self._db.save_snapshot(
            target.url,
            last_price=snapshot.price,
            last_availability=snapshot.availability,
            last_notified_price=(
                snapshot.price if alerted else (stored.last_notified_price if stored else None)
            ),
        )

        return CheckResult(
            target_name=target.name,
            url=target.url,
            price=snapshot.price,
            alerted=alerted,
            reason=reason,
        )

    def _evaluate_and_notify(
        self,
        target: MonitorTarget,
        current: PageSnapshot,
        stored: StoredSnapshot | None,
    ) -> tuple[bool, str]:
        price = current.price
        if price is None:
            return False, "Nie udało się odczytać ceny"

        # Alert o dostępności (np. ogłoszenie wróciło na listę)
        if target.availability_selector and current.availability:
            avail_alerted = self._check_availability_change(
                target, current, stored
            )
            if avail_alerted:
                return True, "Wysłano alert o zmianie dostępności"

        previous = stored.last_price if stored else None
        last_notified = stored.last_notified_price if stored else None

        # Pierwsze uruchomienie — zapis bez alertu (unikamy spamu)
        if previous is None:
            logger.info(
                "Pierwszy odczyt [%s]: %.2f zł — zapisano bazę, bez alertu",
                target.name,
                price,
            )
            return False, f"Pierwszy odczyt: {price:.2f} zł"

        # Brak zmiany
        if abs(price - previous) < 0.01:
            return False, f"Cena bez zmian: {price:.2f} zł"

        # Anty-spam: nie powtarzaj alertu dla tej samej ceny
        if last_notified is not None and abs(price - last_notified) < 0.01:
            return False, "Ta cena była już zgłoszona"

        kind, title, message = self._build_alert_message(
            target, previous, price
        )

        alert = AlertPayload(
            title=title,
            message=message,
            product_name=target.name,
            url=target.url,
            old_price=previous,
            new_price=price,
            kind=kind,
        )

        sent = self._notifier.send(alert)
        if sent:
            logger.info(
                "ALERT [%s]: %.2f → %.2f zł (%s)",
                target.name,
                previous,
                price,
                kind.value,
            )
            return True, f"Wysłano alert: {previous:.2f} → {price:.2f} zł"

        return False, "Wykryto zmianę, ale nie wysłano (brak webhooka?)"

    def _check_availability_change(
        self,
        target: MonitorTarget,
        current: PageSnapshot,
        stored: StoredSnapshot | None,
    ) -> bool:
        prev_avail = stored.last_availability if stored else None
        new_avail = current.availability
        if prev_avail is None or new_avail == prev_avail:
            return False

        in_stock_phrase = target.availability_in_stock_text.lower()
        now_in_stock = in_stock_phrase in new_avail
        was_in_stock = in_stock_phrase in (prev_avail or "")

        if now_in_stock and not was_in_stock:
            alert = AlertPayload(
                title="Produkt dostępny",
                message="Status dostępności się zmienił — produkt jest ponownie dostępny.",
                product_name=target.name,
                url=target.url,
                old_price=stored.last_price if stored else None,
                new_price=current.price,
                kind=AlertKind.AVAILABILITY,
                extra_fields={"Status": new_avail},
            )
            return self._notifier.send(alert)

        return False

    def _build_alert_message(
        self,
        target: MonitorTarget,
        old_price: float,
        new_price: float,
    ) -> tuple[AlertKind, str, str]:
        if target.target_price is not None and new_price <= target.target_price:
            return (
                AlertKind.TARGET_REACHED,
                "Cel cenowy osiągnięty",
                (
                    f"Cena spadła do {new_price:.2f} zł "
                    f"(cel: {target.target_price:.2f} zł)."
                ),
            )

        if new_price < old_price:
            diff = old_price - new_price
            pct = (diff / old_price) * 100 if old_price else 0
            return (
                AlertKind.PRICE_DROP,
                "Spadek ceny",
                f"Cena spadła o {diff:.2f} zł ({pct:.1f}%). Sprawdź ofertę.",
            )

        return (
            AlertKind.PRICE_CHANGE,
            "Zmiana ceny",
            f"Cena wzrosła z {old_price:.2f} zł do {new_price:.2f} zł.",
        )

    @staticmethod
    def _log_check_result(result: CheckResult) -> None:
        status = "ALERT" if result.alerted else "OK"
        price_str = f"{result.price:.2f} zł" if result.price is not None else "—"
        logger.info(
            "[%s] %s | %s | %s",
            status,
            result.target_name,
            price_str,
            result.reason,
        )

    def stop(self) -> None:
        self._running = False
