"""IDs de ticket: autogenerados, no editables y robustos ante valores malformados."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import MAX_TICKET_ID

HX = {"HX-Request": "true"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    # raise_server_exceptions=False: un fallo interno se vería como 500, no como excepción
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def ticket(client):
    response = client.post("/tickets", json={"title": "t", "description": "d"})
    assert response.status_code == 201
    return response.json()


def test_ids_are_sequential_positive_integers(client):
    ids = [
        client.post("/tickets", json={"title": f"t{i}", "description": "d"}).json()["id"]
        for i in range(3)
    ]
    assert ids == [1, 2, 3]


@pytest.mark.parametrize("bad_id", [-5, 0, "abc", 1.5, None])
def test_id_cannot_be_set_on_creation(client, bad_id):
    response = client.post("/tickets", json={"id": bad_id, "title": "t", "description": "d"})
    assert response.status_code == 422


def test_id_in_patch_body_is_ignored(client, ticket):
    response = client.patch(f"/tickets/{ticket['id']}", json={"id": 99, "status": "in_progress"})
    assert response.status_code == 200
    assert response.json()["id"] == ticket["id"]
    assert client.patch("/tickets/99", json={"status": "in_progress"}).status_code == 404


# Malformados o fuera de rango: 422 (nunca 500). Mismas reglas en la API y en la pantalla.
INVALID_IDS = ["abc", "1.5", "1e3", "%20", "-1", "0", str(MAX_TICKET_ID + 1), "9" * 25]


@pytest.mark.parametrize("bad_id", INVALID_IDS)
def test_malformed_id_in_api_url_is_422(client, ticket, bad_id):
    response = client.patch(f"/tickets/{bad_id}", json={"status": "in_progress"})
    assert response.status_code == 422


@pytest.mark.parametrize("bad_id", INVALID_IDS)
def test_malformed_id_in_ui_url_is_422(client, ticket, bad_id):
    response = client.patch(f"/ui/tickets/{bad_id}", data={"status": "in_progress"}, headers=HX)
    assert response.status_code == 422


def test_valid_but_missing_ids_are_404_including_the_upper_limit(client, ticket):
    for valid_missing in ("9999", str(MAX_TICKET_ID)):
        api = client.patch(f"/tickets/{valid_missing}", json={"status": "in_progress"})
        ui = client.patch(
            f"/ui/tickets/{valid_missing}", data={"status": "in_progress"}, headers=HX
        )
        assert (api.status_code, ui.status_code) == (404, 404)


def test_malformed_ids_do_not_change_existing_tickets(client, ticket):
    for bad_id in INVALID_IDS:
        client.patch(f"/tickets/{bad_id}", json={"status": "resolved"})
    stored = client.get("/tickets").json()
    assert [(t["id"], t["status"]) for t in stored] == [(ticket["id"], "open")]
