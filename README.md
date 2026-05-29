# Inteligentny Bot-Monitorujący (Price & Availability Tracker)

Bot śledzący **zmiany cen** i **dostępność** na stronach WWW, z natychmiastowymi alertami na **Discord** (Embeds) lub **Telegram**.

## Funkcje

- Architektura OOP: klasy, `dataclasses`, pełne type hinting, `logging`
- Pobieranie: `requests` + `BeautifulSoup`, niestandardowy User-Agent
- Pamięć stanu: SQLite (brak spamu przy tej samej cenie)
- Powiadomienia: Discord Webhook (kolorowe embedy) lub Telegram Bot API
- Odporność: błędy sieci i zmiana struktury HTML — log + kolejna próba
- CLI (`argparse`) lub `config.json`
- **Tryb DEMO**: bez URL uruchamia lokalny sklep testowy z losową ceną co ~15 s

## Instalacja

```bash
cd "Magik od Excela"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Szybki start — DEMO

1. Utwórz webhook w Discord: Ustawienia kanału → Integracje → Webhooki.
2. Uruchom (bez podawania URL):

```bash
python -m price_tracker.main --discord-webhook "https://discord.com/api/webhooks/..."
```

Bot wystartuje serwer na `http://127.0.0.1:8765/`, będzie logował odczyty w konsoli i wysyłał embedy przy zmianie ceny.

## Produkcja — własny sklep

```bash
python -m price_tracker.main ^
  --url "https://twoj-sklep.pl/produkt/123" ^
  --price-selector ".product-price" ^
  --name "Konsola XYZ" ^
  --target-price 1999 ^
  --interval 30 ^
  --discord-webhook "https://discord.com/api/webhooks/..."
```

Skopiuj `config.example.json` → `config.json` i uzupełnij pola.

## Telegram

```bash
python -m price_tracker.main --channel telegram ^
  --telegram-token "BOT_TOKEN" ^
  --telegram-chat-id "CHAT_ID" ^
  --url "https://..."
```

## Struktura projektu

```
price_tracker/
  __init__.py
  main.py          # CLI i punkt wejścia
  config.py        # Konfiguracja JSON + dataclasses
  database.py      # SQLite — poprzednie ceny
  fetcher.py       # requests + BeautifulSoup
  notifier.py      # Discord / Telegram
  monitor.py       # Logika alertów
  demo_server.py   # Wbudowany sklep testowy (threading + http.server)
```
