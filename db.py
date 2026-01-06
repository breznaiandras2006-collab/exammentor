# db.py
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = "app.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable FK constraints (sqlite defaults to OFF)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
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

    # ---------------- Study (cards + simple SRS + reviews) ----------------
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS study_cards (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      document_id INTEGER NULL,
      note_id INTEGER NULL,
      question TEXT NOT NULL,
      answer TEXT NOT NULL,
      created_at TEXT DEFAULT (datetime('now')),
      FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE SET NULL,
      FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE SET NULL
    )
    """
    )

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS study_srs (
      card_id INTEGER PRIMARY KEY,
      box INTEGER NOT NULL DEFAULT 1,
      due_at TEXT NOT NULL DEFAULT (date('now')),
      last_review_at TEXT NULL,
      correct_streak INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY(card_id) REFERENCES study_cards(id) ON DELETE CASCADE
    )
    """
    )

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS study_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      card_id INTEGER NOT NULL,
      correct INTEGER NOT NULL,
      source TEXT NOT NULL DEFAULT 'session',
      created_at TEXT DEFAULT (datetime('now')),
      FOREIGN KEY(card_id) REFERENCES study_cards(id) ON DELETE CASCADE
    )
    """
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_study_cards_doc ON study_cards(document_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_study_srs_due ON study_srs(due_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_study_reviews_card ON study_reviews(card_id)")

    # Defaults
    _set_default(cur, "ui_lang", "hu")
    _set_default(cur, "answer_language", "hu")
    _set_default(cur, "theme", "dark")
    _set_default(cur, "manual_mode", "0")
    _set_default(cur, "translation_style", "precise")
    _set_default(cur, "default_gpt_mode", "exam")

    conn.commit()
    conn.close()


# ---------- study cards ----------
_LEITNER_INTERVALS_DAYS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 14}


def _same_nullable(a: Any, b: Any) -> bool:
    return (a is None and b is None) or (a == b)


def _find_existing_card_id(document_id: Optional[int], question: str, answer: str) -> Optional[int]:
    """Dedup helper (keeps null-doc distinct)."""
    conn = get_conn()
    cur = conn.cursor()
    if document_id is None:
        cur.execute(
            """
        SELECT id FROM study_cards
        WHERE document_id IS NULL AND question=? AND answer=?
        LIMIT 1
        """,
            (question, answer),
        )
    else:
        cur.execute(
            """
        SELECT id FROM study_cards
        WHERE document_id=? AND question=? AND answer=?
        LIMIT 1
        """,
            (int(document_id), question, answer),
        )
    row = cur.fetchone()
    conn.close()
    return int(row["id"]) if row else None


def create_study_card(
    question: str,
    answer: str,
    document_id: Optional[int] = None,
    note_id: Optional[int] = None,
) -> Tuple[Optional[int], bool]:
    """Returns (card_id, created_new)."""
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or not a:
        return None, False

    existing = _find_existing_card_id(document_id, q, a)
    if existing is not None:
        return existing, False

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
    INSERT INTO study_cards(document_id, note_id, question, answer)
    VALUES(?,?,?,?)
    """,
        (document_id, note_id, q, a),
    )
    card_id = int(cur.lastrowid)
    cur.execute(
        """
    INSERT OR REPLACE INTO study_srs(card_id, box, due_at, last_review_at, correct_streak)
    VALUES(?, 1, date('now'), NULL, 0)
    """,
        (card_id,),
    )
    conn.commit()
    conn.close()
    return card_id, True


def update_study_card(card_id: int, question: str, answer: str, document_id: Optional[int]) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
    UPDATE study_cards SET question=?, answer=?, document_id=? WHERE id=?
    """,
        ((question or "").strip(), (answer or "").strip(), document_id, int(card_id)),
    )
    conn.commit()
    conn.close()


def delete_study_card(card_id: int) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM study_cards WHERE id=?", (int(card_id),))
    conn.commit()
    conn.close()


def get_study_card(card_id: int) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
    SELECT c.*, d.title AS document_title, s.box, s.due_at
    FROM study_cards c
    LEFT JOIN documents d ON d.id=c.document_id
    LEFT JOIN study_srs s ON s.card_id=c.id
    WHERE c.id=?
    """,
        (int(card_id),),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def list_study_cards(
    q: str = "",
    document_id: Optional[int] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    q2 = f"%{(q or '').strip()}%"
    conn = get_conn()
    cur = conn.cursor()

    where = []
    args: List[Any] = []
    if (q or "").strip():
        where.append("(c.question LIKE ? OR c.answer LIKE ?)")
        args.extend([q2, q2])
    if document_id is not None:
        where.append("c.document_id=?")
        args.append(int(document_id))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    cur.execute(
        f"""
    SELECT c.*, d.title AS document_title, s.box, s.due_at
    FROM study_cards c
    LEFT JOIN documents d ON d.id=c.document_id
    LEFT JOIN study_srs s ON s.card_id=c.id
    {where_sql}
    ORDER BY date(s.due_at) ASC, s.box ASC, c.id DESC
    LIMIT ?
    """,
        (*args, int(limit)),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_study_counts(document_id: Optional[int] = None) -> Tuple[int, int]:
    conn = get_conn()
    cur = conn.cursor()
    if document_id is None:
        cur.execute("SELECT COUNT(*) AS n FROM study_cards")
        total = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM study_srs WHERE date(due_at) <= date('now')")
        due = int(cur.fetchone()["n"])
    else:
        cur.execute("SELECT COUNT(*) AS n FROM study_cards WHERE document_id=?", (int(document_id),))
        total = int(cur.fetchone()["n"])
        cur.execute(
            """
        SELECT COUNT(*) AS n
        FROM study_srs s
        JOIN study_cards c ON c.id=s.card_id
        WHERE c.document_id=? AND date(s.due_at) <= date('now')
        """,
            (int(document_id),),
        )
        due = int(cur.fetchone()["n"])
    conn.close()
    return total, due


def get_next_due_card(document_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    if document_id is None:
        cur.execute(
            """
        SELECT c.*, d.title AS document_title, s.box, s.due_at
        FROM study_srs s
        JOIN study_cards c ON c.id=s.card_id
        LEFT JOIN documents d ON d.id=c.document_id
        WHERE date(s.due_at) <= date('now')
        ORDER BY date(s.due_at) ASC, s.box ASC, c.id ASC
        LIMIT 1
        """
        )
    else:
        cur.execute(
            """
        SELECT c.*, d.title AS document_title, s.box, s.due_at
        FROM study_srs s
        JOIN study_cards c ON c.id=s.card_id
        LEFT JOIN documents d ON d.id=c.document_id
        WHERE c.document_id=? AND date(s.due_at) <= date('now')
        ORDER BY date(s.due_at) ASC, s.box ASC, c.id ASC
        LIMIT 1
        """,
            (int(document_id),),
        )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_random_card(document_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Returns a random card (useful for practice mode when nothing is due)."""
    conn = get_conn()
    cur = conn.cursor()
    if document_id is None:
        cur.execute(
            """
        SELECT c.*, d.title AS document_title, s.box, s.due_at
        FROM study_cards c
        LEFT JOIN documents d ON d.id=c.document_id
        LEFT JOIN study_srs s ON s.card_id=c.id
        ORDER BY RANDOM()
        LIMIT 1
        """
        )
    else:
        cur.execute(
            """
        SELECT c.*, d.title AS document_title, s.box, s.due_at
        FROM study_cards c
        LEFT JOIN documents d ON d.id=c.document_id
        LEFT JOIN study_srs s ON s.card_id=c.id
        WHERE c.document_id=?
        ORDER BY RANDOM()
        LIMIT 1
        """
            , (int(document_id),)
        )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_random_distractors(
    *,
    exclude_card_id: int,
    document_id: Optional[int] = None,
    k: int = 3,
) -> List[str]:
    conn = get_conn()
    cur = conn.cursor()
    out: List[str] = []

    if document_id is not None:
        cur.execute(
            """
        SELECT answer FROM study_cards
        WHERE id != ? AND document_id=?
        ORDER BY RANDOM()
        LIMIT ?
        """,
            (int(exclude_card_id), int(document_id), int(k)),
        )
        out = [r["answer"] for r in cur.fetchall()]

    if len(out) < k:
        cur.execute(
            """
        SELECT answer FROM study_cards
        WHERE id != ?
        ORDER BY RANDOM()
        LIMIT ?
        """,
            (int(exclude_card_id), int(k - len(out))),
        )
        out.extend([r["answer"] for r in cur.fetchall()])

    conn.close()
    # unique, keep order
    seen = set()
    uniq = []
    for a in out:
        if a in seen:
            continue
        seen.add(a)
        uniq.append(a)
    return uniq[:k]


def review_card(card_id: int, correct: bool, source: str = "session") -> None:
    """Updates SRS (Leitner) + logs a review."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT box, correct_streak FROM study_srs WHERE card_id=?", (int(card_id),))
    row = cur.fetchone()
    if not row:
        # ensure srs row exists
        cur.execute(
            """
        INSERT OR REPLACE INTO study_srs(card_id, box, due_at, last_review_at, correct_streak)
        VALUES(?, 1, date('now'), NULL, 0)
        """,
            (int(card_id),),
        )
        box = 1
        streak = 0
    else:
        box = int(row["box"])
        streak = int(row["correct_streak"])

    if correct:
        new_box = min(5, box + 1)
        new_streak = streak + 1
    else:
        new_box = 1
        new_streak = 0

    interval = int(_LEITNER_INTERVALS_DAYS.get(new_box, 0))
    cur.execute(
        """
    UPDATE study_srs
    SET box=?,
        due_at=date('now', ?),
        last_review_at=datetime('now'),
        correct_streak=?
    WHERE card_id=?
    """,
        (new_box, f"+{interval} day", new_streak, int(card_id)),
    )

    cur.execute(
        """
    INSERT INTO study_reviews(card_id, correct, source)
    VALUES(?,?,?)
    """,
        (int(card_id), 1 if correct else 0, (source or "session")),
    )
    conn.commit()
    conn.close()


def study_stats(document_id: Optional[int] = None) -> Dict[str, Any]:
    """Returns {total,due,dist,acc,weak}."""
    total, due = get_study_counts(document_id)

    conn = get_conn()
    cur = conn.cursor()

    dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    if document_id is None:
        cur.execute("SELECT box, COUNT(*) AS n FROM study_srs GROUP BY box")
    else:
        cur.execute("""
        SELECT s.box AS box, COUNT(*) AS n
        FROM study_srs s
        JOIN study_cards c ON c.id=s.card_id
        WHERE c.document_id=?
        GROUP BY s.box
        """, (int(document_id),))
    for r in cur.fetchall():
        b = int(r["box"])
        if b in dist:
            dist[b] = int(r["n"])

    if document_id is None:
        cur.execute("SELECT correct FROM study_reviews ORDER BY id DESC LIMIT 50")
    else:
        cur.execute("""
        SELECT r.correct
        FROM study_reviews r
        JOIN study_cards c ON c.id=r.card_id
        WHERE c.document_id=?
        ORDER BY r.id DESC
        LIMIT 50
        """, (int(document_id),))
    rows = cur.fetchall()
    n = len(rows)
    correct_n = sum(int(r["correct"]) for r in rows)
    wrong_n = n - correct_n
    rate = int(round((correct_n / n) * 100)) if n else 0
    acc = {"n": n, "correct": correct_n, "wrong": wrong_n, "rate": rate}

    # weak cards: box 1, earliest due, plus last result
    if document_id is None:
        cur.execute(
            """
    SELECT c.*, d.title AS document_title, s.box, s.due_at,
           (SELECT r.correct FROM study_reviews r WHERE r.card_id=c.id ORDER BY r.id DESC LIMIT 1) AS last_result
    FROM study_cards c
    LEFT JOIN documents d ON d.id=c.document_id
    LEFT JOIN study_srs s ON s.card_id=c.id
    WHERE s.box=1
    ORDER BY date(s.due_at) ASC, c.id DESC
    LIMIT 12
    """
        )
    else:
        cur.execute(
            """
    SELECT c.*, d.title AS document_title, s.box, s.due_at,
           (SELECT r.correct FROM study_reviews r WHERE r.card_id=c.id ORDER BY r.id DESC LIMIT 1) AS last_result
    FROM study_cards c
    LEFT JOIN documents d ON d.id=c.document_id
    LEFT JOIN study_srs s ON s.card_id=c.id
    WHERE s.box=1 AND c.document_id=?
    ORDER BY date(s.due_at) ASC, c.id DESC
    LIMIT 12
    """,
            (int(document_id),),
        )
    weak = [dict(r) for r in cur.fetchall()]

    conn.close()
    return {"total": total, "due": due, "dist": dist, "acc": acc, "weak": weak}


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
