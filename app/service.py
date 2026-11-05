"""Lógica compartida por la API JSON y la interfaz web."""

import logging

from app import classifier, db
from app.models import ALLOWED_TRANSITIONS, TicketCreate

logger = logging.getLogger(__name__)


class TicketNotFound(Exception):
    """El ticket no existe."""


class InvalidTransition(Exception):
    """El cambio de estado no está permitido (ver ALLOWED_TRANSITIONS)."""


def change_ticket(ticket_id: int, status: str | None = None, priority: str | None = None) -> dict:
    """Cambia estado y/o prioridad aplicando las reglas de transición de estado.

    Mantener el mismo estado es siempre válido. Lo usan la API JSON y la pantalla.
    """
    current = db.get_ticket(ticket_id)
    if current is None:
        raise TicketNotFound(ticket_id)
    if (
        status
        and status != current["status"]
        and status not in ALLOWED_TRANSITIONS[current["status"]]
    ):
        raise InvalidTransition(f"Transición no permitida: {current['status']} -> {status}")
    return db.update_ticket(ticket_id, status=status, priority=priority)


def create_classified_ticket(ticket: TicketCreate) -> dict:
    """Clasifica el ticket y lo guarda. Un fallo de la IA nunca impide crearlo."""
    try:
        classification = classifier.classify_ticket(ticket.title, ticket.description)
    except Exception:  # noqa: BLE001 - un fallo de la IA nunca debe tumbar el endpoint
        logger.warning("El clasificador ha fallado; se aplica el fallback", exc_info=True)
        classification = {**classifier.FALLBACK_CLASSIFICATION, "tags": []}

    return db.insert_ticket(
        ticket.title,
        ticket.description,
        classification,
        created_at=ticket.created_at,
        responsable=ticket.responsable,
    )
