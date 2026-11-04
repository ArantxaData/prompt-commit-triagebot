from pydantic import BaseModel, ConfigDict, Field

ALLOWED_CATEGORIES = {"bug", "feature_request", "question", "urgent"}
ALLOWED_PRIORITIES = {"P1", "P2", "P3"}
ALLOWED_STATUSES = {"open", "in_progress", "closed"}


class TicketCreate(BaseModel):
    """Payload aceptado por POST /tickets.

    Solo se admiten `title` y `description`: cualquier otro campo, tipo
    incorrecto o texto vacío (tras trim) se rechaza con 422.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
