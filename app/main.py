from fastapi import FastAPI, status

from app.models import TicketCreate

app = FastAPI(title="TriageBot")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(ticket: TicketCreate) -> dict[str, str]:
    # FastAPI ya ha validado el formato: aquí solo llegan tickets con
    # title y description correctos (los erróneos devuelven 422 antes).
    # TODO (persistencia): guardar el ticket en SQLite vía app/db.py.
    return ticket.model_dump()


# TODO: implementar durante el bootcamp.
# Endpoints esperados por los tests:
# - GET /tickets
# - PATCH /tickets/{ticket_id}
# - GET /
