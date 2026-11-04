import logging

from fastapi import FastAPI, status

from app import classifier, db
from app.models import Ticket, TicketCreate

logger = logging.getLogger(__name__)

app = FastAPI(title="TriageBot")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tickets", status_code=status.HTTP_201_CREATED, response_model=Ticket)
def create_ticket(ticket: TicketCreate) -> dict:
    # FastAPI ya ha validado el formato: aquí solo llegan tickets con
    # title y description correctos (los erróneos devuelven 422 antes).
    try:
        classification = classifier.classify_ticket(ticket.title, ticket.description)
    except Exception:  # noqa: BLE001 - un fallo de la IA nunca debe tumbar el endpoint
        logger.warning("El clasificador ha fallado; se aplica el fallback", exc_info=True)
        classification = {**classifier.FALLBACK_CLASSIFICATION, "tags": []}

    return db.insert_ticket(
        ticket.title, ticket.description, classification, created_at=ticket.created_at
    )


# TODO: implementar durante el bootcamp.
# Endpoints esperados por los tests:
# - GET /tickets
# - PATCH /tickets/{ticket_id}
# - GET /
