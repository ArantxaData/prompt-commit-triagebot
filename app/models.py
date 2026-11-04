from typing import Literal

from pydantic import BaseModel, Field, field_validator, ConfigDict

ALLOWED_CATEGORIES = {"bug", "feature_request", "question", "urgent"}
ALLOWED_PRIORITIES = {"P1", "P2", "P3"}
ALLOWED_STATUSES = {"open", "in_progress", "closed"}

Category = Literal["bug", "feature_request", "question", "urgent"]
Priority = Literal["P1", "P2", "P3"]
Status = Literal["open", "in_progress", "closed"]


class TicketCreate(BaseModel):
    """Entrada: título y descripción obligatorios; la fecha la aporta el origen si la tiene."""
    
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True
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
    category: Category
    priority: Priority
    tags: list[str]
    status: Status
    created_at: str
    updated_at: str
