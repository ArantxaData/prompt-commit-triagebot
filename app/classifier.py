FALLBACK_CLASSIFICATION = {"category": "question", "priority": "P3", "tags": []}


def classify_ticket(title: str, description: str) -> dict:
    """Classify a support ticket.

    TODO durante el bootcamp:
    - Llamar al LLM (openai/gpt-oss-120b) vía OpenRouter con el SDK de openai,
      usando OPENROUTER_API_KEY.
    - Pedir JSON estricto.
    - Parsear y validar category, priority y tags.
    - Nunca propagar excepciones del SDK.
    - Devolver FALLBACK_CLASSIFICATION ante cualquier problema.
    """
    raise NotImplementedError("Implement this function during Lab 2")
