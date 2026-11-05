import logging

from fastapi import FastAPI, HTTPException, status

from app import classifier, db
from app.models import Ticket, TicketCreate, TicketUpdate

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
        ticket.title,
        ticket.description,
        classification,
        created_at=ticket.created_at,
        responsable=ticket.responsable,
    )


@app.get("/tickets", response_model=list[Ticket])
def list_tickets(
    category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    responsable: str | None = None,
) -> list[dict]:
    # Los filtros vacíos (p. ej. un <select> sin elegir) se ignoran en db.list_tickets.
    return db.list_tickets(
        category=category, priority=priority, status=status, responsable=responsable
    )


@app.patch("/tickets/{ticket_id}", response_model=Ticket)
def update_ticket(ticket_id: int, changes: TicketUpdate) -> dict:
    # status y priority ya vienen validados contra el enum (si no, 422).
    ticket = db.update_ticket(ticket_id, status=changes.status, priority=changes.priority)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return ticket


# TODO: implementar durante el bootcamp.
# Endpoints esperados por los tests:
# - GET /
