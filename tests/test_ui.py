"""Tests de la interfaz web (GET /, /ui/tickets) y del orden por prioridad."""

import re

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

HX = {"HX-Request": "true"}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Todos los tests (también los de BD pura) usan una BD temporal, nunca triagebot.db."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture()
def client():
    return TestClient(app)


def add(title, category="bug", priority="P1", status="open", responsable=None, date=None):
    ticket = db.insert_ticket(
        title,
        "descripción de " + title,
        {"category": category, "priority": priority, "tags": ["t-" + title]},
        created_at=date,
        responsable=responsable,
    )
    if status != "open":
        ticket = db.update_ticket(ticket["id"], status=status)
    return ticket


def titles(html):
    """Títulos de las filas, en el orden en que salen en la tabla."""
    return re.findall(r'<summary class="ticket-title[^>]*>\s*(.*?)\s*</summary>', html, flags=re.S)


# ---------- orden por prioridad (backend) ----------


def test_sort_priority_p1_first_then_oldest_first_and_not_inferred_last():
    add("p3-viejo", priority="P3", date="2026-01-01T00:00:00Z")
    add("p1-nuevo", priority="P1", date="2026-03-01T00:00:00Z")
    add("sin-inferir", priority="no inferido", date="2026-01-01T00:00:00Z")
    add("p1-viejo", priority="P1", date="2026-02-01T00:00:00Z")
    add("p2", priority="P2", date="2026-01-01T00:00:00Z")

    ordered = [t["title"] for t in db.list_tickets(sort="priority")]
    assert ordered == ["p1-viejo", "p1-nuevo", "p2", "p3-viejo", "sin-inferir"]
    # El orden por defecto del listado JSON no cambia: más recientes primero.
    assert db.list_tickets()[0]["title"] == "p2"


def test_api_sort_param(client):
    add("p3", priority="P3")
    add("p1", priority="P1")
    by_priority = client.get("/tickets", params={"sort": "priority"}).json()
    assert [t["title"] for t in by_priority] == ["p1", "p3"]
    assert client.get("/tickets", params={"sort": "invalid"}).status_code == 422


# ---------- GET / ----------


def test_index_defaults_to_open_tickets_sorted_by_priority(client):
    add("cerrado", status="closed")
    add("p3", priority="P3")
    add("p1", priority="P1")

    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert titles(response.text) == ["p1", "p3"]  # solo abiertos, P1 antes
    assert "<html" in response.text and "Nuevo ticket" in response.text


def test_index_filters_by_every_dimension(client):
    add("ana-bug", category="bug", responsable="Ana")
    add("ana-q", category="question", priority="P3", responsable="Ana")
    add("luis-bug", category="bug", responsable="Luis")
    add("cerrado", status="closed", responsable="Ana")

    def shown(**params):
        return set(titles(client.get("/", params=params).text))

    assert shown(status="all") == {"ana-bug", "ana-q", "luis-bug", "cerrado"}
    assert shown(status="closed") == {"cerrado"}
    assert shown(category="question") == {"ana-q"}
    assert shown(priority="P3") == {"ana-q"}
    assert shown(responsable="Ana") == {"ana-bug", "ana-q"}
    assert shown(responsable="Ana", category="bug") == {"ana-bug"}
    assert shown(responsable="Pedro") == set()


def test_index_keeps_selected_filters_in_the_form(client):
    html = client.get("/", params={"status": "closed", "priority": "P2", "responsable": "Ana"}).text
    assert re.search(r'<option value="closed"\s+selected', html)
    assert re.search(r'<option value="P2"\s+selected', html)
    assert 'value="Ana"' in html


def test_empty_state_message(client):
    html = client.get("/", params={"responsable": "nadie"}).text
    assert "No hay tickets con estos filtros" in html
    assert "0 tickets" in " ".join(html.split())


def test_htmx_request_returns_only_the_fragment(client):
    add("uno")
    fragment = client.get("/", headers=HX)
    assert "<html" not in fragment.text
    assert titles(fragment.text) == ["uno"]
    assert "HX-Request" in fragment.headers["vary"]

    restore = client.get("/", headers={**HX, "HX-History-Restore-Request": "true"})
    assert "<html" in restore.text  # al volver atrás se necesita la página completa


def test_ticket_text_is_escaped(client):
    add('<script>alert("x")</script>', responsable="<b>Ana</b>")
    html = client.get("/").text
    assert '<script>alert("x")</script>' not in html
    assert "&lt;script&gt;" in html
    assert "<b>Ana</b>" not in html


def test_not_inferred_row_is_shown_and_selectable(client):
    add("raro", category="no inferido", priority="no inferido")
    html = client.get("/", params={"priority": "no inferido"}).text
    assert titles(html) == ["raro"]
    assert "no inferido" in html


# ---------- POST /ui/tickets ----------


def test_form_creates_ticket_and_triggers_table_refresh(client, monkeypatch):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: {"category": "urgent", "priority": "P1", "tags": ["vpn"]},
    )
    response = client.post(
        "/ui/tickets",
        data={"title": "  VPN caída ", "description": "Nadie conecta", "responsable": "Ana"},
        headers=HX,
    )
    assert response.status_code == 200
    assert response.headers["HX-Trigger"] == "ticket-created"
    assert "Nuevo ticket" in response.text and "VPN caída" not in response.text  # form vacío

    created = db.list_tickets()[0]
    assert (created["title"], created["responsable"], created["category"]) == (
        "VPN caída",
        "Ana",
        "urgent",
    )


def test_form_errors_are_shown_next_to_fields_and_nothing_is_saved(client):
    response = client.post(
        "/ui/tickets",
        data={"title": "   ", "description": "x" * 5001, "responsable": "y" * 101},
        headers=HX,
    )
    assert response.status_code == 422
    assert "Este campo es obligatorio." in response.text
    assert "Máximo 5000 caracteres." in response.text
    assert "Máximo 100 caracteres." in response.text
    assert re.search(r"<details[^>]*\bopen\b", response.text)  # el formulario sigue abierto
    assert db.list_tickets() == []


def test_form_keeps_typed_values_on_error(client):
    response = client.post(
        "/ui/tickets", data={"title": "Mi título", "description": ""}, headers=HX
    )
    assert response.status_code == 422
    assert 'value="Mi título"' in response.text


def test_form_survives_classifier_failure(client, monkeypatch):
    def broken(title, description):
        raise RuntimeError("sin servicio")

    monkeypatch.setattr("app.classifier.classify_ticket", broken)
    response = client.post("/ui/tickets", data={"title": "a", "description": "b"}, headers=HX)
    assert response.status_code == 200
    assert db.list_tickets()[0]["category"] == "question"


# ---------- PATCH /ui/tickets/{id} ----------


def test_row_edit_updates_and_returns_the_row(client):
    ticket = add("editable", priority="P3")
    response = client.patch(
        f"/ui/tickets/{ticket['id']}", data={"status": "in_progress", "priority": "P1"}, headers=HX
    )
    assert response.status_code == 200
    assert f'id="ticket-{ticket["id"]}"' in response.text
    assert "<html" not in response.text
    stored = db.get_ticket(ticket["id"])
    assert (stored["status"], stored["priority"]) == ("in_progress", "P1")


def test_row_edit_ignores_not_inferred_and_rejects_bad_values(client):
    ticket = add("raro", priority="no inferido")
    url = f"/ui/tickets/{ticket['id']}"

    ok = client.patch(url, data={"status": "closed", "priority": "no inferido"}, headers=HX)
    assert ok.status_code == 200
    stored = db.get_ticket(ticket["id"])
    assert (stored["status"], stored["priority"]) == ("closed", "no inferido")

    assert client.patch(url, data={"status": "done"}, headers=HX).status_code == 422
    assert client.patch("/ui/tickets/9999", data={"status": "open"}, headers=HX).status_code == 404
