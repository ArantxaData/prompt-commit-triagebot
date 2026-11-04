# BRIEF.md — El briefing del cliente: TriageBot

## De

Marta Iturri, responsable de Soporte

## Para

Equipo de Ingeniería

## Asunto

Necesitamos una herramienta de triage de incidencias

---

Hola, equipo.

Os escribo porque tengo un problema operativo que está empezando a hacerse insostenible en mi área y quería ver si podéis ayudarme.

Resumiendo: mi equipo de Soporte recibe muchísimos tickets de clientes a lo largo del día. Vienen por mil sitios distintos —email, formulario web, Slack interno— y los acabamos volcando todos a un Excel que ya da pena.

Cuando uno de mis técnicos abre por la mañana ese Excel se encuentra con doscientos tickets sin orden ni concierto, todos con descripciones libres en lenguaje natural:

- "la app no carga"
- "querría poder exportar a PDF"
- "esto urge porque tenemos demo el viernes"

Y se pasa la primera hora del día simplemente ordenando ese lío antes de poder ponerse a resolver nada.

A esa hora de pérdida la llamamos **triage**. Y la queremos automatizar.

## Qué necesitamos

Una aplicación web interna sencilla para:

1. Crear tickets con un título y una descripción.
2. Clasificarlos automáticamente usando IA.
3. Verlos en un tablero filtrable.
4. Poder revisar y cambiar manualmente estado y prioridad si hace falta.

## Clasificación esperada

La IA debe devolver:

- `category`: una de `bug`, `feature_request`, `question`, `urgent`.
- `priority`: una de `P1`, `P2`, `P3`.
- `tags`: lista corta de etiquetas útiles.

## Restricciones técnicas

El equipo de Plataforma nos ha pedido que el stack sea este:

- Python 3.11+
- FastAPI
- SQLite
- HTML + HTMX
- Tailwind por CDN
- Un LLM vía OpenRouter (gpt-oss-120b) para la clasificación
- pytest para tests
- GitHub Actions para CI

## Criterios de aceptación

Sabremos que está terminado cuando:

- Pueda crear un ticket desde API.
- El ticket quede persistido en SQLite.
- El ticket se clasifique automáticamente.
- Si la IA falla, la aplicación no se cae y usa un fallback seguro.
- Pueda ver los tickets en una página web.
- Pueda filtrar por categoría, prioridad y estado.
- Los 5 tests obligatorios estén verdes.
- El pipeline de GitHub Actions esté verde.

## Fuera de alcance

No hace falta:

- Login de usuarios.
- Roles o permisos.
- React, Vue ni frameworks frontend complejos.
- Despliegue productivo con base de datos gestionada.
- Integración real con email, Slack o formularios externos.
