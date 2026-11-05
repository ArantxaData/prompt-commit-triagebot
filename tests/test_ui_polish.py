"""Pulido de la interfaz: transiciones ofrecidas, contador de vencidos y accesibilidad."""

import itertools
import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture()
def client():
    return TestClient(app)


def add(title, status="open"):
    ticket = db.insert_ticket(title, "d", {"category": "bug", "priority": "P1", "tags": []})
    if status != "open":
        ticket = db.update_ticket(ticket["id"], status=status)
    return ticket


def status_options(html):
    select = re.search(r'<select name="status".*?</select>', html, flags=re.S).group(0)
    return re.findall(r'<option value="(\w+)"', select)


def set_due_date(ticket_id, days_from_today):
    day = (datetime.now(UTC).date() + timedelta(days=days_from_today)).isoformat()
    with db.get_connection() as conn:
        conn.execute("UPDATE tickets SET due_date = ? WHERE id = ?", (day, ticket_id))


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("open", ["open", "in_progress", "resolved"]),
        ("in_progress", ["in_progress", "resolved"]),
        ("resolved", ["in_progress", "resolved", "closed"]),
        ("closed", ["in_progress", "closed"]),
    ],
)
def test_status_select_only_offers_current_and_allowed_transitions(client, status, expected):
    add("t", status=status)
    html = client.get("/", params={"status": "all"}).text
    assert sorted(status_options(html)) == sorted(expected)


def test_row_after_rejected_transition_still_offers_only_valid_options(client):
    ticket = add("t")
    response = client.patch(
        f"/ui/tickets/{ticket['id']}", data={"status": "closed"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 409
    assert sorted(status_options(response.text)) == ["in_progress", "open", "resolved"]


def test_overdue_counter_counts_only_open_or_in_progress_past_due(client):
    late, late2, on_time, done = add("a"), add("b"), add("c"), add("d", status="resolved")
    set_due_date(late["id"], -2)
    set_due_date(on_time["id"], 0)
    set_due_date(done["id"], -2)  # resuelto: no cuenta

    text = " ".join(client.get("/", params={"status": "all"}).text.split())
    assert "1 vencido" in text and "vencidos" not in text

    set_due_date(late2["id"], -1)
    text = " ".join(client.get("/", params={"status": "all"}).text.split())
    assert "2 vencidos" in text


def test_no_overdue_counter_when_nothing_is_late(client):
    add("a")
    assert "vencido" not in client.get("/").text.lower().replace("fecha límite", "")


def test_clear_filters_link_only_when_filters_are_active(client):
    add("a")
    default = client.get("/").text
    assert "Limpiar filtros" not in default
    for params in ({"priority": "P1"}, {"status": "all"}, {"responsable": "Ana"}):
        assert "Limpiar filtros" in client.get("/", params=params).text


def test_table_is_accessible_and_has_mobile_labels(client):
    ticket = add("a")
    with db.get_connection() as conn:  # un P1 siempre trae fecha: se quita para ver el "sin fecha"
        conn.execute("UPDATE tickets SET due_date = NULL WHERE id = ?", (ticket["id"],))
    html = client.get("/").text
    assert html.count('scope="col"') == 7
    assert 'role="region"' in html and 'aria-label="Listado de tickets"' in html
    for label in ("Categoría", "Prioridad", "Fecha límite", "Estado", "Responsable"):
        assert f'data-label="{label}"' in html
    assert "Sin responsable" in html and "Sin fecha límite" in html  # texto para lectores


_serial = itertools.count(1)


def add_with(responsable):
    # Título distinto en cada llamada: dos tickets con el mismo texto se rechazan.
    return db.insert_ticket(
        f"t{next(_serial)}",
        "d",
        {"category": "bug", "priority": "P1", "tags": []},
        responsable=responsable,
    )


def responsable_options(html):
    select = re.search(r'<select id="f-resp-filter".*?</select>', html, flags=re.S).group(0)
    return re.findall(r'<option value="([^"]*)"', select)


def test_list_responsables_is_distinct_sorted_and_skips_empty():
    for name in ("luis", "Ana", "Ana", None, "", "Berta"):
        add_with(name)
    assert db.list_responsables() == ["Ana", "Berta", "luis"]  # sin duplicados, sin vacíos


def test_responsable_filter_is_a_dropdown_with_existing_names(client):
    add_with("Luis")
    add_with("Ana")
    html = client.get("/").text
    assert responsable_options(html) == ["", "Ana", "Luis"]  # "" = Todos
    assert '<input id="f-resp-filter"' not in html


def test_responsable_filter_selects_the_active_one_and_keeps_unknown_ones(client):
    add_with("Ana")
    html = client.get("/", params={"responsable": "Ana"}).text
    assert re.search(r'<option value="Ana"\s+selected', html)
    # Un responsable que ya no existe (URL antigua) no se pierde: sigue como opción activa.
    html = client.get("/", params={"responsable": "Pedro"}).text
    assert re.search(r'<option value="Pedro"\s+selected', html)


def test_responsable_names_are_escaped_in_the_dropdown(client):
    add_with("<b>Ana</b>")
    html = client.get("/").text
    assert "<b>Ana</b>" not in html and "&lt;b&gt;Ana&lt;/b&gt;" in html


def test_form_errors_are_linked_to_their_fields(client):
    response = client.post(
        "/ui/tickets",
        data={"title": " ", "description": "x"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422
    assert 'aria-invalid="true"' in response.text
    assert 'aria-describedby="e-title"' in response.text and 'id="e-title"' in response.text
