"""Parámetros de ruta compartidos por la API JSON y la interfaz web."""

from typing import Annotated

from fastapi import Path

from app.models import MAX_TICKET_ID

# ID de ticket válido: entero de 1 a MAX_TICKET_ID. Fuera de rango -> 422 (nunca un 500).
TicketId = Annotated[int, Path(ge=1, le=MAX_TICKET_ID)]
