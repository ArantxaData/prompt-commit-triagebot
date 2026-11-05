"""Tests adicionales de POST, GET y PATCH /tickets (complementan test_acceptance.py)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

TICKET_FIELDS = {
    "id", "title", "description", "category", "priority",
    "tags", "responsable", "status", "created_at", "updated_at",
}  # fmt: skip


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return TestClient(app)


def fake_classifier(monkeypatch, **classification):
    result = {"category": "bug", "priority": "P1", "tags": ["x"], **classification}
    monkeypatch.setattr("app.classifier.classify_ticket", lambda title, description: result)


def create(client, title="T", description="D", **extra):
    response = client.post("/tickets", json={"title": title, "description": description, **extra})
    assert response.status_code == 201
    return response.json()


def test_post_trims_text_accepts_limits_and_keeps_given_date(client, monkeypatch):
    fake_classifier(monkeypatch)

    # El SPEC valida "tras trim": los espacios sobrantes no cuentan ni se guardan.
    trimmed = create(client, title="  La app no carga  ", description="\n Pantalla en blanco \t")
    assert trimmed["title"] == "La app no carga"
    assert trimmed["description"] == "Pantalla en blanco"

    # Límites exactos permitidos: 200 y 5000 caracteres.
    limit = create(client, title="x" * 200, description="y" * 5000)
    assert len(limit["title"]) == 200
    assert len(limit["description"]) == 5000

    # La fecha aportada por el origen se guarda tal cual; updated_at es del servidor.
    dated = create(client, created_at="2026-03-27T09:42:23Z")
    assert dated["created_at"] == "2026-03-27T09:42:23Z"
    assert dated["updated_at"] != dated["created_at"]
    assert set(dated) == TICKET_FIELDS


def test_get_tickets_filters_each_field_and_combinations(client, monkeypatch):
    fake_classifier(monkeypatch, category="bug", priority="P1")
    bug = create(client, title="bug")
    fake_classifier(monkeypatch, category="question", priority="P3", tags=[])
    question = create(client, title="question")
    fake_classifier(monkeypatch, category="bug", priority="P3")
    low_bug = create(client, title="low bug")
    client.patch(f"/tickets/{low_bug['id']}", json={"status": "closed"})

    def ids(**params):
        response = client.get("/tickets", params=params)
        assert response.status_code == 200
        return {t["id"] for t in response.json()}

    assert ids() == {bug["id"], question["id"], low_bug["id"]}
    assert ids(category="bug") == {bug["id"], low_bug["id"]}
    assert ids(priority="P3") == {question["id"], low_bug["id"]}
    assert ids(status="closed") == {low_bug["id"]}
    assert ids(category="bug", priority="P3", status="closed") == {low_bug["id"]}
    assert ids(category="question", priority="P1") == set()  # sin coincidencias: lista vacía
    assert ids(category="") == {bug["id"], question["id"], low_bug["id"]}  # filtro vacío se ignora

    assert all(set(t) == TICKET_FIELDS for t in client.get("/tickets").json())


def test_patch_updates_partially_keeps_immutable_fields_and_rejects_bad_input(
    client, monkeypatch
):
    fake_classifier(monkeypatch, category="feature_request", priority="P2", tags=["pdf"])
    original = create(
        client, title="Exportar", description="A PDF", created_at="2026-01-01T00:00:00Z"
    )
    url = f"/tickets/{original['id']}"

    # Cambio parcial: solo status; priority queda como estaba.
    partial = client.patch(url, json={"status": "closed"})
    assert partial.status_code == 200
    assert partial.json()["status"] == "closed"
    assert partial.json()["priority"] == "P2"

    # El resto de campos son inmutables: se ignoran aunque se envíen.
    sneaky = client.patch(url, json={"title": "otro", "category": "urgent", "tags": ["z"]})
    assert sneaky.status_code == 200
    after = sneaky.json()
    for field in ("title", "description", "category", "tags", "created_at"):
        assert after[field] == original[field]

    # Valores fuera del enum → 422 y el ticket no cambia.
    for bad in ({"status": "done"}, {"priority": "P9"}, {"status": "OPEN"}):
        assert client.patch(url, json=bad).status_code == 422
    persisted = next(t for t in client.get("/tickets").json() if t["id"] == original["id"])
    assert persisted["status"] == "closed"
    assert persisted["priority"] == "P2"

    # Ticket inexistente → 404.
    assert client.patch("/tickets/9999", json={"status": "open"}).status_code == 404


def test_patch_with_unknown_category_or_empty_values(client, monkeypatch):
    fake_classifier(monkeypatch, category="bug", priority="P1")
    original = create(client)
    url = f"/tickets/{original['id']}"

    # La categoría no es modificable: una categoría inexistente se ignora y nada cambia.
    unknown = client.patch(url, json={"category": "inexistente"})
    assert unknown.status_code == 200
    assert unknown.json() == original

    # Cuerpo vacío o valores null (nada que cambiar): 200 y el ticket queda intacto.
    for empty in ({}, {"status": None}, {"priority": None}):
        response = client.patch(url, json=empty)
        assert response.status_code == 200
        assert response.json() == original

    # Cadena vacía no es un valor del enum: 422 y sin cambios.
    for blank in ({"status": ""}, {"priority": ""}):
        assert client.patch(url, json=blank).status_code == 422
    assert client.get("/tickets").json() == [original]


def test_responsable_is_saved_trimmed_and_filterable(client, monkeypatch):
    fake_classifier(monkeypatch)
    ana = create(client, title="de Ana", responsable="  Ana  ")
    luis = create(client, title="de Luis", responsable="Luis")
    sin = create(client, title="sin responsable")
    blank = create(client, title="en blanco", responsable="   ")

    assert ana["responsable"] == "Ana"  # recortado
    assert sin["responsable"] is None
    assert blank["responsable"] is None  # solo espacios = sin responsable

    def ids(**params):
        return {t["id"] for t in client.get("/tickets", params=params).json()}

    assert ids(responsable="Ana") == {ana["id"]}
    assert ids(responsable="Luis", category="bug", status="open") == {luis["id"]}
    assert ids(responsable="Pedro") == set()
    assert len(ids(responsable="")) == 4  # filtro vacío se ignora

    too_long = client.post(
        "/tickets", json={"title": "t", "description": "d", "responsable": "x" * 101}
    )
    assert too_long.status_code == 422
