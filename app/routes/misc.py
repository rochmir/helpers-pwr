"""Konfiguracja publiczna, lista stoisk, kod QR, healthcheck."""
from __future__ import annotations

import io
import sqlite3

import segno
from fastapi import APIRouter, Depends, HTTPException, Response

from .. import captcha, config, db

router = APIRouter()


@router.get("/healthz")
def healthz():
    return {"ok": True}


@router.get("/api/config")
def get_config(conn: sqlite3.Connection = Depends(db.get_db)):
    return {"turnstile_site_key": captcha.site_key() if captcha.enabled() else None,
            "public_url": config.public_url(), "facebook_url": db.get_setting(conn, "facebook_url") or None}


@router.get("/api/qr.svg")
def qr_svg(path: str):
    if not path.startswith("/") or path.startswith("//") or len(path) > 200:
        raise HTTPException(400, "Niepoprawna ścieżka.")
    buf = io.BytesIO()
    segno.make(config.public_url() + path, error="m").save(buf, kind="svg", scale=8, border=2)
    return Response(buf.getvalue(), media_type="image/svg+xml")


@router.get("/api/booths")
def booth_list(conn: sqlite3.Connection = Depends(db.get_db)):
    """Publiczna lista stoisk (id i nazwa) do wyboru przy logowaniu wolontariusza."""
    return [{"id": r["id"], "name": r["name"]} for r in conn.execute("SELECT id, name FROM booths ORDER BY name, id")]


@router.get("/api/booths/public")
def booths_public(conn: sqlite3.Connection = Depends(db.get_db)):
    """Publiczne terminy stanowisk (bez genotypów i tokenów). Stoiska po ``date_to`` są ukryte."""
    today = config.today()
    rows = conn.execute(
        "SELECT building, name, date_from, date_to FROM booths WHERE date_to IS NULL OR date_to >= ? "
        "ORDER BY date_from IS NULL, date_from, building, name", (today,))
    return {"booths": [{"building": r["building"], "name": r["name"], "date_from": r["date_from"],
                        "date_to": r["date_to"]} for r in rows], "hours": db.get_booth_hours(conn)}
