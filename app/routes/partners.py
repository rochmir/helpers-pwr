"""Partnerzy (loga na certyfikatach i grafikach): pliki w DATA_DIR/partners, nazwy plików nadaje serwer."""
from __future__ import annotations

import base64
import binascii
import re
import secrets
import sqlite3
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .. import auth, config, db

router = APIRouter()
MAX_BYTES = 1_500_000
FILE_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp|svg)$")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "svg": "image/svg+xml"}
SVG_NS = "{http://www.w3.org/2000/svg}"
SVG_FORBIDDEN_TAGS = {"script", "foreignobject", "iframe", "embed", "object", "audio", "video"}
SVG_EXTERNAL_RE = re.compile(r"@import|url\(\s*[\"']?\s*(?!#)|javascript:", re.I)


class OrderIn(BaseModel):
    ids: list[int] = Field(max_length=200)


class PartnerIn(BaseModel):
    name: str = Field(max_length=80)
    filename: str = Field(max_length=120)
    data_base64: str = Field(max_length=2_100_000)


def partners_dir():
    path = config.data_dir() / "partners"
    path.mkdir(exist_ok=True)
    return path


def _svg_ok(raw: bytes) -> bool:
    """SVG bez skryptów, obsługi zdarzeń, foreignObject i odwołań na zewnątrz; z width i height na elemencie głównym."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    low = text.lower()
    if "<script" in low or "<!doctype" in low or "<!entity" in low or "<foreignobject" in low:
        return False
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return False
    if root.tag != SVG_NS + "svg" or not root.get("width") or not root.get("height"):
        return False
    for el in root.iter():
        if not isinstance(el.tag, str) or el.tag.rsplit("}", 1)[-1].lower() in SVG_FORBIDDEN_TAGS:
            return False
        for attr, value in el.attrib.items():
            name = attr.rsplit("}", 1)[-1].lower()
            if name.startswith("on") or (name == "href" and not value.strip().startswith("#")):
                return False
            if SVG_EXTERNAL_RE.search(value):
                return False
        if el.tag.endswith("style") and SVG_EXTERNAL_RE.search(el.text or ""):
            return False
    return True


def sniff(raw: bytes) -> str | None:
    """Rozszerzenie wg sygnatury pliku (nazwa i typ podane przez klienta nie mają znaczenia)."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    if b"<svg" in raw[:4096].lower() and _svg_ok(raw):
        return "svg"
    return None


@router.get("/api/partners")
def list_partners(conn: sqlite3.Connection = Depends(db.get_db)):
    return [{"id": r["id"], "name": r["name"], "url": f"/partners/{r['filename']}"}
            for r in conn.execute("SELECT id, name, filename FROM partners ORDER BY sort_order, id")]


@router.put("/api/admin/partners/order")
def order_partners(body: OrderIn, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    """Nowa kolejność partnerów (certyfikaty, grafiki, strony): lista musi zawierać każde id dokładnie raz."""
    with db.tx(conn):
        existing = sorted(r[0] for r in conn.execute("SELECT id FROM partners"))
        if sorted(body.ids) != existing:
            raise HTTPException(422, "Lista musi zawierać każdego partnera dokładnie raz.")
        for pos, pid in enumerate(body.ids, 1):
            conn.execute("UPDATE partners SET sort_order=? WHERE id=?", (pos, pid))
    return list_partners(conn)


@router.get("/partners/{filename}", include_in_schema=False)
def partner_file(filename: str):
    if not FILE_RE.match(filename):
        raise HTTPException(404, "Nie znaleziono pliku.")
    path = partners_dir() / filename
    if not path.is_file():
        raise HTTPException(404, "Nie znaleziono pliku.")
    return Response(path.read_bytes(), media_type=MEDIA_TYPES[filename.rsplit(".", 1)[1]])


@router.post("/api/admin/partners", status_code=201)
def add_partner(body: PartnerIn, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Podaj nazwę partnera.")
    try:
        raw = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "Niepoprawny plik.")
    if not raw or len(raw) > MAX_BYTES:
        raise HTTPException(422, "Plik może mieć do 1,5 MB.")
    ext = sniff(raw)
    if ext is None:
        raise HTTPException(422, "Dozwolone pliki: PNG, JPG, WebP albo bezpieczne SVG z width i height.")
    filename = f"{secrets.token_hex(16)}.{ext}"
    (partners_dir() / filename).write_bytes(raw)
    cur = conn.execute("INSERT INTO partners(name,filename,sort_order) "
                       "VALUES(?,?,(SELECT COALESCE(MAX(sort_order),0)+1 FROM partners))", (name, filename))
    return {"id": cur.lastrowid, "name": name, "url": f"/partners/{filename}"}


@router.delete("/api/admin/partners/{partner_id}")
def delete_partner(partner_id: int, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    row = conn.execute("SELECT filename FROM partners WHERE id=?", (partner_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Nie ma takiego partnera.")
    conn.execute("DELETE FROM partners WHERE id=?", (partner_id,))
    (partners_dir() / row["filename"]).unlink(missing_ok=True)
    return {"ok": True}
