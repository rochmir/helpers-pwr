"""Strony statyczne: wersjonowane adresy statyk, ikony, podstawianie `{{NAZWA}}` w szablonach."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

STATIC_DIR = Path(__file__).with_name("static")


def _asset_version() -> str:
    """Skrót zawartości katalogu static — zmienia się przy każdej zmianie plików (cache-busting)."""
    h = hashlib.sha256()
    for f in sorted(STATIC_DIR.rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(STATIC_DIR)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


ASSET_VERSION = _asset_version()
VERSIONED_PREFIX = f"/static/v/{ASSET_VERSION}/"
# Ikony wstrzykiwane przed </head>; href zostaje przepisane na wersjonowany prefiks.
FAVICON_LINKS = ('<link rel="icon" href="/static/brand/favicon.svg" type="image/svg+xml">'
                 '<link rel="icon" href="/static/brand/favicon-32.png" sizes="32x32" type="image/png">'
                 '<link rel="apple-touch-icon" href="/static/brand/apple-touch-icon.png">')
_SLOT_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


def render(filename: str, slots: dict[str, str] | None = None) -> HTMLResponse:
    """Strona z ``static/`` z ikonami i wersjonowanymi statykami. ``slots``: gotowy HTML pod ``{{NAZWA}}``
    (podstawiany jednym przebiegiem, więc wstawiona treść nie jest ponownie interpretowana)."""
    path = STATIC_DIR / filename
    if not path.is_file():
        raise HTTPException(404, "Nie znaleziono strony.")
    html = path.read_text(encoding="utf-8")
    html = html.replace("</head>", FAVICON_LINKS + "</head>")
    html = html.replace('src="/static/', f'src="{VERSIONED_PREFIX}').replace('href="/static/', f'href="{VERSIONED_PREFIX}')
    if slots is not None:
        html = _SLOT_RE.sub(lambda m: slots.get(m.group(1), m.group(0)), html)
    return HTMLResponse(html)
