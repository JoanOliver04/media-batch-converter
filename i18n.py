"""Selección de idioma en tiempo de ejecución y acceso al catálogo de mensajes."""

from __future__ import annotations

import logging
from enum import StrEnum

from locales.en import MESSAGES as ENGLISH_MESSAGES
from locales.es import MESSAGES as SPANISH_MESSAGES

logging.getLogger(__name__).addHandler(logging.NullHandler())


class Language(StrEnum):
    SPANISH = "es"
    ENGLISH = "en"


DEFAULT_LANGUAGE = Language.SPANISH

#: El nombre de cada idioma se muestra siempre en ese idioma, para que sea
#: reconocible aunque la interfaz esté en el otro.
LANGUAGE_NAMES = {
    Language.SPANISH: "Español",
    Language.ENGLISH: "English",
}

_CATALOGUES: dict[Language, dict[str, str]] = {
    Language.SPANISH: SPANISH_MESSAGES,
    Language.ENGLISH: ENGLISH_MESSAGES,
}

_current_language = DEFAULT_LANGUAGE


def available_languages() -> tuple[Language, ...]:
    return tuple(_CATALOGUES)


def language_display_name(language: Language | str) -> str:
    return LANGUAGE_NAMES.get(
        normalized_language(language), LANGUAGE_NAMES[DEFAULT_LANGUAGE]
    )


def normalized_language(value: Language | str | None) -> Language:
    """Devuelve un idioma admitido; cualquier valor desconocido cae al predeterminado."""
    try:
        return Language(str(value))
    except ValueError:
        return DEFAULT_LANGUAGE


def current_language() -> Language:
    return _current_language


def set_language(value: Language | str | None) -> Language:
    global _current_language
    _current_language = normalized_language(value)
    return _current_language


def t(key: str, **fields: object) -> str:
    """Traduce `key` al idioma activo.

    Si falta en el idioma activo se usa el español, que es el catálogo de
    referencia; si tampoco está, se devuelve la propia clave para que el hueco
    sea visible en vez de romper la interfaz.
    """
    template = _CATALOGUES[_current_language].get(key)
    if template is None:
        template = SPANISH_MESSAGES.get(key)
        if template is None:
            logging.getLogger(__name__).warning(
                "missing_translation key=%s language=%s", key, _current_language.value
            )
            return key
        logging.getLogger(__name__).warning(
            "untranslated key=%s language=%s", key, _current_language.value
        )
    if not fields:
        return template
    try:
        return template.format(**fields)
    except (KeyError, IndexError) as error:
        logging.getLogger(__name__).error(
            "translation_format_failed key=%s error=%s", key, error
        )
        return template
