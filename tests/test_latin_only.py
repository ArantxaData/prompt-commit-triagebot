"""Solo caracteres latinos en título, descripción y responsable (sin emojis ni otros alfabetos).

Los caracteres invisibles o ambiguos se construyen con chr(0x...) para que se vea qué se prueba.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.models import LATIN_CLASS, LATIN_ONLY_MESSAGE, is_latin_text

HX = {"HX-Request": "true"}

NBSP = chr(0xA0)  # espacio duro
ZWJ = chr(0x200D)  # unificador de ancho cero (une emojis)
ZWSP = chr(0x200B)  # espacio de ancho cero (invisible)
VS16 = chr(0xFE0F)  # selector de variación de emoji
KEYCAP = chr(0x20E3)  # marco combinante de tecla
ACUTE = chr(0x301)  # acento agudo combinante
TILDE = chr(0x303)  # tilde combinante

ALLOWED = [
    "Hello world 123 !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
    "¿Cómo reseteo la contraseña? ¡Urgente! Ñandú ñoño ç ü ß",
    "Łódź Őrség Şişli Việt Nam ạ ẹ",  # Latin extendido A/B y adicional
    "“comillas” ‘simples’ — guion – medio … • † ‰ ′ ″ ‹ ›",  # puntuación tipográfica
    "Precio: 20 € ™ → ← ↔ 5 − 3 © ® ° ± × ÷ ª º",
    "«francés» l·l 1" + NBSP + "2",  # comillas angulares, punto medio catalán, espacio duro
    "línea1\nlínea2\r\n\ttabulado",
    "e" + ACUTE + " n" + TILDE,  # letras con diacrítico combinante (forma NFD)
]

BLOCKED = [
    "你好", "漢字", "日本語のテスト", "한국어",  # CJK
    "Привет", "مرحبا", "שלום", "αβγ", "ไทย",  # cirílico, árabe, hebreo, griego, tailandés
    "😀", "hola 🙂", "👨" + ZWJ + "👩" + ZWJ + "👧", "1" + VS16 + KEYCAP, "🇪🇸",  # emojis
    "✓", "★", "❤", "☺",  # símbolos tipo emoji
    "ｱｲｳ", "Ａ",  # formas de ancho medio y completo
    "zero" + ZWSP + "width", "tab\x00null", "bell\x07",  # invisibles y de control
]  # fmt: skip


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: {"category": "bug", "priority": "P1", "tags": []},
    )


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.mark.parametrize("text", ALLOWED)
def test_latin_text_is_allowed(text):
    assert is_latin_text(text)


@pytest.mark.parametrize("text", BLOCKED)
def test_non_latin_text_is_rejected(text):
    assert not is_latin_text(text)


@pytest.mark.parametrize("field", ["title", "description", "responsable"])
@pytest.mark.parametrize("bad", ["你好", "hola 😀", "Привет"])
def test_api_rejects_non_latin_in_every_text_field(client, field, bad):
    payload = {"title": "t", "description": "d", "responsable": "Ana"}
    payload[field] = bad
    response = client.post("/tickets", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == field  # y el JSON del error se serializa
    assert db.list_tickets() == []  # no se guarda nada


def test_api_accepts_spanish_text_with_accents_and_typographic_punctuation(client):
    payload = {
        "title": "¿Cómo restablezco la contraseña?",
        "description": "El usuario dice: “no me deja entrar” — urgente… ¡gracias! (20 €)",
        "responsable": "Ñoño Pérez",
    }
    response = client.post("/tickets", json=payload)
    assert response.status_code == 201
    assert response.json()["title"] == payload["title"]
    assert response.json()["responsable"] == "Ñoño Pérez"


@pytest.mark.parametrize(
    ("field", "data"),
    [
        ("title", {"title": "Fallo 😀", "description": "d", "responsable": ""}),
        ("description", {"title": "t", "description": "没有网络", "responsable": ""}),
        ("responsable", {"title": "t", "description": "d", "responsable": "Иван"}),
    ],
)
def test_form_shows_the_message_next_to_the_field_and_saves_nothing(client, field, data):
    response = client.post("/ui/tickets", data=data, headers=HX)
    assert response.status_code == 422
    assert LATIN_ONLY_MESSAGE in response.text
    assert f'id="e-{field}"' in response.text  # el aviso va junto al campo concreto
    assert db.list_tickets() == []


def test_form_keeps_what_the_user_typed_when_it_is_rejected(client):
    response = client.post(
        "/ui/tickets", data={"title": "Mi título", "description": "你好"}, headers=HX
    )
    assert response.status_code == 422
    assert 'value="Mi título"' in response.text


def test_page_hands_the_same_whitelist_to_the_browser(client):
    html = client.get("/").text
    # La lista blanca va como atributo del body (Jinja la escapa para HTML) y es la misma
    # que usa el servidor, generada a partir de los rangos de app/models.py.
    assert f'data-latin="{LATIN_CLASS}"' in html
    assert LATIN_CLASS.startswith("\\t\\n\\r\\u0020-\\u007e")
    assert "caracteres latinos" in html  # textos de aviso del script


def test_the_whitelist_is_a_valid_class_for_javascript_too():
    # Sin indicador "u", JavaScript solo entiende \uXXXX de 4 cifras: sin \u{...} ni
    # puntos de código fuera del plano básico. LATIN_CLASS solo usa ese formato.
    import re

    body = LATIN_CLASS.replace("\\t", "").replace("\\n", "").replace("\\r", "")
    assert re.fullmatch(r"(\\u[0-9a-f]{4}(-\\u[0-9a-f]{4})?)+", body)


def test_seed_tickets_are_all_latin():
    seed = Path(__file__).resolve().parent.parent / "seed_tickets.json"
    tickets = json.loads(seed.read_text(encoding="utf-8"))
    bad = [
        t["title"]
        for t in tickets
        if not (is_latin_text(t["title"]) and is_latin_text(t["description"]))
    ]
    assert bad == []


def test_existing_tickets_with_other_characters_are_still_displayed(client):
    # Datos antiguos (insertados antes de la restricción) no deben romper la página.
    classification = {"category": "bug", "priority": "P1", "tags": []}
    db.insert_ticket("历史工单 😀", "descripción", classification)
    response = client.get("/")
    assert response.status_code == 200
    assert "历史工单" in response.text
