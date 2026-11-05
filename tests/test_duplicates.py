"""Tickets exactamente repetidos (tras normalizar el texto) y avisos de error al guardar."""

import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import classifier, db
from app.main import app
from app.normalize import fingerprint, normalize_text

HX = {"HX-Request": "true"}
BUG = {"category": "bug", "priority": "P2", "tags": ["x"]}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture()
def calls(monkeypatch):
    """Clasificador simulado que cuenta cuántas veces se le llama."""
    seen = []

    def fake(title, description):
        seen.append((title, description))
        return dict(BUG)

    monkeypatch.setattr("app.classifier.classify_ticket", fake)
    return seen


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------- normalización ----------


@pytest.mark.parametrize(
    "a, b",
    [
        ("¿No carga, la app?", "no carga la app"),
        ("MAYÚSCULAS y Tildes", "mayusculas y tildes"),
        ("  varios   espacios\ty\nsaltos ", "varios espacios y saltos"),
        ("La VPN: no conecta!!!", "la vpn no conecta"),
        ("Año nuevo", "ano nuevo"),
    ],
)
def test_normalization_ignores_case_accents_punctuation_and_spaces(a, b):
    assert normalize_text(a) == normalize_text(b)
    assert fingerprint(a, "x") == fingerprint(b, "x")


@pytest.mark.parametrize(
    "a, b",
    [
        ("no carga la app", "no carga la web"),  # una palabra distinta
        ("error 404", "error 405"),  # los números cuentan
        ("3.5", "35"),
    ],
)
def test_normalization_keeps_real_differences(a, b):
    assert normalize_text(a) != normalize_text(b)


def test_fingerprint_does_not_mix_title_and_description():
    assert fingerprint("ab", "c") != fingerprint("a", "bc")
    assert fingerprint("a", "b") != fingerprint("b", "a")


def test_texts_without_letters_are_compared_as_written():
    assert fingerprint("???", "x") != fingerprint("!!!", "x")
    assert fingerprint("???", "x") == fingerprint("???", "x")


# ---------- base de datos ----------


def test_db_rejects_same_text_even_with_other_punctuation_and_other_fields():
    first = db.insert_ticket("¿No carga, la app?", "Pantalla en blanco.", BUG)
    with pytest.raises(db.DuplicateTicket) as exc:
        db.insert_ticket(
            "no carga la APP",
            "pantalla   en BLANCO",
            {"category": "question", "priority": "P3", "tags": []},
            created_at="2020-01-01T00:00:00Z",
            responsable="Ana",
        )
    assert exc.value.existing["id"] == first["id"]
    assert len(db.list_tickets()) == 1


def test_db_allows_different_text_and_counts_closed_tickets_as_duplicates():
    first = db.insert_ticket("a", "b", BUG)
    db.insert_ticket("a", "b distinto", BUG)  # misma cabecera, otra descripción: es otro ticket
    db.update_ticket(first["id"], status="in_progress")
    db.update_ticket(first["id"], status="resolved")
    db.update_ticket(first["id"], status="closed")
    with pytest.raises(db.DuplicateTicket):
        db.insert_ticket("A", "B", BUG)  # el duplicado cerrado también cuenta


def test_find_duplicate_returns_the_oldest_match_or_none():
    assert db.find_duplicate("a", "b") is None
    first = db.insert_ticket("a", "b", BUG)
    assert db.find_duplicate("A!", "b?")["id"] == first["id"]


# ---------- API JSON ----------


def test_api_second_identical_ticket_is_409_with_reference_and_no_ai_call(client, calls):
    body = {"title": "Rodamientos necesarios", "description": "Hay que pedir rodamientos"}
    first = client.post("/tickets", json=body)
    assert first.status_code == 201

    second = client.post("/tickets", json={**body, "title": "rodamientos necesarios."})
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["duplicate_of"] == first.json()["id"]
    assert "exactamente igual" in detail["message"]
    assert len(calls) == 1  # no se gasta una llamada a la IA en un ticket rechazado
    assert len(client.get("/tickets").json()) == 1


def test_api_similar_but_different_tickets_are_both_saved(client, calls):
    ok = client.post("/tickets", json={"title": "La VPN no conecta", "description": "desde casa"})
    other = client.post(
        "/tickets", json={"title": "La VPN no conecta", "description": "en la oficina"}
    )
    assert (ok.status_code, other.status_code) == (201, 201)


# ---------- pantalla ----------


def test_ui_duplicate_shows_red_error_keeps_values_and_saves_nothing(client, calls):
    data = {"title": "Rodamientos <necesarios>", "description": "Pedir", "responsable": "Begoña"}
    assert client.post("/ui/tickets", data=data, headers=HX).status_code == 200

    response = client.post(
        "/ui/tickets", data={**data, "title": "rodamientos necesarios"}, headers=HX
    )
    assert response.status_code == 409
    html = response.text
    assert "HX-Trigger" not in response.headers  # no se refresca la tabla como si fuera un alta
    assert re.search(
        r'role="alert"[^>]*>\s*<span[^>]*>.*?</span>\s*<p>[^<]*NO se ha guardado', html, re.S
    )
    assert "ya existe un ticket exactamente igual (#1" in html
    assert "estado: Abierto" in html
    assert 'value="rodamientos necesarios"' in html  # conserva lo escrito
    assert re.search(r"<details[^>]*\bopen\b", html)
    assert "&lt;necesarios&gt;" in html or "necesarios" in html
    assert len(db.list_tickets()) == 1


def test_ui_duplicate_title_is_escaped_in_the_error(client, calls):
    client.post("/ui/tickets", data={"title": "<b>x</b>", "description": "d"}, headers=HX)
    html = client.post(
        "/ui/tickets", data={"title": "<b>x</b>", "description": "d"}, headers=HX
    ).text
    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


# ---------- envíos simultáneos idénticos ----------


def test_ten_identical_simultaneous_submissions_save_exactly_one(client, monkeypatch):
    def slow(title, description):
        time.sleep(0.2)  # todos pasan la comprobación previa antes de que nadie guarde
        return dict(BUG)

    monkeypatch.setattr("app.classifier.classify_ticket", slow)
    body = {"title": "Doble clic", "description": "mismo texto"}
    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(lambda _: client.post("/tickets", json=body).status_code, range(10)))
    assert sorted(codes) == [201] + [409] * 9
    assert len(db.list_tickets()) == 1


# ---------- bases de datos antiguas ----------


def test_old_database_without_fingerprint_is_migrated_and_old_duplicates_are_kept(
    tmp_path, monkeypatch
):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,"
        " description TEXT NOT NULL, category TEXT NOT NULL, priority TEXT NOT NULL,"
        " tags TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'open',"
        " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    for title in ("Mismo", "mismo!", "Otro"):  # los dos primeros ya eran repetidos
        conn.execute(
            "INSERT INTO tickets (title, description, category, priority, created_at, updated_at)"
            " VALUES (?, 'texto', 'bug', 'P1', 'c', 'u')",
            (title,),
        )
    conn.commit()
    conn.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")

    assert [t["id"] for t in db.list_tickets()] == [3, 2, 1]  # no se pierde ni se borra nada
    with db.get_connection() as c:
        assert (
            c.execute("SELECT COUNT(*) FROM tickets WHERE fingerprint IS NULL").fetchone()[0] == 0
        )
    with pytest.raises(db.DuplicateTicket) as exc:
        db.insert_ticket("MISMO?", "Texto", BUG)
    assert exc.value.existing["id"] == 1  # se señala el más antiguo
    db.insert_ticket("Nuevo", "texto", BUG)  # y lo distinto sigue entrando


# ---------- clasificación provisional (la IA falla) ----------


def test_ui_warns_when_ai_failed_but_the_ticket_is_saved(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("sin servicio")

    monkeypatch.setattr(classifier, "_call_llm", boom)
    response = client.post("/ui/tickets", data={"title": "a", "description": "b"}, headers=HX)
    assert response.status_code == 200
    assert response.headers["HX-Trigger"] == "ticket-created"
    assert "la IA no ha podido clasificarlo" in response.text
    assert "clasificación provisional" in response.text
    assert db.list_tickets()[0]["category"] == "question"


def test_ui_has_no_ai_warning_when_classification_worked(client, calls):
    response = client.post("/ui/tickets", data={"title": "a", "description": "b"}, headers=HX)
    assert response.status_code == 200
    assert "la IA no ha podido" not in response.text


def test_a_real_question_p3_classification_is_not_flagged_as_provisional(client, monkeypatch):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: {"category": "question", "priority": "P3", "tags": []},
    )
    response = client.post("/ui/tickets", data={"title": "a", "description": "b"}, headers=HX)
    assert "la IA no ha podido" not in response.text


def test_json_api_still_returns_201_when_the_ai_fails(client, monkeypatch):
    monkeypatch.setattr(classifier, "_call_llm", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    response = client.post("/tickets", json={"title": "a", "description": "b"})
    assert response.status_code == 201
    assert response.json()["category"] == "question"


# ---------- fallos del servidor: nunca se presentan como éxito ----------


def test_unexpected_server_error_is_a_500_not_a_fake_success(client, calls, monkeypatch):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(db, "insert_ticket", broken)
    response = client.post("/ui/tickets", data={"title": "a", "description": "b"}, headers=HX)
    assert response.status_code == 500
    assert "HX-Trigger" not in response.headers
    assert "Nuevo ticket" not in response.text  # no se devuelve el formulario "limpio" de éxito


def test_page_has_the_global_error_banner_wired_to_htmx_failures(client):
    html = client.get("/").text
    assert 'id="app-alert"' in html and 'role="alert"' in html
    for event in ("htmx:sendError", "htmx:responseError", "htmx:timeout", "htmx:beforeRequest"):
        assert event in html
    assert '"timeout":60000' in html  # una petición colgada acaba avisando
    assert "El ticket NO se ha guardado." in html
