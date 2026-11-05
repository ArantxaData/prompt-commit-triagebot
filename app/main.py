from typing import Literal

from fastapi import FastAPI, HTTPException, status

from app import db, ui
from app.models import Ticket, TicketCreate, TicketStats, TicketUpdate

from app.params import TicketId
from app.service import (
    DuplicateTicket,
    InvalidTransition,
    TicketNotFound,
    change_ticket,
    create_classified_ticket,
)

app = FastAPI(title="TriageBot")
app.include_router(ui.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tickets", status_code=status.HTTP_201_CREATED, response_model=Ticket)
def create_ticket(ticket: TicketCreate) -> dict:
    # FastAPI ya ha validado el formato: aquí solo llegan tickets con
    # title y description correctos (los erróneos devuelven 422 antes).
    try:
        return create_classified_ticket(ticket)
    except DuplicateTicket as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Ya existe un ticket exactamente igual (#{exc.existing['id']})",
                "duplicate_of": exc.existing["id"],
            },
        ) from None


@app.get("/tickets", response_model=list[Ticket])
def list_tickets(
    category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    responsable: str | None = None,
    sort: Literal["recent", "priority"] = "recent",
) -> list[dict]:
    # Los filtros vacíos (p. ej. un <select> sin elegir) se ignoran en db.list_tickets.
    return db.list_tickets(
        category=category, priority=priority, status=status, responsable=responsable, sort=sort
    )


@app.get("/tickets/stats", response_model=TicketStats)
def tickets_stats() -> dict:
    """Recuento de tickets: total y desglose por categoría, prioridad y estado."""
    return db.ticket_stats()


@app.patch("/tickets/{ticket_id}", response_model=Ticket)
def update_ticket(ticket_id: TicketId, changes: TicketUpdate) -> dict:
    # status y priority ya vienen validados contra el enum (si no, 422).
    try:
        return change_ticket(ticket_id, status=changes.status, priority=changes.priority)
    except TicketNotFound:
        raise HTTPException(status_code=404, detail="Ticket no encontrado") from None
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
