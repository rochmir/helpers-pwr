"""Dokumenty prawne (regulaminy, polityka prywatności): treści w bazie, edytowane z panelu admina.

Treść to Markdown renderowany po stronie serwera bez surowego HTML (``js-default``: html=False, bez linkify),
więc edytor dokumentu nie może wstrzyknąć skryptu. Zapis treści lub tytułu podbija wersję, a datę ostatniej zmiany
ustawia wyłącznie serwer.
"""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from markdown_it import MarkdownIt

from . import config

log = logging.getLogger("helpersi.legal")

LEGAL_DIR = Path(__file__).with_name("legal")
# Dokumenty bazowe (seed z plików): nie można ich usunąć ani ukryć. Kolejność = domyślna kolejność na liście.
BASE_SLUGS = ("regulamin-konkursu", "regulamin-pucharu", "polityka-prywatnosci")
# Zmiana któregokolwiek z nich wymaga ponownej zgody w symulatorze.
CONSENT_SLUGS = ("regulamin-konkursu", "polityka-prywatnosci")
SLUG_RE = re.compile(r"^[a-z0-9-]{3,60}$")
MAX_BODY_BYTES = 200_000
PLACEHOLDER = "[do uzupełnienia]"

_md = MarkdownIt("js-default")


def render_markdown(body_md: str) -> str:
    """HTML z Markdowna (surowy HTML w treści jest zamieniany na tekst) z podstawionym ``{{CONTACT}}``."""
    html = _md.render(body_md or "")
    return html.replace("{{CONTACT}}", escape(config.legal_contact() or PLACEHOLDER))


def split_title(text: str) -> tuple[str, str]:
    """Tytuł = pierwszy nagłówek ``# ``, ciało = reszta bez niego (i bez pustych linii na początku)."""
    lines = text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return line[2:].strip(), "\n".join(lines[:i] + lines[i + 1:]).strip("\n") + "\n"
        if line.strip():
            break
    raise ValueError("Brak nagłówka # na początku dokumentu.")


# SHA-256 ciała (po ``split_title``) poprzednich wersji seedu: dokument w bazie z dokładnie taką treścią nie był
# zmieniany w panelu, więc przy starcie dostaje nową treść seedu (wersja +1). Wartości z commita 463c281 (seed v1) i kolejnych wersji seedu.
PREVIOUS_SEED_SHA256 = {
    "regulamin-konkursu": ("fb663c80d697b5a038ce8d7204d04654bb79224c0bbd7945dfea6f978fcec72b",),
    "regulamin-pucharu": ("dc380fa703839da27b8b7d1f0975419f98757a3473b6dd1d817429b997f44da3",),
    "polityka-prywatnosci": ("fca77a29550101ebe375e9186ea6f29f46799aba5441d931ba37f1bf7399b956",
                             "2bff634c64ab4280617fa265e9bad38453060685107aabfc65e541dc4687cf15"),
}
SEED_UPDATE_AUTHOR = "system"
# Wersja treści seedu (pliki app/legal/*.md). Baza z niższą wartością w settings.legal_seed_version dostaje jednorazowo
# treść z plików (v3: bez fingerprintingu, trzy kategorie głosu w Pucharze, kod QR ważny 60 s).
LEGAL_SEED_VERSION = 3
LEGAL_SEED_KEY = "legal_seed_version"


def _update_untouched(conn: sqlite3.Connection, slug: str, title: str, body: str) -> None:
    """Podmienia treść dokumentu, jeśli w bazie jest jeszcze jedna z poprzednich wersji seedu. Zapis jak w panelu:
    kopia starej wersji w ``legal_document_versions``, wersja +1, ``updated_at`` teraz. Dokument zmieniony ręcznie
    (inny hash) zostaje nietknięty, a drugi start nic nie zmienia, bo hash nowej treści nie jest na liście."""
    from . import db
    with db.tx(conn):
        row = conn.execute("SELECT title, body_md, version FROM legal_documents WHERE slug=?", (slug,)).fetchone()
        if row is None or hashlib.sha256(row["body_md"].encode()).hexdigest() not in PREVIOUS_SEED_SHA256.get(slug, ()):
            return
        now = config.now_iso()
        conn.execute("INSERT INTO legal_document_versions(slug,version,title,body_md,saved_at,saved_by) VALUES(?,?,?,?,?,?)",
                     (slug, row["version"], row["title"], row["body_md"], now, SEED_UPDATE_AUTHOR))
        conn.execute("UPDATE legal_documents SET title=?, body_md=?, version=?, updated_at=? WHERE slug=?",
                     (title, body, row["version"] + 1, now, slug))
        log.info("Zaktualizowano dokument %s do wersji %s", slug, row["version"] + 1)


def seed(conn: sqlite3.Connection) -> None:
    """Wstawia brakujące dokumenty bazowe z ``app/legal/*.md``; istniejące zmienia tylko, gdy nadal mają treść
    poprzedniej wersji seedu (``PREVIOUS_SEED_SHA256``)."""
    now = config.now_iso()
    for sort, slug in enumerate(BASE_SLUGS, 1):
        if conn.execute("SELECT 1 FROM legal_documents WHERE slug=?", (slug,)).fetchone():
            title, body = split_title((LEGAL_DIR / f"{slug}.md").read_text(encoding="utf-8"))
            _update_untouched(conn, slug, title, body)
            continue
        title, body = split_title((LEGAL_DIR / f"{slug}.md").read_text(encoding="utf-8"))
        conn.execute("INSERT INTO legal_documents(slug,title,body_md,published,sort,version,created_at,updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?)", (slug, title, body, 1, sort, 1, now, now))
        log.info("Dodano dokument %s", slug)
    upgrade_seed_version(conn)


def upgrade_seed_version(conn: sqlite3.Connection) -> None:
    """Jednorazowe (idempotentne) podniesienie dokumentów bazowych do treści z plików seedu v3: stara treść trafia do
    ``legal_document_versions`` (autor „system”), wersja +1, ``updated_at`` teraz, więc symulator poprosi o ponowną zgodę.
    Po ustawieniu flagi późniejsze edycje z panelu admina nie są nadpisywane. Świeża baza: treść już zgodna, tylko flaga."""
    from . import db
    try:
        current = int(db.get_setting(conn, LEGAL_SEED_KEY, "0") or 0)
    except ValueError:
        current = 0
    if current >= LEGAL_SEED_VERSION:
        return
    with db.tx(conn):
        for slug in BASE_SLUGS:
            row = conn.execute("SELECT title, body_md, version FROM legal_documents WHERE slug=?", (slug,)).fetchone()
            if row is None:
                continue
            title, body = split_title((LEGAL_DIR / f"{slug}.md").read_text(encoding="utf-8"))
            if (row["title"], row["body_md"]) == (title, body):
                continue
            now = config.now_iso()
            conn.execute("INSERT OR IGNORE INTO legal_document_versions(slug,version,title,body_md,saved_at,saved_by) "
                         "VALUES(?,?,?,?,?,?)", (slug, row["version"], row["title"], row["body_md"], now, SEED_UPDATE_AUTHOR))
            conn.execute("UPDATE legal_documents SET title=?, body_md=?, version=?, updated_at=? WHERE slug=?",
                         (title, body, row["version"] + 1, now, slug))
            log.info("Podniesiono dokument %s do treści seedu v%s (wersja %s)", slug, LEGAL_SEED_VERSION, row["version"] + 1)
        db.set_setting(conn, LEGAL_SEED_KEY, str(LEGAL_SEED_VERSION))


def format_updated(iso_ts: str) -> str:
    """„1 listopada 2026, 14:30” w strefie Europe/Warsaw."""
    dt = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return config.format_pl(dt)


def published(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT slug,title,updated_at,version FROM legal_documents WHERE published=1 "
                        "ORDER BY sort, slug").fetchall()


def consent_updated_at(conn: sqlite3.Connection) -> str | None:
    """Najpóźniejsza zmiana regulaminu konkursu lub polityki prywatności (do ponownej zgody w symulatorze)."""
    marks = ",".join("?" * len(CONSENT_SLUGS))
    return conn.execute(f"SELECT MAX(updated_at) FROM legal_documents WHERE slug IN ({marks})", CONSENT_SLUGS).fetchone()[0]
