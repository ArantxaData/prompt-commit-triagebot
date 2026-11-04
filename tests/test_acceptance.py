import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Test client with an isolated database path when the app supports DATABASE_URL."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return TestClient(app)


def fake_classification(category="bug", priority="P1", tags=None):
    return {
        "category": category,
        "priority": priority,
        "tags": tags if tags is not None else ["login", "customer-impact"],
    }


def test_post_ticket_creates_ticket_with_classification(client, monkeypatch):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: fake_classification(),
    )

    response = client.post(
        "/tickets",
        json={
            "title": "La app no carga",
            "description": "Desde esta mañana aparece una pantalla en blanco al iniciar sesión",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert isinstance(data["id"], int)
    assert data["title"] == "La app no carga"
    assert data["description"].startswith("Desde esta mañana")
    assert data["category"] == "bug"
    assert data["priority"] == "P1"
    assert data["tags"] == ["login", "customer-impact"]
    assert data["status"] == "open"
    assert "created_at" in data
    assert "updated_at" in data


def test_created_ticket_is_persisted_and_listed(client, monkeypatch):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: fake_classification(category="feature_request", priority="P2", tags=["export"]),
    )

    created = client.post(
        "/tickets",
        json={"title": "Exportar a PDF", "description": "Necesitamos exportar informes a PDF"},
    )
    assert created.status_code == 201

    listed = client.get("/tickets")

    assert listed.status_code == 200
    tickets = listed.json()
    assert len(tickets) >= 1
    assert any(ticket["title"] == "Exportar a PDF" for ticket in tickets)
    assert any(ticket["category"] == "feature_request" for ticket in tickets)


def test_post_ticket_rejects_invalid_input(client):
    invalid_payloads = [
        {"title": "", "description": "Descripción válida"},
        {"title": "   ", "description": "Descripción válida"},
        {"title": "x" * 201, "description": "Descripción válida"},
        {"title": "Título válido", "description": ""},
        {"title": "Título válido", "description": "x" * 5001},
    ]

    for payload in invalid_payloads:
        response = client.post("/tickets", json=payload)
        assert response.status_code == 422


def test_classifier_failure_uses_safe_fallback(client, monkeypatch):
    def broken_classifier(title, description):
        raise RuntimeError("Anthropic is unavailable")

    monkeypatch.setattr("app.classifier.classify_ticket", broken_classifier)

    response = client.post(
        "/tickets",
        json={
            "title": "No entiendo cómo cambiar mi contraseña",
            "description": "El cliente pregunta cómo resetear la contraseña desde el portal",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["category"] == "question"
    assert data["priority"] == "P3"
    assert data["tags"] == []
    assert data["status"] == "open"


def test_update_ticket_and_filter_by_status_priority_category(client, monkeypatch):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: fake_classification(category="urgent", priority="P1", tags=["demo"]),
    )

    created = client.post(
        "/tickets",
        json={
            "title": "Esto urge porque tenemos demo el viernes",
            "description": "El cliente necesita una solución antes de una demo crítica",
        },
    )
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    patched = client.patch(f"/tickets/{ticket_id}", json={"status": "in_progress", "priority": "P2"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "in_progress"
    assert patched.json()["priority"] == "P2"

    filtered = client.get("/tickets", params={"category": "urgent", "priority": "P2", "status": "in_progress"})
    assert filtered.status_code == 200
    tickets = filtered.json()
    assert len(tickets) == 1
    assert tickets[0]["id"] == ticket_id
