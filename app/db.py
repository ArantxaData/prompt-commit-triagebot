"""Persistencia SQLite de TriageBot (solo sqlite3, sin ORM)."""

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta

DEFAULT_DATABASE_URL = "sqlite:///triagebot.db"

TICKETS_TABLE = """
CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    category    TEXT NOT NULL CHECK (
        category IN ('bug','feature_request','question','urgent','no inferido')
    ),
    priority    TEXT NOT NULL CHECK (priority IN ('P1','P2','P3','no inferido')),
    tags        TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','in_progress','resolved','closed')),
    responsable TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    due_date    TEXT
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_tickets_category ON tickets (category);
CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets (priority);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets (status);
"""

SCHEMA = TICKETS_TABLE + INDEXES

TICKET_COLUMNS = (
    "id, title, description, category, priority, tags, status, "
    "responsable, created_at, updated_at, due_date"
)
# Se crea aparte: en BDs anteriores la columna se añade por migración antes del índice.
RESPONSABLE_INDEX = "CREATE INDEX IF NOT EXISTS idx_tickets_responsable ON tickets (responsable)"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# Días hasta la fecha límite según prioridad: P1 hoy, P2 mañana, P3 dentro de dos días.
DUE_DAYS = {"P1": 0, "P2": 1, "P3": 2}


def _due_date(priority: str) -> str | None:
    """Fecha límite (YYYY-MM-DD, UTC) desde hoy; None si la prioridad no tiene plazo."""
    days = DUE_DAYS.get(priority)
    if days is None:
        return None
    return (datetime.now(UTC).date() + timedelta(days=days)).isoformat()


def _db_path() -> str:
    """Lee DATABASE_URL en cada llamada (los tests la cambian por test)."""
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    return url.removeprefix("sqlite:///")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)  # idempotente
    # Migraciones: bases de datos creadas antes de añadir columnas nuevas.
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(tickets)")}
    if "due_date" not in columns:
        conn.execute("ALTER TABLE tickets ADD COLUMN due_date TEXT")
    if "responsable" not in columns:
        conn.execute("ALTER TABLE tickets ADD COLUMN responsable TEXT")
    conn.commit()
    _migrate_status_check(conn)
    conn.execute(RESPONSABLE_INDEX)

    return conn


def _migrate_status_check(conn: sqlite3.Connection) -> None:
    """Bases de datos antiguas: su CHECK de status no admite 'resolved'.

    SQLite no permite modificar un CHECK, así que se reconstruye la tabla copiando los datos
    (todo en una transacción: si algo falla no queda nada a medias).
    """
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'tickets'"
    ).fetchone()["sql"]
    if "'resolved'" in sql:
        return
    conn.executescript(
        f"""
        BEGIN;
        DROP INDEX IF EXISTS idx_tickets_category;
        DROP INDEX IF EXISTS idx_tickets_priority;
        DROP INDEX IF EXISTS idx_tickets_status;
        ALTER TABLE tickets RENAME TO tickets_old;
        {TICKETS_TABLE}
        INSERT INTO tickets ({TICKET_COLUMNS}) SELECT {TICKET_COLUMNS} FROM tickets_old;
        DROP TABLE tickets_old;
        {INDEXES}
        COMMIT;
        """
    )


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
    """Guarda título, descripción y fecha tal cual; el resto viene del clasificador.

    La fecha límite (due_date) se calcula desde hoy según la prioridad.
    """
    now = _now()
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO tickets (title, description, category, priority, tags,"
                " responsable, status, created_at, updated_at, due_date)"
                " VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)",
                (
                    title,
                    description,
                    classification["category"],
                    classification["priority"],
                    json.dumps(classification["tags"], ensure_ascii=False),
                    responsable,
                    created_at or now,
                    now,
                    _due_date(classification["priority"]),
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


def list_tickets(
    category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    responsable: str | None = None,
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
    query += " ORDER BY id DESC"
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
    if "priority" in changes:
        changes["due_date"] = _due_date(changes["priority"])  # se recalcula desde hoy
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
