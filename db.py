# db.py
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

DB_PATH = "app.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize tables and insert default settings keys if missing."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS documents (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      original_name TEXT NOT NULL,
      stored_name TEXT NOT NULL,
      language TEXT DEFAULT 'auto',
      pages INTEGER DEFAULT 0,
      doc_type TEXT DEFAULT 'pdf',
      search_text TEXT DEFAULT '',
      created_at TEXT DEFAULT (datetime('now'))
    )
    """
    )

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS notes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      body TEXT NOT NULL,
      document_id INTEGER NULL,
      created_at TEXT DEFAULT (datetime('now')),
      FOREIGN KEY(document_id) REFERENCES documents(id)
    )
    """
    )

    # Key-value settings table
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    )
    """
    )

    # Defaults
    _set_default(cur, "ui_lang", "hu")
    _set_default(cur, "answer_language", "hu")
    _set_default(cur, "theme", "dark")
    _set_default(cur, "manual_mode", "0")
    _set_default(cur, "translation_style", "precise")
    _set_default(cur, "default_gpt_mode", "exam")

    conn.commit()
    conn.close()


def _set_default(cur: sqlite3.Cursor, key: str, value: str) -> None:
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO settings(key, value) VALUES(?, ?)", (key, value))


# ---------- settings ----------
def get_all_settings() -> Dict[str, str]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings")
    rows = cur.fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def get_setting(key: str, default: str = "") -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
    INSERT INTO settings(key, value) VALUES(?, ?)
    ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """,
        (key, value),
    )
    conn.commit()
    conn.close()


# ---------- documents ----------
def insert_document(
    title: str,
    original_name: str,
    stored_name: str,
    language: str,
    pages: int,
    doc_type: str,
    search_text: str,
) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
    INSERT INTO documents(title, original_name, stored_name, language, pages, doc_type, search_text)
    VALUES(?,?,?,?,?,?,?)
    """,
        (title, original_name, stored_name, language, int(pages), doc_type, search_text),
    )
    conn.commit()
    doc_id = cur.lastrowid
    conn.close()
    return int(doc_id)


def _doc_postprocess(d: Dict[str, Any]) -> Dict[str, Any]:
    # Backwards-compat aliases for templates
    if "doc_type" in d and "type" not in d:
        d["type"] = d.get("doc_type")
    if "pages" in d and "page_count" not in d:
        d["page_count"] = d.get("pages")
    return d


def list_documents() -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM documents ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return [_doc_postprocess(dict(r)) for r in rows]


def get_document(doc_id: int) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM documents WHERE id = ?", (int(doc_id),))
    row = cur.fetchone()
    conn.close()
    return _doc_postprocess(dict(row)) if row else None


def search_documents(q: str, limit: int = 8) -> List[Dict[str, Any]]:
    q2 = f"%{(q or '').strip()}%"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
    SELECT * FROM documents
    WHERE title LIKE ? OR search_text LIKE ? OR original_name LIKE ?
    ORDER BY id DESC
    LIMIT ?
    """,
        (q2, q2, q2, int(limit)),
    )
    rows = cur.fetchall()
    conn.close()
    return [_doc_postprocess(dict(r)) for r in rows]


# ---------- notes ----------
def insert_note(title: str, body: str, document_id: Optional[int] = None) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
    INSERT INTO notes(title, body, document_id)
    VALUES(?,?,?)
    """,
        (title, body, document_id),
    )
    conn.commit()
    nid = cur.lastrowid
    conn.close()
    return int(nid)


def list_notes(limit: int = 50, document_id: Optional[int] = None) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    if document_id is None:
        cur.execute(
            """
        SELECT * FROM notes
        ORDER BY id DESC
        LIMIT ?
        """,
            (int(limit),),
        )
    else:
        cur.execute(
            """
        SELECT * FROM notes
        WHERE document_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
            (int(document_id), int(limit)),
        )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_note(note_id: int) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM notes WHERE id = ?", (int(note_id),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_note(note_id: int, title: str, body: str, document_id: Optional[int]) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
    UPDATE notes SET title=?, body=?, document_id=? WHERE id=?
    """,
        (title, body, document_id, int(note_id)),
    )
    conn.commit()
    conn.close()


def delete_note(note_id: int) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM notes WHERE id=?", (int(note_id),))
    conn.commit()
    conn.close()


def search_notes(q: str, document_id: Optional[int] = None, limit: int = 12) -> List[Dict[str, Any]]:
    q2 = f"%{(q or '').strip()}%"
    conn = get_conn()
    cur = conn.cursor()

    if document_id is None:
        cur.execute(
            """
        SELECT * FROM notes
        WHERE title LIKE ? OR body LIKE ?
        ORDER BY id DESC
        LIMIT ?
        """,
            (q2, q2, int(limit)),
        )
    else:
        cur.execute(
            """
        SELECT * FROM notes
        WHERE (title LIKE ? OR body LIKE ?) AND document_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
            (q2, q2, int(document_id), int(limit)),
        )

    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
