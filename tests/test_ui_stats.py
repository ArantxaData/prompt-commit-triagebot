"""Interfaz de estadísticas: botón en el tablero y página con la tabla resumen."""

import re

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

FAKE_STATS = {
    "total": 12,
    "by_category": {"bug": 5, "feature_request": 3, "question": 2, "urgent": 1, "no inferido": 1},
    "by_priority": {"P1": 4, "P2": 0, "P3": 7, "no inferido": 1},
    "by_status": {"open": 8, "in_progress": 2, "resolved": 1, "closed": 1},
}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def fake_stats(monkeypatch):
    # raising=False: db.ticket_stats llega con la rama de la parte funcional.
    monkeypatch.setattr(db, "ticket_stats", lambda: FAKE_STATS, raising=False)


def rows(html):
    """Filas de la tabla en orden: (texto, recuento) de cada <th scope="row"> + <td>."""
    pattern = r'<th scope="row"[^>]*>\s*(.*?)\s*</th>\s*<td[^>]*>\s*(\d+)\s*</td>'
    return [(label, int(count)) for label, count in re.findall(pattern, html, re.S)]


def test_dashboard_has_a_statistics_button_that_opens_a_new_tab(client):
    html = client.get("/").text
    link = re.search(r'<a href="/estadisticas"[^>]*>', html).group(0)
    assert 'target="_blank"' in link
    assert 'rel="noopener"' in link  # una pestaña nueva no debe poder controlar el tablero
    assert "Estadísticas" in html
    assert "se abre en una pestaña nueva" in html  # aviso para lectores de pantalla


def test_button_is_in_the_page_header_next_to_the_title(client):
    html = client.get("/").text
    header = re.search(r"<header.*?</header>", html, re.S).group(0)
    assert "TriageBot" in header and 'href="/estadisticas"' in header


def test_page_shows_the_total_and_every_breakdown_in_order(client, fake_stats):
    response = client.get("/estadisticas")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert rows(response.text) == [
        ("Total de tickets", 12),
        ("Bug", 5), ("Solicitud", 3), ("Consulta", 2), ("Urgente", 1), ("no inferido", 1),
        ("P1 · Alta", 4), ("P2 · Media", 0), ("P3 · Baja", 7), ("no inferido", 1),
        ("Abierto", 8), ("En curso", 2), ("Resuelto", 1), ("Cerrado", 1),
    ]  # fmt: skip


def test_page_has_a_group_header_for_category_priority_and_status(client, fake_stats):
    html = client.get("/estadisticas").text
    groups = re.findall(r'<th scope="rowgroup"[^>]*>\s*(.*?)\s*</th>', html, re.S)
    assert groups == ["Categoría", "Prioridad", "Estado"]


def test_values_without_tickets_are_listed_with_a_zero(client, fake_stats):
    assert ("P2 · Media", 0) in rows(client.get("/estadisticas").text)


def test_empty_database_shows_zero_everywhere(client, monkeypatch):
    empty = {
        "total": 0,
        "by_category": dict.fromkeys(["bug", "feature_request", "question", "urgent"], 0),
        "by_priority": dict.fromkeys(["P1", "P2", "P3"], 0),
        "by_status": dict.fromkeys(["open", "in_progress", "resolved", "closed"], 0),
    }
    monkeypatch.setattr(db, "ticket_stats", lambda: empty, raising=False)
    assert {count for _, count in rows(client.get("/estadisticas").text)} == {0}


def test_a_value_without_a_spanish_label_is_shown_as_is(client, monkeypatch):
    stats = {**FAKE_STATS, "by_status": {**FAKE_STATS["by_status"], "archivado": 3}}
    monkeypatch.setattr(db, "ticket_stats", lambda: stats, raising=False)
    assert ("archivado", 3) in rows(client.get("/estadisticas").text)


def test_page_links_back_to_the_dashboard_and_is_accessible(client, fake_stats):
    html = client.get("/estadisticas").text
    assert 'href="/"' in html and "Tablero" in html
    assert '<html lang="es">' in html and "<caption" in html
    assert html.count('scope="col"') == 2 and "Estadísticas · TriageBot" in html


@pytest.mark.skipif(
    not hasattr(db, "ticket_stats"), reason="db.ticket_stats aún no está en esta rama"
)
def test_page_with_the_real_stats_function(client):
    classification = {"category": "bug", "priority": "P1", "tags": []}
    first = db.insert_ticket("uno", "d", classification)
    db.insert_ticket("dos", "d", {**classification, "category": "question", "priority": "P3"})
    db.update_ticket(first["id"], status="in_progress")

    table = rows(client.get("/estadisticas").text)
    assert table[0] == ("Total de tickets", 2)
    assert dict(table[1:5]) == {"Bug": 1, "Solicitud": 0, "Consulta": 1, "Urgente": 0}
    assert ("En curso", 1) in table and ("Abierto", 1) in table
