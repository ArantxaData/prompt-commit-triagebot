"""Tests de la capa SQLite (app/db.py), independientes de FastAPI y del LLM."""

import sqlite3

import pytest

from app import db

BUG_P1 = {"category": "bug", "priority": "P1", "tags": ["login", "blank-screen"]}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")


def test_init_creates_table_and_is_idempotent():
    db.init_db()
    db.init_db()
    conn = db.get_connection()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tickets)")}
    conn.close()
    assert cols == {
        "id", "title", "description", "category", "priority",
        "tags", "responsable", "status", "created_at", "updated_at", "due_date",
    }  # fmt: skip


def test_insert_stores_input_as_is_and_defaults():
    date = "2026-03-27T09:42:23Z"
    ticket = db.insert_ticket("Título ñ", "Descripción  con acentos", BUG_P1, date)
    assert isinstance(ticket["id"], int)
    assert ticket["title"] == "Título ñ"
    assert ticket["description"] == "Descripción  con acentos"
    assert ticket["created_at"] == "2026-03-27T09:42:23Z"  # fecha tal cual
    assert ticket["status"] == "open"
    assert ticket["tags"] == ["login", "blank-screen"]
    assert ticket["updated_at"].endswith("Z")


def test_insert_without_date_uses_server_time():
    ticket = db.insert_ticket("a", "b", BUG_P1)
    assert ticket["created_at"] == ticket["updated_at"]


def test_data_persists_across_connections():
    created = db.insert_ticket("a", "b", BUG_P1)
    assert db.get_ticket(created["id"]) == created
    assert db.get_ticket(9999) is None


def test_empty_tags_roundtrip():
    ticket = db.insert_ticket("a", "b", {"category": "question", "priority": "P3", "tags": []})
    assert db.get_ticket(ticket["id"])["tags"] == []


def test_not_inferred_is_accepted():
    ticket = db.insert_ticket(
        "a", "b", {"category": "no inferido", "priority": "no inferido", "tags": []}
    )
    assert ticket["category"] == "no inferido"
    assert ticket["priority"] == "no inferido"


def test_check_constraints_reject_invalid_values():
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_ticket("a", "b", {"category": "URGENT", "priority": "P1", "tags": []})
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_ticket("a", "b", {"category": "bug", "priority": "P9", "tags": []})
    assert db.list_tickets() == []  # nada a medias


def test_list_filters_and_order():
    t1 = db.insert_ticket("1", "x", BUG_P1)
    t2 = db.insert_ticket("2", "x", {"category": "question", "priority": "P3", "tags": []})
    t3 = db.insert_ticket("3", "x", {"category": "bug", "priority": "P3", "tags": []})
    db.update_ticket(t3["id"], status="closed")

    assert [t["id"] for t in db.list_tickets()] == [t3["id"], t2["id"], t1["id"]]
    assert [t["id"] for t in db.list_tickets(category="bug")] == [t3["id"], t1["id"]]
    assert [t["id"] for t in db.list_tickets(priority="P3", status="closed")] == [t3["id"]]
    assert db.list_tickets(category="bug", priority="P2") == []


def test_filter_values_are_not_injectable():
    db.insert_ticket("1", "x", BUG_P1)
    assert db.list_tickets(category="bug' OR '1'='1") == []


def test_update_changes_only_status_and_priority():
    created = db.insert_ticket("a", "b", BUG_P1, "2020-01-01T00:00:00Z")
    updated = db.update_ticket(created["id"], status="in_progress", priority="P2")
    assert updated["status"] == "in_progress"
    assert updated["priority"] == "P2"
    assert updated["title"] == "a"
    assert updated["created_at"] == "2020-01-01T00:00:00Z"
    assert updated["updated_at"] >= created["updated_at"]


def test_update_partial_and_missing_ticket():
    created = db.insert_ticket("a", "b", BUG_P1)
    assert db.update_ticket(created["id"], status="closed")["priority"] == "P1"
    assert db.update_ticket(9999, status="closed") is None


def test_update_rejects_invalid_status():
    created = db.insert_ticket("a", "b", BUG_P1)
    with pytest.raises(sqlite3.IntegrityError):
        db.update_ticket(created["id"], status="done")


def test_responsable_is_stored_optional_and_filterable():
    ana = db.insert_ticket("1", "x", BUG_P1, responsable="Ana")
    luis = db.insert_ticket("2", "x", BUG_P1, responsable="Luis")
    nadie = db.insert_ticket("3", "x", BUG_P1)

    assert ana["responsable"] == "Ana"
    assert nadie["responsable"] is None
    assert [t["id"] for t in db.list_tickets(responsable="Ana")] == [ana["id"]]
    assert [t["id"] for t in db.list_tickets(responsable="Luis", category="bug")] == [luis["id"]]
    assert db.list_tickets(responsable="Pedro") == []
    assert len(db.list_tickets(responsable="")) == 3  # filtro vacío se ignora


def test_old_database_without_responsable_is_migrated(tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute(
        "CREATE TABLE tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,"
        " description TEXT NOT NULL, category TEXT NOT NULL, priority TEXT NOT NULL,"
        " tags TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'open',"
        " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO tickets (title, description, category, priority, created_at, updated_at)"
        " VALUES ('viejo', 'x', 'bug', 'P1', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{old}")

    tickets = db.list_tickets()
    assert tickets[0]["title"] == "viejo"
    assert tickets[0]["responsable"] is None
    assert db.insert_ticket("nuevo", "x", BUG_P1, responsable="Ana")["responsable"] == "Ana"
