"""Lógica compartida por la API JSON y la interfaz web."""

import logging

from app import classifier, db
from app.models import ALLOWED_TRANSITIONS, TicketCreate

logger = logging.getLogger(__name__)


class TicketNotFound(Exception):
    """El ticket no existe."""


DuplicateTicket = db.DuplicateTicket  # reexportado: lo lanzan find_duplicate/insert_ticket


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


def create_ticket_reporting_fallback(ticket: TicketCreate) -> tuple[dict, bool]:
    """Clasifica y guarda el ticket. Devuelve (ticket, clasificación_provisional).

    - Un fallo de la IA nunca impide crearlo: se usa el fallback y el segundo valor es True.
    - Lanza DuplicateTicket si ya existe uno exactamente igual (tras normalizar el texto).
      Se comprueba antes de llamar a la IA para no gastar una clasificación en vano; el INSERT
      lo vuelve a comprobar de forma atómica por si dos envíos iguales llegan a la vez.
    """
    existing = db.find_duplicate(ticket.title, ticket.description)
    if existing:
        raise DuplicateTicket(existing)

    try:
        classification = classifier.classify_ticket(ticket.title, ticket.description)
    except Exception:  # noqa: BLE001 - un fallo de la IA nunca debe tumbar el endpoint
        logger.warning("El clasificador ha fallado; se aplica el fallback", exc_info=True)
        classification = classifier.fallback()

    created = db.insert_ticket(
        ticket.title,
        ticket.description,
        classification,
        created_at=ticket.created_at,
        responsable=ticket.responsable,
    )
    return created, isinstance(classification, classifier.FallbackClassification)


def create_classified_ticket(ticket: TicketCreate) -> dict:
    """Como create_ticket_reporting_fallback, pero devolviendo solo el ticket."""
    return create_ticket_reporting_fallback(ticket)[0]
