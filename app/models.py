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

# Valor que el clasificador asigna cuando no puede inferir categoría o prioridad.
NOT_INFERRED = "no inferido"


class TicketCreate(BaseModel):
    """Entrada: título y descripción obligatorios; la fecha la aporta el origen si la tiene."""
    
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    created_at: str | None = None

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
    status: Status
    created_at: str
    updated_at: str
    due_date: str | None = None
