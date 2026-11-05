import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_CATEGORIES = {"bug", "feature_request", "question", "urgent"}
ALLOWED_PRIORITIES = {"P1", "P2", "P3"}
ALLOWED_STATUSES = {"open", "in_progress", "resolved", "closed"}

# Transiciones de estado permitidas en PATCH. Reabrir (resolved/closed -> in_progress)
# no toca la fecha límite. Mantener el mismo estado es siempre válido (no-op).
ALLOWED_TRANSITIONS = {
    "open": {"in_progress", "resolved"},
    "in_progress": {"resolved"},
    "resolved": {"closed", "in_progress"},
    "closed": {"in_progress"},
}

Category = Literal["bug", "feature_request", "question", "urgent"]
Priority = Literal["P1", "P2", "P3"]
Status = Literal["open", "in_progress", "resolved", "closed"]

# Los IDs son enteros autogenerados de SQLite: de 1 al mayor entero de 64 bits con signo.
# Fuera de ese rango SQLite lanzaría un error interno (500) en lugar de "no existe".
MAX_TICKET_ID = 2**63 - 1

# Valor que el clasificador asigna cuando no puede inferir categoría o prioridad.
NOT_INFERRED = "no inferido"

# Caracteres admitidos en los textos de un ticket: lista blanca de escritura latina.
# Cada rango son puntos de código Unicode. De ellos se genera LATIN_CLASS, el contenido de una
# clase de caracteres con escapes que vale igual en Python (re) y en JavaScript: el formulario
# la recibe de aquí, así cliente y servidor no pueden discrepar. Se admiten además los saltos de
# línea y tabuladores. Quedan fuera emojis, CJK, cirílico, árabe, griego, ZWJ e invisibles.
_LATIN_RANGES = (
    (0x20, 0x7E),  # ASCII imprimible
    (0xA0, 0x24F),  # Latin-1 (ñ á ü ¿ ¡ ç « » € ° ·) y Latin extendido A y B (ł ő ş)
    (0x300, 0x36F),  # diacríticos combinantes (acentos escritos en forma NFD)
    (0x1E00, 0x1EFF),  # Latin extendido adicional (ạ ẹ ế)
    (0x2010, 0x2015),  # guiones
    (0x2018, 0x201F),  # comillas tipográficas
    (0x2020, 0x2022),  # daga, doble daga y viñeta
    (0x2026, 0x2026),  # puntos suspensivos
    (0x2030, 0x2030),  # por mil
    (0x2032, 0x2033),  # prima y doble prima
    (0x2039, 0x203A),  # comillas angulares simples
    (0x20AC, 0x20AC),  # euro
    (0x2122, 0x2122),  # marca registrada (TM)
    (0x2190, 0x2194),  # flechas
    (0x2212, 0x2212),  # signo menos
)
_BACKSLASH = chr(92)


def _escape(code_point: int) -> str:
    return f"{_BACKSLASH}u{code_point:04x}"


LATIN_CLASS = r"\t\n\r" + "".join(
    _escape(a) if a == b else f"{_escape(a)}-{_escape(b)}" for a, b in _LATIN_RANGES
)
_LATIN_ONLY = re.compile(f"[{LATIN_CLASS}]*")
LATIN_ONLY_MESSAGE = "Solo se admiten caracteres latinos (sin emojis ni otros alfabetos)."


def is_latin_text(text: str) -> bool:
    """True si todos los caracteres del texto están en la lista blanca latina."""
    return _LATIN_ONLY.fullmatch(text) is not None


class TicketCreate(BaseModel):
    """Entrada: título y descripción obligatorios; la fecha la aporta el origen si la tiene."""
    
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    created_at: str | None = None
    responsable: str | None = Field(default=None, max_length=100)

    @field_validator("title", "description", "responsable", mode="after")
    @classmethod
    def _only_latin_characters(cls, v: str | None) -> str | None:
        if v is not None and not is_latin_text(v):
            raise ValueError(LATIN_ONLY_MESSAGE)
        return v

    @field_validator("responsable", mode="after")
    @classmethod
    def _blank_responsable_is_none(cls, v: str | None) -> str | None:
        return v or None  # "" o solo espacios (ya recortados) = sin responsable

    @field_validator("title", "description", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v
      
      
      


class TicketUpdate(BaseModel):
    status: Status | None = None
    priority: Priority | None = None


class Ticket(BaseModel):
    id: int
    title: str
    description: str
    category: Category | Literal["no inferido"]
    priority: Priority | Literal["no inferido"]
    tags: list[str]
    responsable: str | None = None
    status: Status
    created_at: str
    updated_at: str
    due_date: str | None = None


class TicketStats(BaseModel):
    """Respuesta de GET /tickets/stats: el total y el recuento por cada valor de cada campo."""

    total: int
    by_category: dict[str, int]
    by_priority: dict[str, int]
    by_status: dict[str, int]
