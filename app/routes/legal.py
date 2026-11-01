"""Dokumenty prawne: strony publiczne (/dokumenty), API publiczne i panel admina (/api/admin/legal)."""
from __future__ import annotations

import sqlite3
from html import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .. import auth, config, db, legal, pages

router = APIRouter()
admin_router = APIRouter(prefix="/api/admin/legal")


class DocumentIn(BaseModel):
    slug: str = Field(max_length=60)
    title: str = Field(max_length=200)
    body_md: str


class DocumentPatch(BaseModel):
    title: str | None = Field(None, max_length=200)
    body_md: str | None = None
    published: bool | None = None
    sort: int | None = Field(None, ge=-1000, le=1000)


class PreviewIn(BaseModel):
    body_md: str


def _body(text: str) -> str:
    text = text.replace("\r\n", "\n")
    if len(text.encode("utf-8")) > legal.MAX_BODY_BYTES:
        raise HTTPException(422, "Treść dokumentu może mieć do 200 kB.")
    return text


def _title(text: str) -> str:
    text = text.strip()
    if not text:
        raise HTTPException(422, "Tytuł dokumentu nie może być pusty.")
    return text


def _row(conn: sqlite3.Connection, slug: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM legal_documents WHERE slug=?", (slug,)).fetchone()
    if row is None:
        raise HTTPException(404, "Nie ma takiego dokumentu.")
    return row


# --- strony publiczne ---------------------------------------------------------------
@router.get("/regulamin", include_in_schema=False)
def old_terms():
    return RedirectResponse("/dokumenty", status_code=302)


@router.get("/polityka-prywatnosci", include_in_schema=False)
def old_privacy():
    return RedirectResponse("/dokumenty/polityka-prywatnosci", status_code=302)


@router.get("/dokumenty", include_in_schema=False)
def documents_page(conn: sqlite3.Connection = Depends(db.get_db)):
    items = "".join(
        f'<li><a href="/dokumenty/{escape(r["slug"])}">{escape(r["title"])}</a>'
        f'<span class="hint">Ostatnia zmiana: {escape(legal.format_updated(r["updated_at"]))}</span></li>'
        for r in legal.published(conn))
    content = f'<section class="card"><ul class="doc-list">{items}</ul></section>' if items \
        else '<section class="card"><p>Brak opublikowanych dokumentów.</p></section>'
    return pages.render("dokument.html", {
        "PAGETITLE": "Regulaminy i dokumenty", "TITLE": "Regulaminy i dokumenty",
        "LEAD": '<p class="lead">Zasady konkursu, turnieju i przetwarzania danych.</p>', "CONTENT": content})


@router.get("/dokumenty/{slug}", include_in_schema=False)
def document_page(slug: str, conn: sqlite3.Connection = Depends(db.get_db)):
    row = conn.execute("SELECT * FROM legal_documents WHERE slug=? AND published=1", (slug,)).fetchone()
    if row is None:
        raise HTTPException(404, "Nie znaleziono dokumentu.")
    title = escape(row["title"])
    lead = (f'<p class="lead doc-meta">Ostatnia zmiana: {escape(legal.format_updated(row["updated_at"]))}</p>'
            f'<p class="lead doc-meta">Wersja {row["version"]}</p>')
    return pages.render("dokument.html", {
        "PAGETITLE": title, "TITLE": title, "LEAD": lead,
        "CONTENT": f'<article class="card doc-body">{legal.render_markdown(row["body_md"])}</article>'})


# --- API publiczne ------------------------------------------------------------------
@router.get("/api/legal")
def list_public(conn: sqlite3.Connection = Depends(db.get_db)):
    docs = [{"slug": r["slug"], "title": r["title"], "updated_at": r["updated_at"], "version": r["version"]}
            for r in legal.published(conn)]
    return {"documents": docs, "latest_update": max((d["updated_at"] for d in docs), default=None)}


# --- panel admina -------------------------------------------------------------------
@admin_router.get("")
def admin_list(_: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    rows = conn.execute("SELECT slug,title,published,sort,version,created_at,updated_at FROM legal_documents "
                        "ORDER BY sort, slug").fetchall()
    return [{**dict(r), "published": bool(r["published"]), "base": r["slug"] in legal.BASE_SLUGS} for r in rows]


@admin_router.post("/preview")
def admin_preview(body: PreviewIn, _: dict = Depends(auth.require_admin)):
    return {"html": legal.render_markdown(_body(body.body_md))}


@admin_router.get("/{slug}")
def admin_get(slug: str, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    row = _row(conn, slug)
    versions = conn.execute("SELECT version,title,saved_at,saved_by FROM legal_document_versions WHERE slug=? "
                            "ORDER BY version DESC", (slug,)).fetchall()
    return {**dict(row), "published": bool(row["published"]), "base": slug in legal.BASE_SLUGS,
            "versions": [dict(v) for v in versions]}


@admin_router.get("/{slug}/versions/{n}")
def admin_version(slug: str, n: int, _: dict = Depends(auth.require_admin),
                  conn: sqlite3.Connection = Depends(db.get_db)):
    row = conn.execute("SELECT * FROM legal_document_versions WHERE slug=? AND version=?", (slug, n)).fetchone()
    if row is None:
        raise HTTPException(404, "Nie ma takiej wersji dokumentu.")
    return dict(row)


@admin_router.post("", status_code=201)
def admin_create(body: DocumentIn, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    slug = body.slug.strip()
    if not legal.SLUG_RE.match(slug):
        raise HTTPException(422, "Adres dokumentu: 3-60 znaków, małe litery, cyfry i myślniki.")
    title, text = _title(body.title), _body(body.body_md)
    now = config.now_iso()
    with db.tx(conn):
        if conn.execute("SELECT 1 FROM legal_documents WHERE slug=?", (slug,)).fetchone():
            raise HTTPException(409, "Dokument o tym adresie już istnieje.")
        sort = conn.execute("SELECT COALESCE(MAX(sort),0)+1 FROM legal_documents").fetchone()[0]
        conn.execute("INSERT INTO legal_documents(slug,title,body_md,published,sort,version,created_at,updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?)", (slug, title, text, 1, sort, 1, now, now))
    return {"slug": slug, "version": 1, "updated_at": now}


@admin_router.put("/{slug}")
def admin_update(slug: str, body: DocumentPatch, staff: dict = Depends(auth.require_admin),
                 conn: sqlite3.Connection = Depends(db.get_db)):
    """Zmiana tytułu lub treści: wersja +1, stan sprzed zmiany do ``legal_document_versions``, ``updated_at`` z serwera.
    Sama zmiana ``published`` / ``sort`` nie zmienia wersji ani daty."""
    title = _title(body.title) if body.title is not None else None
    text = _body(body.body_md) if body.body_md is not None else None
    with db.tx(conn):
        row = _row(conn, slug)
        if body.published is False and slug in legal.BASE_SLUGS:
            raise HTTPException(409, "Dokumentu bazowego nie można ukryć.")
        new_title = row["title"] if title is None else title
        new_text = row["body_md"] if text is None else text
        version, updated_at = row["version"], row["updated_at"]
        if new_title != row["title"] or new_text != row["body_md"]:
            now = config.now_iso()
            conn.execute("INSERT INTO legal_document_versions(slug,version,title,body_md,saved_at,saved_by) "
                         "VALUES(?,?,?,?,?,?)", (slug, version, row["title"], row["body_md"], now, staff["login"]))
            version, updated_at = version + 1, now
        published = row["published"] if body.published is None else int(body.published)
        sort = row["sort"] if body.sort is None else body.sort
        conn.execute("UPDATE legal_documents SET title=?, body_md=?, published=?, sort=?, version=?, updated_at=? "
                     "WHERE slug=?", (new_title, new_text, published, sort, version, updated_at, slug))
    return {"slug": slug, "version": version, "updated_at": updated_at}


@admin_router.delete("/{slug}")
def admin_delete(slug: str, _: dict = Depends(auth.require_admin), conn: sqlite3.Connection = Depends(db.get_db)):
    with db.tx(conn):
        _row(conn, slug)
        if slug in legal.BASE_SLUGS:
            raise HTTPException(409, "Dokumentu bazowego nie można usunąć.")
        conn.execute("DELETE FROM legal_document_versions WHERE slug=?", (slug,))
        conn.execute("DELETE FROM legal_documents WHERE slug=?", (slug,))
    return {"ok": True}
