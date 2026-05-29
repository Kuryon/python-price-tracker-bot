"""Wbudowany serwer demo — symulacja sklepu z losową ceną."""

from __future__ import annotations

import logging
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEMO_PRODUCT_NAME = "Laptop Pro X (DEMO)"


class _DemoStoreState:
    """Współdzielony stan ceny w pamięci (wątek serwera)."""

    def __init__(self) -> None:
        self.price: float = round(random.uniform(899.0, 1599.0), 2)
        self._lock = threading.Lock()
        self._last_change = time.monotonic()

    def maybe_tick(self, min_interval: float = 12.0, max_interval: float = 18.0) -> None:
        """Losowa zmiana ceny co kilkanaście sekund."""
        with self._lock:
            now = time.monotonic()
            if now - self._last_change < random.uniform(min_interval, max_interval):
                return
            delta = random.choice([-1, 1]) * random.uniform(30.0, 120.0)
            self.price = max(499.0, min(1999.0, round(self.price + delta, 2)))
            self._last_change = now
            logger.info("[DEMO] Nowa cena w sklepie: %.2f zł", self.price)

    @property
    def in_stock(self) -> bool:
        return True


class DemoHTTPHandler(BaseHTTPRequestHandler):
    """Obsługa żądań do fikcyjnego sklepu."""

    store_state: ClassVar[_DemoStoreState]

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        # Wycisz domyślny log http.server — używamy logging
        logger.debug("Demo HTTP: " + format, *args)

    def do_GET(self) -> None:  # noqa: N802
        self.store_state.maybe_tick()
        price = self.store_state.price
        html = f"""<!DOCTYPE html>
<html lang="pl">
<head><meta charset="utf-8"><title>Sklep Demo</title></head>
<body>
  <h1>{DEMO_PRODUCT_NAME}</h1>
  <p class="price">{price:.2f} zł</p>
  <p class="availability">Produkt dostępny</p>
  <p><em>Serwer demo — cena zmienia się losowo co ~15 s.</em></p>
</body>
</html>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DemoServer:
    """Uruchamia mini-serwer HTTP w osobnym wątku."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        self._host = host
        self._port = port
        self._state = _DemoStoreState()
        self._thread: threading.Thread | None = None
        self._httpd: HTTPServer | None = None

    @property
    def product_url(self) -> str:
        return f"http://{self._host}:{self._port}/"

    def start(self) -> None:
        """Start serwera w tle."""
        handler = DemoHTTPHandler
        handler.store_state = self._state

        self._httpd = HTTPServer((self._host, self._port), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="demo-http-server",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Serwer DEMO uruchomiony: %s (cena zmienia się losowo)",
            self.product_url,
        )

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            logger.info("Serwer DEMO zatrzymany")
