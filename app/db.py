"""Persistencia SQLite de TriageBot (solo sqlite3, sin ORM)."""

import json
import os
import sqlite3
from datetime import UTC, datetime

DEFAULT_DATABASE_URL = "sqlite:///triagebot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    category    TEXT NOT NULL CHECK (
        category IN ('bug','feature_request','question','urgent','no inferido')
    ),
    priority    TEXT NOT NULL CHECK (priority IN ('P1','P2','P3','no inferido')),
    tags        TEXT NOT NULL DEFAULT '[]',
    responsable TEXT,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','closed')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_category ON tickets (category);
CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets (priority);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets (status);
"""

# Se crea aparte: en BDs anteriores la columna se añade por migración antes del índice.
RESPONSABLE_INDEX = "CREATE INDEX IF NOT EXISTS idx_tickets_responsable ON tickets (responsable)"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _db_path() -> str:
    """Lee DATABASE_URL en cada llamada (los tests la cambian por test)."""
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    return url.removeprefix("sqlite:///")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)  # idempotente
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(tickets)")}
    if "responsable" not in columns:  # BD creada antes de existir el campo
        conn.execute("ALTER TABLE tickets ADD COLUMN responsable TEXT")
    conn.execute(RESPONSABLE_INDEX)
    return conn


def init_db() -> None:
    get_connection().close()


def _row_to_ticket(row: sqlite3.Row) -> dict:
    ticket = dict(row)
    ticket["tags"] = json.loads(ticket["tags"])
    return ticket


def insert_ticket(
    title: str,
    description: str,
    classification: dict,
    created_at: str | None = None,
    responsable: str | None = None,
) -> dict:
    """Guarda título, descripción y fecha tal cual; el resto viene del clasificador."""
    now = _now()
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO tickets (title, description, category, priority, tags,"
                " responsable, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)",
                (
                    title,
                    description,
                    classification["category"],
                    classification["priority"],
                    json.dumps(classification["tags"], ensure_ascii=False),
                    responsable,
                    created_at or now,
                    now,
                ),
            )
        return get_ticket(cur.lastrowid, conn)
    finally:
        conn.close()


def get_ticket(ticket_id: int, conn: sqlite3.Connection | None = None) -> dict | None:
    own = conn is None
    conn = conn or get_connection()
    try:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return _row_to_ticket(row) if row else None
    finally:
        if own:
            conn.close()


# Orden del listado: "recent" (más nuevos primero) o "priority" (P1 primero y, dentro de
# cada prioridad, los más antiguos primero; "no inferido" al final).
SORTS = {
    "recent": "id DESC",
    "priority": (
        "CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 WHEN 'P3' THEN 3 ELSE 4 END,"
        " created_at ASC, id ASC"
    ),
}


def list_tickets(
    category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    responsable: str | None = None,
    sort: str = "recent",
) -> list[dict]:
    filters = {
        "category": category,
        "priority": priority,
        "status": status,
        "responsable": responsable,
    }
    active = {k: v for k, v in filters.items() if v}
    where = " AND ".join(f"{k} = ?" for k in active)  # claves fijas, valores parametrizados
    query = "SELECT * FROM tickets"
    if where:
        query += f" WHERE {where}"
    query += f" ORDER BY {SORTS[sort]}"  # sort solo puede ser una clave de SORTS
    conn = get_connection()
    try:
        return [_row_to_ticket(r) for r in conn.execute(query, tuple(active.values()))]
    finally:
        conn.close()


def update_ticket(
    ticket_id: int, status: str | None = None, priority: str | None = None
) -> dict | None:
    """Solo status y priority son modificables. Devuelve None si el ticket no existe."""
    changes = {k: v for k, v in {"status": status, "priority": priority}.items() if v}
    conn = get_connection()
    try:
        if changes:
            sets = ", ".join(f"{k} = ?" for k in changes)
            with conn:
                conn.execute(
                    f"UPDATE tickets SET {sets}, updated_at = ? WHERE id = ?",
                    (*changes.values(), _now(), ticket_id),
                )
        return get_ticket(ticket_id, conn)
    finally:
        conn.close()
