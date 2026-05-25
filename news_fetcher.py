# -*- coding: utf-8 -*-
"""
news_fetcher.py — Fetcher CENTRALE del calendario economico per AleBot.

Gira su GitHub Actions (cron): scarica da Finnhub (primaria) con fallback FMP,
tiene solo gli eventi High-impact in USD/EUR/GBP e scrive 'news.json'.
TUTTI i bot leggono quel JSON via NEWS_SOURCE_URL: serve UNA SOLA chiave API
totale, indipendente dal numero di bot.

Le chiavi arrivano dalle variabili d'ambiente (GitHub Secrets):
    FINNHUB_API_KEY  (obbligatoria: sorgente primaria)
    FMP_API_KEY      (opzionale: fallback se Finnhub fallisce)

Comportamento di sicurezza:
  - se almeno una sorgente risponde (anche con lista vuota = nessuna news) -> scrive news.json
  - se TUTTE falliscono tecnicamente -> NON scrive (esce con codice 1) cosi' l'ultimo
    news.json valido resta intatto e i bot continuano sull'ultimo calendario noto.
"""
import os
import sys
import json
from datetime import datetime, timedelta, timezone

import requests

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()
FMP_API_KEY     = os.environ.get("FMP_API_KEY", "").strip()

OUT_FILE   = "news.json"
CURRENCIES = {"USD", "EUR", "GBP"}
# Finestra di lookahead: un po' piu' ampia (2 giorni) cosi' i bot vedono sempre
# gli eventi imminenti anche a cavallo della mezzanotte. Il bot ri-filtra a 24h.
DAYS_AHEAD = 2

# Country code -> valuta (Finnhub), identico al bot.
COUNTRY_TO_CURRENCY = {
    "US": "USD", "EU": "EUR", "UK": "GBP", "JP": "JPY",
    "CA": "CAD", "AU": "AUD", "NZ": "NZD", "CH": "CHF",
    "CN": "CNY", "HK": "HKD", "SG": "SGD", "MX": "MXN",
    "NO": "NOK", "SE": "SEK", "DK": "DKK", "DE": "EUR",
    "FR": "EUR", "IT": "EUR", "ES": "EUR", "RU": "RUB",
}


def _parse_dt(s):
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return None


def _finestra():
    today = datetime.now(timezone.utc).date()
    return today, today + timedelta(days=DAYS_AHEAD)


def _tieni(ev_time, impact, currency, now_utc, fine):
    if ev_time is None:
        return False
    if ev_time <= now_utc - timedelta(minutes=1):
        return False
    if ev_time.date() > fine:
        return False
    if str(impact).strip().capitalize() != "High":
        return False
    if str(currency).strip().upper() not in CURRENCIES:
        return False
    return True


def scarica_finnhub():
    """Ritorna list (anche vuota) oppure None su errore tecnico."""
    if not FINNHUB_API_KEY:
        print("Finnhub: chiave assente, salto.", file=sys.stderr)
        return None
    da, a = _finestra()
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"from": da.isoformat(), "to": a.isoformat(), "token": FINNHUB_API_KEY},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Finnhub: errore API: {e}", file=sys.stderr)
        return None
    raw = data.get("economicCalendar") if isinstance(data, dict) else None
    if raw is None:
        print(f"Finnhub: risposta inattesa: {data!r}", file=sys.stderr)
        return None
    now_utc = datetime.now(timezone.utc)
    _, fine = _finestra()
    out = []
    for ev in raw:
        if not isinstance(ev, dict):
            continue
        t = _parse_dt(ev.get("time", ""))
        country = str(ev.get("country", "")).upper().strip()
        currency = COUNTRY_TO_CURRENCY.get(country, country)
        impact = ev.get("impact", "")
        if not _tieni(t, impact, currency, now_utc, fine):
            continue
        out.append({
            "time": t.isoformat(),
            "title": str(ev.get("event", "")).strip() or "Evento sconosciuto",
            "impact": "High",
            "currency": currency,
        })
    return out


def scarica_fmp():
    """Fallback. Ritorna list (anche vuota) oppure None su errore tecnico."""
    if not FMP_API_KEY:
        print("FMP: chiave assente, salto.", file=sys.stderr)
        return None
    da, a = _finestra()
    try:
        resp = requests.get(
            "https://financialmodelingprep.com/api/v3/economic_calendar",
            params={"from": da.isoformat(), "to": a.isoformat(), "apikey": FMP_API_KEY},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"FMP: errore API: {e}", file=sys.stderr)
        return None
    if not isinstance(data, list):
        print(f"FMP: risposta inattesa: {data!r}", file=sys.stderr)
        return None
    now_utc = datetime.now(timezone.utc)
    _, fine = _finestra()
    out = []
    for ev in data:
        if not isinstance(ev, dict):
            continue
        t = _parse_dt(ev.get("date", ""))
        currency = str(ev.get("currency", "")).strip().upper()
        impact = ev.get("impact", "")
        if not _tieni(t, impact, currency, now_utc, fine):
            continue
        out.append({
            "time": t.isoformat(),
            "title": str(ev.get("event", "")).strip() or "Evento sconosciuto",
            "impact": "High",
            "currency": currency,
        })
    return out


def main():
    eventi = scarica_finnhub()
    fonte = "finnhub"
    if eventi is None:
        print("Finnhub fallito -> fallback FMP.", file=sys.stderr)
        eventi = scarica_fmp()
        fonte = "fmp"
    if eventi is None:
        print("ERRORE: tutte le sorgenti hanno fallito. news.json NON aggiornato.", file=sys.stderr)
        sys.exit(1)

    # dedup + ordina
    seen, dedup = set(), []
    for ev in sorted(eventi, key=lambda x: x["time"]):
        k = (ev["time"], ev["currency"], ev["impact"], ev["title"])
        if k not in seen:
            seen.add(k)
            dedup.append(ev)

    payload = {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "source": fonte,
        "events": dedup[:50],
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"OK: scritti {len(payload['events'])} eventi in {OUT_FILE} (fonte: {fonte}).")


if __name__ == "__main__":
    main()
