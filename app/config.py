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
DAILY_ATTEMPTS = 5
REGISTER_BONUS = 10        # dodatkowe próby za rejestrację dawcy (nie wygasają o północy)
REGISTER_BONUS_ACTUAL = 20   # dawca faktyczny (legitymacja)
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


def code_ttl_minutes() -> int:
    try:
        return max(1, int(os.environ.get("CODE_TTL_MINUTES", "60")))
    except ValueError:
        return 60


def cookie_secure() -> bool:
    return os.environ.get("COOKIE_SECURE", "1").strip() != "0"


def dev_no_cache() -> bool:
    """Tryb lokalnego podglądu: statyki bez cache'u (zmiany w CSS/JS widać po odświeżeniu)."""
    return os.environ.get("DEV_NO_CACHE", "").strip() == "1"


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
