"""Aplikacja FastAPI: routery, nagłówki bezpieczeństwa, strony statyczne."""
from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import captcha, config, db, pages
from .pages import STATIC_DIR, VERSIONED_PREFIX
from .routes import admin, admin_test, donor, game, legal, login, misc, partners, stats, volunteer

log = logging.getLogger("helpersi")

CSP = ("default-src 'self'; script-src 'self' https://challenges.cloudflare.com; "
       "frame-src https://challenges.cloudflare.com; img-src 'self' data: blob:; "
       "style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


async def _rotate_salt_hourly():
    """Sól dobowa rotuje także bez ruchu: klucz urządzenia znika następnego dnia, nawet po zakończeniu akcji."""
    while True:
        await asyncio.sleep(3600)
        try:
            await asyncio.to_thread(db.rotate_device_salt)
        except Exception:
            log.exception("Rotacja soli dobowej nie powiodła się.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    if not captcha.enabled():
        log.warning("Turnstile wyłączony (brak TURNSTILE_SITE_KEY / TURNSTILE_SECRET_KEY).")
    if not config.admin_secret():
        log.warning("Brak ADMIN_SECRET — konto awaryjne admin jest niedostępne.")
    if not config.legal_contact():
        log.warning("Brak LEGAL_CONTACT, dokumenty prawne pokażą „[do uzupełnienia]” w miejscu kontaktu.")
    db.rotate_device_salt()
    rotation = asyncio.create_task(_rotate_salt_hourly())
    yield
    rotation.cancel()


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
    elif request.url.path.startswith(VERSIONED_PREFIX):
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


for module in (misc, game, login, volunteer, donor, stats, partners, admin, admin_test, legal):
    app.include_router(module.router)
app.include_router(legal.admin_router)

# --- strony ---------------------------------------------------------------------
PAGES = {"/": "index.html", "/graj": "graj.html", "/login": "login.html", "/potwierdz": "potwierdz.html",
         "/statystyki": "statystyki.html", "/puchar": "puchar.html"}


def _page(filename: str):
    def handler():
        return pages.render(filename)
    return handler


for url, filename in PAGES.items():
    app.add_api_route(url, _page(filename), methods=["GET"], include_in_schema=False)


@app.get("/bitwa", include_in_schema=False)
def old_battle():
    return RedirectResponse("/puchar", status_code=301)


@app.get("/admin", include_in_schema=False)
@app.get("/wolontariusz", include_in_schema=False)
def old_panels():
    return RedirectResponse("/login", status_code=302)


_stoisko = _page("stoisko.html")


# Przeglądarki i systemy często pytają o /favicon.ico wprost.
@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "brand" / "favicon-32.png", media_type="image/png")


@app.get("/stoisko/{booth_id}", include_in_schema=False)
def stoisko(booth_id: str):
    if not re.fullmatch(r"[a-z0-9]{1,20}", booth_id):
        raise HTTPException(404, "Nie znaleziono strony.")
    return _stoisko()


# Statyki z wersją w ścieżce (strony HTML odwołują się tylko do nich); stary hash też działa,
# ale dostaje bieżące pliki — po przebudowie nowe strony i tak wskazują nowy hash.
app.mount("/static/v/{version}", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static_v")
app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")
