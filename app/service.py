"""Lógica compartida por la API JSON y la interfaz web."""

import logging

from app import classifier, db
from app.models import TicketCreate

logger = logging.getLogger(__name__)


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
