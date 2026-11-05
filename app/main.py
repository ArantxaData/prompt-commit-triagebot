from typing import Literal

from fastapi import FastAPI, HTTPException, status

from app import db, ui
from app.models import Ticket, TicketCreate, TicketUpdate
from app.service import create_classified_ticket

app = FastAPI(title="TriageBot")
app.include_router(ui.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tickets", status_code=status.HTTP_201_CREATED, response_model=Ticket)
def create_ticket(ticket: TicketCreate) -> dict:
    # FastAPI ya ha validado el formato: aquí solo llegan tickets con
    # title y description correctos (los erróneos devuelven 422 antes).
    return create_classified_ticket(ticket)


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


@app.patch("/tickets/{ticket_id}", response_model=Ticket)
def update_ticket(ticket_id: int, changes: TicketUpdate) -> dict:
    # status y priority ya vienen validados contra el enum (si no, 422).
    ticket = db.update_ticket(ticket_id, status=changes.status, priority=changes.priority)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return ticket
