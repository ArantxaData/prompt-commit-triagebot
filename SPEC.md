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
| `category` | str | `bug`, `feature_request`, `question`, `urgent` o `no inferido` |
| `priority` | str | `P1`, `P2`, `P3` o `no inferido` |
| `tags` | list[str] | Lista, puede estar vacía |
| `status` | str | `open`, `in_progress`, `resolved`, `closed` (ver transiciones en §2.2) |
| `responsable` | str \| null | Opcional, hasta 100 caracteres tras trim; vacío o solo espacios = `null`. Se indica al crear el ticket y no cambia después |
| `created_at` | datetime | UTC, generado en servidor |
| `updated_at` | datetime | UTC, actualizado en cambios relevantes |
| `due_date` | date \| null | `YYYY-MM-DD`, UTC. Se calcula a partir de la prioridad (ver §2.1) |

Valores por defecto:

- `status`: `open`
- fallback de clasificación: `category="question"`, `priority="P3"`, `tags=[]`

Los valores de `category`, `priority` y `status` son vinculantes: exactamente esos, en minúsculas
(salvo `P1`–`P3`). Si el código devuelve `"URGENT"`, los tests fallan.

`no inferido` es el valor que usa el clasificador cuando no puede deducir con claridad la categoría
o la prioridad. Es válido y se guarda tal cual; no activa el fallback.

### 2.1 Fecha límite (`due_date`)

Se calcula en el servidor al crear el ticket, desde la fecha de hoy (UTC), según la prioridad:

| `priority` | `due_date` |
|---|---|
| `P1` | hoy |
| `P2` | mañana |
| `P3` | dentro de dos días |
| `no inferido` | `null` |

- La referencia es el día en que se guarda el ticket, no su `created_at`.
- Si `priority` cambia con `PATCH`, `due_date` se recalcula desde hoy.
- Cambiar solo `status` (incluido reabrir un ticket) **no** modifica `due_date`.
- `due_date` no se puede enviar ni modificar directamente.

### 2.2 Estados y transiciones

| Desde | Puede pasar a |
|---|---|
| `open` | `in_progress`, `resolved` |
| `in_progress` | `resolved` |
| `resolved` | `closed`, `in_progress` (reabrir) |
| `closed` | `in_progress` (reabrir) |

- Un ticket debe pasar por `resolved` antes de `closed`.
- Reabrir (`resolved` o `closed` → `in_progress`) conserva la misma `due_date`.
- Pedir el estado que ya tiene el ticket es válido y no cambia nada.
- Cualquier otra transición (por ejemplo `open → closed` o `resolved → open`) devuelve `409` y el
  ticket no cambia.

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
| `PATCH /tickets/{ticket_id}` | `200` ticket actualizado | `404` si no existe · `422` si el valor no está en el enum · `409` si la transición de estado no está permitida |
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
  "updated_at": "2026-06-29T09:30:00Z",
  "due_date": "2026-06-29"
}
```

Campos admitidos en el request: `title` y `description` (obligatorios) y `created_at` (opcional;
si viene, se guarda tal cual). Los espacios al principio y al final se recortan antes de validar y
de guardar.

Errores:

- `422` si `title` está vacío (o solo espacios) o supera 200 caracteres.
- `422` si `description` está vacía (o solo espacios) o supera 5000 caracteres.
- `422` si falta `title` o `description`, si algún campo no es texto o si se envía cualquier campo
  no admitido (por ejemplo `category`).
- `422` si `responsable` supera 100 caracteres.
- `409` si ya existe un ticket con el mismo título y descripción. La comparación ignora
  mayúsculas, tildes, signos de puntuación y espacios repetidos («¿No carga, la app?» y
  «no carga la app» son el mismo texto); se compara contra todos los tickets, también los
  cerrados, y no influyen el responsable ni la fecha. La respuesta indica cuál es
  (`{"detail": {"message": "...", "duplicate_of": 31}}`) y no se llama a la IA. Dos envíos
  idénticos simultáneos guardan solo uno. Los tickets ya existentes se conservan aunque
  estuvieran repetidos.

### `GET /tickets`

Lista tickets en JSON. Query params opcionales: `category`, `priority`, `status`, `responsable` (coincidencia exacta;
un filtro vacío se ignora) y `sort` (`recent` por defecto: más nuevos primero; `priority`: P1 primero,
dentro de cada prioridad los más antiguos primero y «no inferido» al final).

```text
GET /tickets?category=bug&priority=P1&status=open
```

Devuelve `200` con una lista de tickets con la misma forma que la respuesta de `POST /tickets`,
ordenada del más reciente al más antiguo (`id` descendente). Un filtro vacío (`?category=`) se
ignora y un valor sin coincidencias devuelve una lista vacía (no `422`).

### `PATCH /tickets/{ticket_id}`

Solo se pueden cambiar `status` y `priority`. El resto de campos son inmutables tras la creación.

```json
{
  "status": "in_progress",
  "priority": "P2"
}
```

- `status`: `open`, `in_progress`, `resolved`, `closed` (solo transiciones de §2.2)
- `priority`: `P1`, `P2`, `P3` (recalcula `due_date`, ver §2.1)

Los dos campos son opcionales: se puede cambiar solo uno. Un cuerpo vacío o valores `null` no
cambian nada y devuelven `200`. Los campos no modificables que se envíen se ignoran.

Errores:

- `404` si no existe el ticket.
- `422` si el valor no pertenece al enum permitido.
- `409` si el cambio de `status` no es una transición permitida (§2.2).

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
    "category": "bug" | "feature_request" | "question" | "urgent" | "no inferido",
    "priority": "P1" | "P2" | "P3" | "no inferido",
    "tags": list[str],
}
```

Llamada al LLM: SDK de `openai` apuntando a OpenRouter (`base_url="https://openrouter.ai/api/v1"`),
modelo `openai/gpt-oss-120b`, API key desde la variable de entorno `OPENROUTER_API_KEY`.

Requisitos no negociables:

- **Valida la salida.** Si el LLM devuelve `"category": "URGENT"` (mayúsculas) o una categoría
  inventada, aplica el fallback. No propagues basura. `no inferido` sí es un valor válido (el LLM
  lo usa cuando no puede deducir con claridad la categoría o la prioridad).
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

Implementación (`app/ui.py`, `templates/`):

- Avisos al guardar un ticket desde la pantalla:
  - **Rojo, el ticket NO se guarda:** ya existe uno exactamente igual (`409`, indica cuál);
    el servidor está caído, no responde o devuelve un error (aviso global arriba, el texto
    escrito se conserva); o falla la edición de una fila (el desplegable vuelve al valor
    guardado). Sin respuesta en 60 s se da por fallida la petición.
  - **Ámbar, el ticket SÍ se guarda:** la IA no pudo clasificarlo y queda con la
    clasificación provisional (`question`/`P3`/`[]`).

- `GET /` devuelve la página completa; con la cabecera `HX-Request` devuelve solo la tabla.
  Sin parámetros muestra los tickets **abiertos** ordenados por prioridad. Acepta los filtros
  `status` (`all` = todos), `priority`, `category` y `responsable`.
- `POST /ui/tickets` (formulario) y `PATCH /ui/tickets/{id}` (edición en la fila) devuelven HTML.
- Los estados y prioridades se editan en la propia fila; «no inferido» no se puede asignar a mano.
  El cambio de estado sigue las mismas reglas de transición que `PATCH /tickets/{id}`; si no es
  válido la fila no cambia y muestra el motivo (`409`).
- La tabla incluye la fecha límite (`due_date`); se marca como vencida si ya pasó y el ticket sigue
  `open` o `in_progress`.

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
