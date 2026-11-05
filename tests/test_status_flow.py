"""Estado `resolved`, transiciones permitidas, reapertura y migración de bases antiguas."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

OLD_SCHEMA = """
CREATE TABLE tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    category    TEXT NOT NULL CHECK (
        category IN ('bug','feature_request','question','urgent','no inferido')
    ),
    priority    TEXT NOT NULL CHECK (priority IN ('P1','P2','P3','no inferido')),
    tags        TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','closed')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    due_date    TEXT
);
CREATE INDEX idx_tickets_category ON tickets (category);
CREATE INDEX idx_tickets_priority ON tickets (priority);
CREATE INDEX idx_tickets_status ON tickets (status);
"""


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: {"category": "bug", "priority": "P2", "tags": ["x"]},
    )
    return TestClient(app)


def new_ticket(client):
    response = client.post("/tickets", json={"title": "t", "description": "d"})
    assert response.status_code == 201
    return response.json()


def set_status(client, ticket, status):
    return client.patch(f"/tickets/{ticket['id']}", json={"status": status})


@pytest.mark.parametrize(
    "path",
    [
        ["in_progress", "resolved", "closed"],  # flujo completo
        ["resolved", "closed"],  # open -> resolved permitido
        ["in_progress", "resolved", "in_progress"],  # reabrir desde resolved
        ["resolved", "closed", "in_progress"],  # reabrir desde closed
    ],
)
def test_allowed_paths(client, path):
    ticket = new_ticket(client)
    for status in path:
        response = set_status(client, ticket, status)
        assert response.status_code == 200
        assert response.json()["status"] == status


@pytest.mark.parametrize(
    ("setup", "target"),
    [
        ([], "closed"),  # open -> closed: falta resolved
        (["in_progress"], "closed"),  # in_progress -> closed
        (["in_progress"], "open"),  # no se vuelve a open
        (["resolved"], "open"),  # reabrir va a in_progress, no a open
        (["resolved", "closed"], "open"),
        (["resolved", "closed"], "resolved"),  # closed -> resolved no existe
    ],
)
def test_forbidden_transitions_return_409_and_change_nothing(client, setup, target):
    ticket = new_ticket(client)
    for status in setup:
        assert set_status(client, ticket, status).status_code == 200
    before = client.get("/tickets").json()

    response = set_status(client, ticket, target)

    assert response.status_code == 409
    assert client.get("/tickets").json() == before


def test_same_status_is_a_noop(client):
    ticket = new_ticket(client)
    response = set_status(client, ticket, "open")
    assert response.status_code == 200
    assert response.json()["status"] == "open"


def test_reopening_keeps_the_same_due_date(client):
    ticket = new_ticket(client)  # P2 -> due_date de mañana
    for status in ("resolved", "closed", "in_progress"):
        reopened = set_status(client, ticket, status).json()
    assert reopened["status"] == "in_progress"
    assert reopened["due_date"] == ticket["due_date"]


def test_resolved_can_be_filtered(client):
    ticket = new_ticket(client)
    other = new_ticket(client)
    set_status(client, ticket, "resolved")
    ids = [t["id"] for t in client.get("/tickets", params={"status": "resolved"}).json()]
    assert ids == [ticket["id"]]
    assert other["id"] not in ids


def test_old_database_is_migrated_keeping_data(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO tickets (title, description, category, priority, tags, status,"
        " created_at, updated_at, due_date)"
        " VALUES ('viejo', 'ñandú', 'bug', 'P1', '[\"a\"]', 'closed', 'c', 'u', '2026-01-01')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")

    migrated = db.list_tickets()  # abrir la conexión dispara la migración

    assert len(migrated) == 1
    assert migrated[0]["title"] == "viejo"
    assert migrated[0]["description"] == "ñandú"
    assert migrated[0]["status"] == "closed"
    assert migrated[0]["tags"] == ["a"]
    assert migrated[0]["due_date"] == "2026-01-01"
    # Ahora admite resolved, y las migraciones repetidas no hacen nada.
    assert db.update_ticket(migrated[0]["id"], status="resolved")["status"] == "resolved"
    assert len(db.list_tickets()) == 1
    conn = sqlite3.connect(path)
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()
    assert {"idx_tickets_category", "idx_tickets_priority", "idx_tickets_status"} <= indexes
