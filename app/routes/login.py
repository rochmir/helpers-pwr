"""Logowanie personelu: jeden panel dla wszystkich, funkcje zależą od rangi konta (admin / wolontariusz)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .. import auth, db

router = APIRouter(prefix="/api/auth")


class LoginIn(BaseModel):
    login: str = Field(max_length=64)
    password: str = Field(max_length=256)


class BoothIn(BaseModel):
    booth_id: str = Field(max_length=40)


def _booth_view(conn: sqlite3.Connection, booth_id: str | None) -> dict | None:
    row = conn.execute("SELECT id, name FROM booths WHERE id=?", (booth_id,)).fetchone() if booth_id else None
    return {"id": row["id"], "name": row["name"]} if row else None


@router.post("/login")
def login(body: LoginIn, response: Response, conn: sqlite3.Connection = Depends(db.get_db)):
    name = body.login.strip().lower()
    key = "vol:" + name[:64]
    auth.throttle.check(key)
    account = auth.verify_login(conn, name, body.password)
    if account is None:
        auth.throttle.fail(key)
        raise HTTPException(401, "Błędny login lub hasło.")
    auth.throttle.reset(key)
    auth.set_staff_cookie(response, account["role"], {"login": name, "ph": account["ph"], "booth": None})
    return {"login": name, "role": account["role"], "booth": None}


@router.post("/logout")
def logout(response: Response):
    auth.clear_staff_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(staff: dict = Depends(auth.current_staff), conn: sqlite3.Connection = Depends(db.get_db)):
    return {"login": staff["login"], "role": staff["role"], "booth": _booth_view(conn, staff["booth"])}


@router.post("/booth")
def choose_booth(body: BoothIn, response: Response, staff: dict = Depends(auth.current_staff),
                 conn: sqlite3.Connection = Depends(db.get_db)):
    booth = _booth_view(conn, body.booth_id.strip().lower())
    if booth is None:
        raise HTTPException(404, "Wybierz stoisko z listy.")
    auth.set_staff_cookie(response, staff["role"], {"login": staff["login"], "ph": staff["ph"], "booth": booth["id"]})
    return {"login": staff["login"], "role": staff["role"], "booth": booth}
