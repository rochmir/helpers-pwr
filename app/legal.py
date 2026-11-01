"""Dokumenty prawne (regulaminy, polityka prywatności): treści w bazie, edytowane z panelu admina.

Treść to Markdown renderowany po stronie serwera bez surowego HTML (``js-default``: html=False, bez linkify),
więc edytor dokumentu nie może wstrzyknąć skryptu. Zapis treści lub tytułu podbija wersję, a datę ostatniej zmiany
ustawia wyłącznie serwer.
"""
from __future__ import annotations

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


def seed(conn: sqlite3.Connection) -> None:
    """Wstawia brakujące dokumenty bazowe z ``app/legal/*.md`` (istniejących nie rusza)."""
    now = config.now_iso()
    for sort, slug in enumerate(BASE_SLUGS, 1):
        if conn.execute("SELECT 1 FROM legal_documents WHERE slug=?", (slug,)).fetchone():
            continue
        title, body = split_title((LEGAL_DIR / f"{slug}.md").read_text(encoding="utf-8"))
        conn.execute("INSERT INTO legal_documents(slug,title,body_md,published,sort,version,created_at,updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?)", (slug, title, body, 1, sort, 1, now, now))
        log.info("Dodano dokument %s", slug)


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
