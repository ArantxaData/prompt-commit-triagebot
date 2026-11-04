from fastapi import FastAPI

app = FastAPI(title="TriageBot")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# TODO: implementar durante el bootcamp.
# Endpoints esperados por los tests:
# - POST /tickets
# - GET /tickets
# - PATCH /tickets/{ticket_id}
# - GET /
