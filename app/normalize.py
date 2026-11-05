"""Normalización de texto y huella (fingerprint) para detectar tickets exactamente repetidos."""

import hashlib
import re
import unicodedata

_SPACES = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Deja solo lo que distingue una consulta de otra: letras y números en minúsculas.

    Ignora mayúsculas, tildes, signos de puntuación y espacios repetidos, de modo que
    "¿No carga, la app?" y "no carga la app" dan el mismo resultado.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    folded = without_accents.casefold()
    alnum = "".join(ch if ch.isalnum() else " " for ch in folded)
    normalized = _SPACES.sub(" ", alnum).strip()
    # Un texto sin letras ni números (p. ej. "???") se compara tal cual, para no igualar
    # tickets distintos que se quedarían ambos en blanco.
    return normalized or _SPACES.sub(" ", folded).strip()


def fingerprint(title: str, description: str) -> str:
    """Huella estable del par título + descripción normalizados."""
    # \x1f separa los campos: ("ab", "c") y ("a", "bc") no pueden dar la misma huella.
    joined = f"{normalize_text(title)}\x1f{normalize_text(description)}"
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
