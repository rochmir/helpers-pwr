"""Konfiguracja ze zmiennych środowiskowych (czytana na bieżąco — wygodne w testach) i czas.

Czas jest pobierany wyłącznie przez ``now()`` / ``today()``, żeby testy mogły go podmienić.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Warsaw")
DAILY_ATTEMPTS = 5         # prób na dobę na jedno urządzenie na każdym stanowisku (regulamin konkursu, §4.2)
DEVICE_TOLERANCE = 10      # domyślny sufit dla identycznych urządzeń (settings.device_tolerance, 1..50)
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"   # bez 0/O/1/I/L; kody rejestracyjne i tokeny trafień
PROMO_BONUS = 5            # dodatkowe próby za post lub story z oznaczeniem Samorządu i dkms_pl (kod od wolontariusza)
CUP_VOTE_BONUS = 10        # dodatkowe próby za udział w Pucharze Dawcy PWr (token typu potential), po udanym głosie
CUP_VOTE_BONUS_ACTUAL = 20  # to samo dla tokenu typu actual
# Terminy z regulaminów (Europe/Warsaw); nadpisywane zmiennymi CUP_DEADLINE i CONTEST_DEADLINE (RRRR-MM-DDTGG:MM).
DEFAULT_CUP_DEADLINE = "2026-12-11T16:30"       # koniec zliczania punktów w Pucharze Dawcy PWr (§6.1)
DEFAULT_CONTEST_DEADLINE = "2026-12-11T16:00"   # koniec zgłoszeń konkursowych (§5.4)
PASS_MINUTES = 30          # ważność przepustki na stoisko po zeskanowaniu kodu QR


def data_dir() -> Path:
    path = Path(os.environ.get("DATA_DIR", "./data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "dkms.db"


def admin_secret() -> str:
    return os.environ.get("ADMIN_SECRET", "").strip()


def public_url() -> str:
    return os.environ.get("PUBLIC_URL", "https://helpers-pwr.rupary.pl").strip().rstrip("/")


def legal_contact() -> str:
    return os.environ.get("LEGAL_CONTACT", "").strip()


def _deadline(name: str, default: str) -> datetime:
    """Termin z env (czas lokalny Europe/Warsaw, jeśli bez strefy); zła wartość = domyślny."""
    for raw in (os.environ.get(name, "").strip(), default):
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            continue
        return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt
    raise ValueError(name)


def cup_deadline() -> datetime:
    return _deadline("CUP_DEADLINE", DEFAULT_CUP_DEADLINE)


def contest_deadline() -> datetime:
    return _deadline("CONTEST_DEADLINE", DEFAULT_CONTEST_DEADLINE)


def code_ttl_minutes() -> int:
    try:
        return max(1, int(os.environ.get("CODE_TTL_MINUTES", "60")))
    except ValueError:
        return 60


def cookie_secure() -> bool:
    return os.environ.get("COOKIE_SECURE", "1").strip() != "0"


def secret_key() -> str:
    """``SECRET_KEY`` ze środowiska albo losowy klucz zapisany w ``DATA_DIR/secret_key``."""
    env = os.environ.get("SECRET_KEY", "").strip()
    if env:
        return env
    path = data_dir() / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(48)
    path.write_text(key, encoding="utf-8")
    os.chmod(path, 0o600)
    return key


# --- czas -----------------------------------------------------------------------
def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return iso(now())


def expiry_of(created_at: str) -> str:
    created = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return iso(created + timedelta(minutes=code_ttl_minutes()))


def warsaw_date(iso_ts: str) -> str:
    dt = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ).date().isoformat()


def today() -> str:
    """Bieżąca data w Europe/Warsaw (granica „dnia” dla limitów i podsumowań)."""
    return now().astimezone(TZ).date().isoformat()


MONTHS_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia",
              "września", "października", "listopada", "grudnia"]


def format_pl(dt: datetime, with_time: bool = True) -> str:
    """Data po polsku w strefie Warsaw, np. „1 listopada 2026, 14:30” albo „11 grudnia 2026”."""
    d = dt.astimezone(TZ)
    out = f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year}"
    return out + f", {d:%H:%M}" if with_time else out


def cup_closed() -> bool:
    return now() >= cup_deadline()


def cup_closed_message() -> str:
    d = cup_deadline().astimezone(TZ)
    return f"Zliczanie punktów zakończone {d.day} {MONTHS_GEN[d.month - 1]} {d.year} o {d:%H:%M}."


def day_bounds(date: str) -> tuple[str, str]:
    """Granice doby Europe/Warsaw o danej dacie (RRRR-MM-DD) jako znaczniki UTC ``[od, do)`` do porównań z ``*_at``."""
    start = datetime.fromisoformat(date).replace(tzinfo=TZ)
    # +36 h omija zmianę czasu, potem zerujemy godzinę lokalnie: północ następnego dnia
    nxt = (start + timedelta(hours=36)).replace(hour=0, minute=0, second=0, microsecond=0)
    return iso(start), iso(nxt)


def noon_iso(date: str) -> str:
    """Południe czasu Warsaw danej daty jako znacznik UTC (dla danych historycznych znanych tylko z daty)."""
    return iso(datetime.fromisoformat(date).replace(hour=12, tzinfo=TZ))
