"""GET /tickets/stats: total y recuento por categoría, prioridad y estado."""

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

EMPTY = {
    "total": 0,
    "by_category": {
        "bug": 0, "feature_request": 0, "question": 0, "urgent": 0, "no inferido": 0,
    },
    "by_priority": {"P1": 0, "P2": 0, "P3": 0, "no inferido": 0},
    "by_status": {"open": 0, "in_progress": 0, "resolved": 0, "closed": 0},
}  # fmt: skip


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture()
def client():
    return TestClient(app)


def add(category="bug", priority="P1", status="open"):
    ticket = db.insert_ticket("t", "d", {"category": category, "priority": priority, "tags": []})
    if status != "open":
        db.update_ticket(ticket["id"], status=status)
    return ticket


def get_stats(client):
    response = client.get("/tickets/stats")
    assert response.status_code == 200
    return response.json()


def test_empty_database_returns_zeros_for_every_known_value(client):
    assert get_stats(client) == EMPTY


def test_counts_tickets_by_category_priority_and_status(client):
    add("bug", "P1", "open")
    add("bug", "P1", "open")
    add("bug", "P2", "in_progress")
    add("question", "P3", "resolved")
    add("urgent", "P1", "closed")
    add("feature_request", "P2", "open")

    assert get_stats(client) == {
        "total": 6,
        "by_category": {
            "bug": 3, "feature_request": 1, "question": 1, "urgent": 1, "no inferido": 0,
        },
        "by_priority": {"P1": 3, "P2": 2, "P3": 1, "no inferido": 0},
        "by_status": {"open": 3, "in_progress": 1, "resolved": 1, "closed": 1},
    }  # fmt: skip


def test_every_breakdown_adds_up_to_the_total(client):
    for category, priority, status in [
        ("bug", "P1", "open"),
        ("question", "P3", "closed"),
        ("urgent", "no inferido", "resolved"),
        ("no inferido", "P2", "in_progress"),
        ("bug", "P2", "open"),
    ]:
        add(category, priority, status)

    stats = get_stats(client)
    assert stats["total"] == 5
    for key in ("by_category", "by_priority", "by_status"):
        assert sum(stats[key].values()) == stats["total"], key


def test_not_inferred_values_are_counted_separately(client):
    add("no inferido", "no inferido")
    add("bug", "P1")

    stats = get_stats(client)
    assert stats["by_category"]["no inferido"] == 1
    assert stats["by_priority"]["no inferido"] == 1
    assert stats["by_category"]["bug"] == 1


def test_stats_follow_status_changes_made_through_the_api(client):
    ticket = add("bug", "P1", "open")
    before = get_stats(client)["by_status"]
    assert before["open"] == 1 and before["in_progress"] == 0

    patched = client.patch(f"/tickets/{ticket['id']}", json={"status": "in_progress"})
    assert patched.status_code == 200

    after = get_stats(client)["by_status"]
    assert after["open"] == 0 and after["in_progress"] == 1
    assert get_stats(client)["total"] == 1  # el total no cambia


def test_stats_follow_priority_changes_made_through_the_api(client):
    ticket = add("bug", "P3")
    assert client.patch(f"/tickets/{ticket['id']}", json={"priority": "P1"}).status_code == 200
    assert get_stats(client)["by_priority"] == {"P1": 1, "P2": 0, "P3": 0, "no inferido": 0}


def test_ticket_created_through_the_api_is_counted(client, monkeypatch):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: {"category": "urgent", "priority": "P1", "tags": []},
    )
    assert client.post("/tickets", json={"title": "a", "description": "b"}).status_code == 201

    stats = get_stats(client)
    assert stats["total"] == 1
    assert stats["by_category"]["urgent"] == 1
    assert stats["by_priority"]["P1"] == 1
    assert stats["by_status"]["open"] == 1


def test_stats_route_is_not_swallowed_by_the_ticket_id_route(client):
    # /tickets/stats no debe tratarse como /tickets/{ticket_id}.
    assert client.get("/tickets/stats").status_code == 200
    assert client.patch("/tickets/stats", json={"status": "open"}).status_code == 422
    assert client.post("/tickets/stats", json={}).status_code == 405
    assert client.get("/tickets/stats").headers["content-type"].startswith("application/json")


def test_stats_does_not_modify_anything(client):
    add("bug", "P1")
    before = db.list_tickets()
    get_stats(client)
    get_stats(client)
    assert db.list_tickets() == before


def test_listing_still_works_next_to_stats(client):
    add("bug", "P1")
    assert len(client.get("/tickets").json()) == 1
    assert get_stats(client)["total"] == 1
