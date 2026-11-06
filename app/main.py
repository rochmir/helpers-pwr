"""Aplikacja FastAPI: routery, nagłówki bezpieczeństwa, strony statyczne."""
from __future__ import annotations

import hashlib
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import captcha, config, db
from .routes import admin, admin_test, donor, game, misc, raffle, stats, volunteer

log = logging.getLogger("helpersi")
STATIC_DIR = Path(__file__).with_name("static")

CSP = ("default-src 'self'; script-src 'self' https://challenges.cloudflare.com; "
       "frame-src https://challenges.cloudflare.com; img-src 'self' data: blob:; "
       "style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    if not captcha.enabled():
        log.warning("Turnstile wyłączony (brak TURNSTILE_SITE_KEY / TURNSTILE_SECRET_KEY).")
    if not config.admin_secret():
        log.warning("Brak ADMIN_SECRET — logowanie admina jest niemożliwe.")
    yield


app = FastAPI(title="helpersi-pwr", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    is_api = request.url.path.startswith("/api/")
    if is_api and request.method in MUTATING and \
            not request.headers.get("content-type", "").lower().startswith("application/json"):
        response = JSONResponse({"detail": "Wymagany nagłówek Content-Type: application/json."}, status_code=415)
    else:
        response = await call_next(request)
    if is_api:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    elif request.url.path.startswith(VERSIONED_PREFIX) and not config.dev_no_cache():
        # Adres zawiera hash zawartości statyk — można cache'ować na stałe.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        # Strony i statyki: zawsze rewalidacja (ETag), żeby Cloudflare/przeglądarka nie trzymały starych wersji.
        response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = CSP
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    loc = [str(p) for p in exc.errors()[0]["loc"] if p not in ("body", "query")] if exc.errors() else []
    field = f" w polu „{'.'.join(loc)}”" if loc else ""
    return JSONResponse({"detail": f"Niepoprawne dane{field}."}, status_code=422)


for module in (misc, game, volunteer, donor, stats, admin, raffle, admin_test):
    app.include_router(module.router)

# --- strony ---------------------------------------------------------------------
PAGES = {"/": "index.html", "/graj": "graj.html", "/wolontariusz": "wolontariusz.html",
         "/potwierdz": "potwierdz.html", "/statystyki": "statystyki.html", "/admin": "admin.html"}


def _page(filename: str):
    def handler():
        path = STATIC_DIR / filename
        if not path.is_file():
            raise HTTPException(404, "Nie znaleziono strony.")
        html = path.read_text(encoding="utf-8")
        html = html.replace('src="/static/', f'src="{VERSIONED_PREFIX}').replace('href="/static/', f'href="{VERSIONED_PREFIX}')
        return HTMLResponse(html)
    return handler


for url, filename in PAGES.items():
    app.add_api_route(url, _page(filename), methods=["GET"], include_in_schema=False)

_stoisko = _page("stoisko.html")


@app.get("/stoisko/{booth_id}", include_in_schema=False)
def stoisko(booth_id: str):
    if not re.fullmatch(r"[a-z0-9]{1,20}", booth_id):
        raise HTTPException(404, "Nie znaleziono strony.")
    return _stoisko()


# Statyki z wersją w ścieżce (strony HTML odwołują się tylko do nich); stary hash też działa,
# ale dostaje bieżące pliki — po przebudowie nowe strony i tak wskazują nowy hash.
app.mount("/static/v/{version}", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static_v")
app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")
