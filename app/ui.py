"""Interfaz web (HTML + HTMX). Devuelve páginas y fragmentos, nunca JSON."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app import db
from app.models import (
    ALLOWED_TRANSITIONS,
    LATIN_CLASS,
    NOT_INFERRED,
    TicketCreate,
    TicketUpdate,
)
from app.params import TicketId
from app.service import (
    DuplicateTicket,
    InvalidTransition,
    TicketNotFound,
    change_ticket,
    create_ticket_reporting_fallback,
)

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

STATUSES = [
    ("open", "Abierto"),
    ("in_progress", "En curso"),
    ("resolved", "Resuelto"),
    ("closed", "Cerrado"),
]
PRIORITIES = [("P1", "P1 · Alta"), ("P2", "P2 · Media"), ("P3", "P3 · Baja")]
CATEGORIES = [
    ("bug", "Bug"),
    ("feature_request", "Solicitud"),
    ("question", "Consulta"),
    ("urgent", "Urgente"),
]
templates.env.globals.update(
    STATUSES=STATUSES,
    PRIORITIES=PRIORITIES,
    CATEGORIES=CATEGORIES,
    NOT_INFERRED=NOT_INFERRED,
    CATEGORY_LABELS=dict(CATEGORIES),
    TRANSITIONS=ALLOWED_TRANSITIONS,  # el desplegable de estado solo ofrece lo permitido
    LATIN_CLASS=LATIN_CLASS,  # la misma lista blanca de caracteres que valida el servidor
)


def _filters(
    status: str | None, priority: str | None, category: str | None, responsable: str | None
) -> dict:
    """Filtros de la pantalla. Sin indicar estado se muestran solo los abiertos."""
    return {
        "status": "open" if status is None else status,
        "priority": priority or "",
        "category": category or "",
        "responsable": (responsable or "").strip(),
    }


def _tickets(filters: dict) -> list[dict]:
    return db.list_tickets(
        status=None if filters["status"] in ("", "all") else filters["status"],
        priority=filters["priority"],
        category=filters["category"],
        responsable=filters["responsable"],
        sort="priority",
    )


def _html(request: Request, name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    context = {"today": datetime.now(UTC).date().isoformat(), **context}  # para marcar vencidos
    response = templates.TemplateResponse(request, name, context, status_code=status_code)
    response.headers["Vary"] = "HX-Request"  # misma URL: página completa o fragmento
    return response


def _form_context(
    values: dict | None = None,
    errors: dict | None = None,
    alert: str | None = None,
    notice: str | None = None,
) -> dict:
    """alert: error que impide guardar (rojo). notice: ticket guardado, pero con una pega."""
    return {"values": values or {}, "errors": errors or {}, "alert": alert, "notice": notice}


def _error_message(error: dict) -> str:
    if error["type"] == "string_too_short":
        return "Este campo es obligatorio."
    if error["type"] == "string_too_long":
        return f"Máximo {error['ctx']['max_length']} caracteres."
    if error["type"] == "value_error":  # validadores propios (p. ej. solo caracteres latinos)
        return str(error["ctx"]["error"])
    return "Valor no válido."


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    responsable: str | None = None,
) -> HTMLResponse:
    filters = _filters(status, priority, category, responsable)
    context = {"filters": filters, "tickets": _tickets(filters)}
    is_fragment = (
        request.headers.get("HX-Request") == "true"
        and request.headers.get("HX-History-Restore-Request") != "true"
    )
    if is_fragment:
        return _html(request, "_tickets_table.html", context)
    # El filtro de responsable es un desplegable con los existentes; si la URL trae uno que ya
    # no existe se conserva como opción para no perder el filtro activo.
    responsables = db.list_responsables()
    if filters["responsable"] and filters["responsable"] not in responsables:
        responsables.append(filters["responsable"])
    return _html(
        request,
        "index.html",
        {**context, "form": _form_context(), "responsables": responsables},
    )


# Páginas de estadísticas: clave de db.ticket_stats() -> (título del grupo, textos en español).
STAT_GROUPS = (
    ("by_category", "Categoría", {**dict(CATEGORIES), NOT_INFERRED: "no inferido"}),
    ("by_priority", "Prioridad", {**dict(PRIORITIES), NOT_INFERRED: "no inferido"}),
    ("by_status", "Estado", dict(STATUSES)),
)


def _stats_groups(stats: dict) -> list[dict]:
    """Los desgloses de db.ticket_stats() listos para pintar: título y filas (texto, recuento)."""
    return [
        {
            "title": title,
            "rows": [(labels.get(value, value), count) for value, count in stats[key].items()],
        }
        for key, title, labels in STAT_GROUPS
    ]


@router.get("/estadisticas", response_class=HTMLResponse)
def stats_page(request: Request) -> HTMLResponse:
    """Tabla resumen: total de tickets y recuento por categoría, prioridad y estado."""
    stats = db.ticket_stats()
    context = {"total": stats["total"], "groups": _stats_groups(stats)}
    return _html(request, "estadisticas.html", context)


@router.post("/ui/tickets", response_class=HTMLResponse)
def create_ticket_form(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    responsable: str = Form(""),
) -> HTMLResponse:
    # Los navegadores envían los saltos de línea como \r\n (2 caracteres) aunque el campo los
    # cuenta como 1: se normalizan para que el límite del servidor coincida con el del campo.
    description = description.replace("\r\n", "\n").replace("\r", "\n")
    values = {"title": title, "description": description, "responsable": responsable}
    try:
        data = TicketCreate(**values)
    except ValidationError as exc:
        errors = {e["loc"][0]: _error_message(e) for e in exc.errors()}
        return _html(
            request, "_new_ticket_form.html", {"form": _form_context(values, errors)}, 422
        )

    try:
        _, provisional = create_ticket_reporting_fallback(data)
    except DuplicateTicket as exc:
        found = exc.existing
        alert = (
            "El ticket NO se ha guardado: ya existe un ticket exactamente igual "
            f"(#{found['id']} «{found['title']}», estado: {dict(STATUSES)[found['status']]})."
        )
        return _html(
            request, "_new_ticket_form.html", {"form": _form_context(values, alert=alert)}, 409
        )

    notice = None
    if provisional:
        notice = (
            "El ticket se ha guardado, pero la IA no ha podido clasificarlo: queda con una "
            "clasificación provisional (consulta, P3). Revísalo a mano."
        )
    response = _html(request, "_new_ticket_form.html", {"form": _form_context(notice=notice)})
    response.headers["HX-Trigger"] = "ticket-created"  # la tabla se vuelve a pedir sola
    return response


@router.patch("/ui/tickets/{ticket_id}", response_class=HTMLResponse)
def update_ticket_row(
    request: Request,
    ticket_id: TicketId,
    status: str | None = Form(None),
    priority: str | None = Form(None),
) -> HTMLResponse:
    # "" y "no inferido" no son valores asignables: se ignoran (no cambian nada).
    priority = None if priority in ("", NOT_INFERRED) else priority
    try:
        changes = TicketUpdate(status=status or None, priority=priority)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Valor no permitido") from exc
    try:
        ticket = change_ticket(ticket_id, status=changes.status, priority=changes.priority)
    except TicketNotFound:
        raise HTTPException(status_code=404, detail="Ticket no encontrado") from None
    except InvalidTransition as exc:
        # Se repinta la fila sin cambios (el desplegable vuelve a su valor) con el motivo.
        current = db.get_ticket(ticket_id)
        return _html(request, "_ticket_row.html", {"t": current, "error": str(exc)}, 409)
    return _html(request, "_ticket_row.html", {"t": ticket})
