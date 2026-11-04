# SPEC.md — Contrato funcional de TriageBot

> **Equipo A (Vibe):** usad este SPEC tal cual. No lo modifiquéis.
>
> **Equipo B (Spec-Driven):** este SPEC está incompleto a propósito. Vuestra tarea es completarlo
> antes de pedir código: casos límite, errores, funcionalidades de cada pantalla, tests propios y
> todo lo que traslade el cliente en `BRIEF.md`.

## 1. Objetivo

Construir una aplicación web interna para registrar, clasificar y consultar tickets de soporte.

## 2. Modelo de datos

### Ticket

Campos mínimos:

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | int | Autogenerado |
| `title` | str | Obligatorio, 1–200 caracteres tras trim |
| `description` | str | Obligatorio, 1–5000 caracteres tras trim |
| `category` | str | `bug`, `feature_request`, `question`, `urgent` |
| `priority` | str | `P1`, `P2`, `P3` |
| `tags` | list[str] | Lista, puede estar vacía |
| `status` | str | `open`, `in_progress`, `closed` |
| `created_at` | datetime | UTC, generado en servidor |
| `updated_at` | datetime | UTC, actualizado en cambios relevantes |

Valores por defecto:

- `status`: `open`
- fallback de clasificación: `category="question"`, `priority="P3"`, `tags=[]`

Los valores de `category`, `priority` y `status` son vinculantes: exactamente esos, en minúsculas
(salvo `P1`–`P3`). Si el código devuelve `"URGENT"`, los tests fallan.

## 3. Arquitectura de módulos

Estructura recomendada:

```text
app/
  __init__.py
  main.py          # FastAPI app y endpoints HTTP
  models.py        # Modelos Pydantic (Ticket, TicketCreate, TicketUpdate)
  db.py            # Conexión y operaciones SQLite (sqlite3)
  classifier.py    # ÚNICO módulo que llama al LLM

templates/
  index.html
  _tickets_table.html

tests/
  test_acceptance.py
```

Regla importante:

> Todo lo que llame a una API de IA (OpenRouter u otra) vive solo en `app/classifier.py`.
> Si hay llamadas al SDK en `main.py`, algo se ha torcido. Y `classifier.py` no importa nada de FastAPI.

El stack cerrado no está aquí: está en `BRIEF.md`, sección «Restricciones técnicas».

## 4. API HTTP

| Endpoint | Devuelve | Errores |
|---|---|---|
| `GET /health` | `200 {"status": "ok"}` | — |
| `POST /tickets` | `201` con el ticket ya clasificado | `422` si título o descripción vacíos o demasiado largos |
| `GET /tickets` | `200` lista, filtrable por `category`, `priority` y `status` | — |
| `PATCH /tickets/{ticket_id}` | `200` ticket actualizado | `404` si no existe · `422` si el valor no está en el enum |
| `GET /` | `200` HTML con el tablero (ver §6) | — |

### `POST /tickets`

Crea un ticket y lo clasifica. La clasificación ocurre de forma síncrona durante la petición: la
respuesta ya trae `category`, `priority` y `tags`.

Request JSON:

```json
{
  "title": "La app no carga",
  "description": "Desde esta mañana aparece una pantalla en blanco al iniciar sesión"
}
```

Response `201`:

```json
{
  "id": 1,
  "title": "La app no carga",
  "description": "Desde esta mañana aparece una pantalla en blanco al iniciar sesión",
  "category": "bug",
  "priority": "P1",
  "tags": ["login", "blank-screen"],
  "status": "open",
  "created_at": "2026-06-29T09:30:00Z",
  "updated_at": "2026-06-29T09:30:00Z"
}
```

Errores:

- `422` si `title` está vacío (o solo espacios) o supera 200 caracteres.
- `422` si `description` está vacía (o solo espacios) o supera 5000 caracteres.

### `GET /tickets`

Lista tickets en JSON. Query params opcionales: `category`, `priority`, `status`.

```text
GET /tickets?category=bug&priority=P1&status=open
```

Devuelve `200` con una lista de tickets con la misma forma que la respuesta de `POST /tickets`.

### `PATCH /tickets/{ticket_id}`

Solo se pueden cambiar `status` y `priority`. El resto de campos son inmutables tras la creación.

```json
{
  "status": "in_progress",
  "priority": "P2"
}
```

- `status`: `open`, `in_progress`, `closed`
- `priority`: `P1`, `P2`, `P3`

Errores:

- `404` si no existe el ticket.
- `422` si el valor no pertenece al enum permitido.

`GET /` devuelve HTML; `GET /tickets` devuelve JSON. No los confundáis: los tests y el agente del
Día 3 usan el JSON.

## 5. Clasificador IA

Función esperada:

```python
def classify_ticket(title: str, description: str) -> dict:
    ...
```

Contrato de salida:

```python
{
    "category": "bug" | "feature_request" | "question" | "urgent",
    "priority": "P1" | "P2" | "P3",
    "tags": list[str],
}
```

Llamada al LLM: SDK de `openai` apuntando a OpenRouter (`base_url="https://openrouter.ai/api/v1"`),
modelo `openai/gpt-oss-120b`, API key desde la variable de entorno `OPENROUTER_API_KEY`.

Requisitos no negociables:

- **Valida la salida.** Si el LLM devuelve `"category": "URGENT"` (mayúsculas) o una categoría
  inventada, aplica el fallback. No propagues basura.
- **Como mucho un reintento** si la llamada falla. Si vuelve a fallar, fallback.
- **Nunca propaga excepciones del SDK.** Ante cualquier problema devuelve el fallback:

```python
{"category": "question", "priority": "P3", "tags": []}
```

El SPEC no fija el prompt: lo decidís vosotros. Sí es obligatorio que la salida cumpla el contrato.

## 6. Frontend mínimo

`GET /` devuelve una página HTML con:

1. Formulario para crear ticket.
2. Tablero de tickets.
3. Filtros por categoría, prioridad y estado.

Recomendación:

- Usar Jinja2 templates.
- Usar HTMX para refrescar la tabla sin recargar toda la página.
- No escribir HTML grande como string dentro de `main.py`.

## 7. Tests obligatorios

El archivo `tests/test_acceptance.py` contiene los 5 tests de aceptación. No se modifica.

Los tests comprueban:

1. Crear un ticket válido devuelve `201` y clasificación.
2. El ticket creado queda persistido y aparece en `GET /tickets`.
3. Input inválido devuelve `422`.
4. Si el clasificador falla, se aplica fallback y la app no cae.
5. Se puede actualizar estado/prioridad y filtrar tickets.

## 8. No negociable

- No commitear `.env`.
- No hardcodear API keys.
- No propagar excepciones del SDK de la IA al endpoint.
- No modificar los tests de aceptación para hacerlos pasar.
- No introducir React ni frontend complejo.
