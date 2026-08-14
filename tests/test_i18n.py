from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

import i18n
from i18n import (
    DEFAULT_LANGUAGE,
    Language,
    available_languages,
    current_language,
    language_display_name,
    normalized_language,
    set_language,
    t,
)
from locales.en import MESSAGES as ENGLISH
from locales.es import MESSAGES as SPANISH

PLACEHOLDER = re.compile(r"\{(\w+)")


class CatalogueConsistencyTests(unittest.TestCase):
    def test_every_language_defines_the_same_keys(self) -> None:
        self.assertEqual(
            sorted(SPANISH), sorted(ENGLISH), "los catálogos se han desincronizado"
        )

    def test_placeholders_match_across_languages(self) -> None:
        for key, spanish in SPANISH.items():
            with self.subTest(key=key):
                self.assertEqual(
                    sorted(PLACEHOLDER.findall(spanish)),
                    sorted(PLACEHOLDER.findall(ENGLISH[key])),
                    f"los campos de formato difieren en {key}",
                )

    def test_no_empty_translations(self) -> None:
        for catalogue in (SPANISH, ENGLISH):
            for key, value in catalogue.items():
                with self.subTest(key=key):
                    self.assertTrue(value.strip(), f"traducción vacía en {key}")

    def test_english_is_not_a_copy_of_spanish(self) -> None:
        """Detecta claves añadidas al inglés copiando el español sin traducir."""
        shared = {
            key
            for key, value in SPANISH.items()
            if value == ENGLISH[key] and len(value) > 24
        }
        self.assertEqual(shared, set(), "hay textos largos sin traducir al inglés")


class CatalogueUsageTests(unittest.TestCase):
    """Una clave que nadie usa suele significar que el literal sigue
    incrustado en el código y no se traduce."""

    PROJECT = Path(__file__).resolve().parent.parent
    #: Se construyen con f-string desde el preset_id, no como literal.
    DYNAMIC_PREFIXES = ("preset.",)

    def sources(self) -> list[Path]:
        return [
            *self.PROJECT.glob("*.py"),
            *(self.PROJECT / "ui").glob("*.py"),
            *(self.PROJECT / "documents").glob("*.py"),
        ]

    def literal_keys(self) -> set[str]:
        keys: set[str] = set()
        for path in self.sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "t"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    keys.add(node.args[0].value)
        return keys

    def indirect_keys(self) -> set[str]:
        """Claves que llegan a t() sin ser su primer argumento literal.

        Cubre las guardadas en constantes y las elegidas con un condicional
        dentro de la propia llamada.
        """
        pattern = re.compile(r'"((?:ui|summary)\.[a-z0-9_.]+)"')
        found: set[str] = set()
        for path in self.sources():
            found |= set(pattern.findall(path.read_text(encoding="utf-8")))
        return found

    def test_every_key_is_reachable_from_the_code(self) -> None:
        reachable = self.literal_keys() | self.indirect_keys()
        orphans = sorted(
            key
            for key in SPANISH
            if key not in reachable and not key.startswith(self.DYNAMIC_PREFIXES)
        )
        self.assertEqual(orphans, [], "claves de catálogo que nadie usa")

    def test_every_key_used_by_the_code_exists(self) -> None:
        unknown = sorted(key for key in self.literal_keys() if key not in SPANISH)
        self.assertEqual(unknown, [], "t() usa claves que no están en el catálogo")


class HardcodedTextTests(unittest.TestCase):
    """El texto visible vive en los catálogos, nunca dentro de los módulos.

    Comprueba la estructura en vez de adivinar el idioma: cualquier literal
    que llegue a un destino visible sin pasar por `t()` es un fallo, aunque
    esté escrito sin tildes.
    """

    PROJECT = Path(__file__).resolve().parent.parent
    #: Llamadas que muestran texto al usuario.
    SINKS = {"showerror", "showwarning", "showinfo", "set", "title", "insert"}
    #: Argumentos con nombre que acaban en pantalla.
    VISIBLE_KEYWORDS = {"text", "title", "value", "values"}
    #: Constructores que llevan un mensaje destinado al usuario.
    MESSAGE_CONSTRUCTORS = {
        "ErrorDescription",
        "ImageWarning",
        "_warning",
        "animation_warning",
    }
    #: Valores técnicos que no deben traducirse.
    TECHNICAL = {
        "44100",
        "48000",
        "1024",
        "black",
        "libx264",
        "libvpx-vp9",
        "mpeg4",
        "aac",
        "libopus",
        "libmp3lame",
        "yuv420p",
        "Español",
        "English",
        # opciones de Tk, no texto
        "readonly",
        "disabled",
        "normal",
        "word",
        "both",
        "left",
        "right",
        "determinate",
        "indeterminate",
        "write",
        "Segoe UI",
        "Consolas",
        "1.0",
        "end",
        "end-1c",
        "*.*",
        "all",
        "units",
        "pages",
        "break",
        "nw",
    }
    #: Invariantes internas: señalan un uso incorrecto de la API, no llegan al
    #: usuario tal cual (se presentan como «error inesperado», ya traducido).
    INTERNAL_INVARIANTS = {
        "chunk_size must be positive",
        "max_length must allow the fallback basename",
        "APP_VERSION must use major.minor.patch",
        "A skipped output plan cannot be committed.",
        "Automatic WebP mode must be resolved before encoding.",
    }

    def _is_offender(self, value: str) -> bool:
        return (
            len(value) > 3
            and value not in SPANISH  # una clave de catálogo, no texto suelto
            and value not in self.TECHNICAL
            and value not in self.INTERNAL_INVARIANTS
        )

    @staticmethod
    def _strings(nodes) -> list[ast.Constant]:
        return [
            n for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]

    def offenders(self) -> list[str]:
        found: list[str] = []
        sources = [
            *self.PROJECT.glob("*.py"),
            *(self.PROJECT / "ui").glob("*.py"),
            *(self.PROJECT / "documents").glob("*.py"),
        ]
        for path in sources:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                # Mensajes de excepción, incluidos los elegidos con un
                # condicional: raise RuntimeError(x if y else "texto")
                if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                    nested = [n for arg in node.exc.args for n in ast.walk(arg)]
                    for literal in self._strings(nested):
                        if self._is_offender(literal.value):
                            found.append(
                                f"{path.name}:{literal.lineno}: {literal.value[:60]!r}"
                            )
                if not isinstance(node, ast.Call):
                    continue
                literals: list[ast.Constant] = []
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", "")
                )
                # root.after(0, self.status.set, "texto")
                if name == "after" or name in self.MESSAGE_CONSTRUCTORS:
                    literals += self._strings(node.args)
                if name in self.SINKS:
                    literals += [
                        a
                        for a in node.args
                        if isinstance(a, ast.Constant) and isinstance(a.value, str)
                    ]
                for keyword in node.keywords:
                    if keyword.arg not in self.VISIBLE_KEYWORDS:
                        continue
                    values = (
                        keyword.value.elts
                        if isinstance(keyword.value, (ast.Tuple, ast.List))
                        else [keyword.value]
                    )
                    literals += [
                        v
                        for v in values
                        if isinstance(v, ast.Constant) and isinstance(v.value, str)
                    ]
                for literal in literals:
                    if self._is_offender(literal.value):
                        found.append(
                            f"{path.name}:{literal.lineno}: {literal.value[:60]!r}"
                        )
        return found

    def test_visible_text_never_bypasses_the_catalogue(self) -> None:
        self.assertEqual(
            self.offenders(), [], "texto visible incrustado; muévelo a locales/"
        )


class PresetCoverageTests(unittest.TestCase):
    def test_every_preset_has_a_name_and_description_in_both_languages(self) -> None:
        from presets import (
            AUDIO_PRESETS,
            DOCUMENT_PRESETS,
            IMAGE_PRESETS,
            VIDEO_PRESETS,
        )

        for preset in (
            *IMAGE_PRESETS,
            *AUDIO_PRESETS,
            *VIDEO_PRESETS,
            *DOCUMENT_PRESETS,
        ):
            for suffix in ("name", "description"):
                key = f"preset.{preset.preset_id}.{suffix}"
                with self.subTest(key=key):
                    self.assertIn(key, SPANISH)
                    self.assertIn(key, ENGLISH)

    def test_preset_labels_follow_the_active_language(self) -> None:
        from presets import preset_by_id

        self.addCleanup(set_language, DEFAULT_LANGUAGE)
        preset = preset_by_id("thumbnail")
        set_language(Language.SPANISH)
        self.assertEqual(preset.display_name, "Miniatura")
        set_language(Language.ENGLISH)
        self.assertEqual(preset.display_name, "Thumbnail")


class LanguageSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(set_language, DEFAULT_LANGUAGE)

    def test_default_language_is_spanish(self) -> None:
        self.assertIs(DEFAULT_LANGUAGE, Language.SPANISH)

    def test_set_language_switches_the_active_catalogue(self) -> None:
        set_language(Language.ENGLISH)
        self.assertIs(current_language(), Language.ENGLISH)
        self.assertEqual(t("ui.button.cancel"), "Cancel")
        set_language(Language.SPANISH)
        self.assertEqual(t("ui.button.cancel"), "Cancelar")

    def test_unknown_language_falls_back_to_default(self) -> None:
        for value in ("fr", "", None, "english"):
            with self.subTest(value=value):
                self.assertIs(normalized_language(value), DEFAULT_LANGUAGE)

    def test_available_languages_and_names(self) -> None:
        self.assertEqual(
            set(available_languages()), {Language.SPANISH, Language.ENGLISH}
        )
        self.assertEqual(language_display_name(Language.SPANISH), "Español")
        self.assertEqual(language_display_name(Language.ENGLISH), "English")

    def test_names_are_shown_in_their_own_language(self) -> None:
        set_language(Language.ENGLISH)
        self.assertEqual(language_display_name(Language.SPANISH), "Español")


class TranslationLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(set_language, DEFAULT_LANGUAGE)

    def test_missing_key_returns_the_key_itself(self) -> None:
        with self.assertLogs("i18n", level="WARNING"):
            self.assertEqual(t("does.not.exist"), "does.not.exist")

    def test_missing_translation_falls_back_to_spanish(self) -> None:
        set_language(Language.ENGLISH)
        i18n._CATALOGUES[Language.ENGLISH] = {}
        self.addCleanup(i18n._CATALOGUES.__setitem__, Language.ENGLISH, dict(ENGLISH))
        with self.assertLogs("i18n", level="WARNING"):
            self.assertEqual(t("ui.button.cancel"), "Cancelar")

    def test_named_fields_are_interpolated(self) -> None:
        set_language(Language.ENGLISH)
        self.assertEqual(
            t("ui.status.converting", index=2, total=5, name="a.png"),
            "Converting 2/5: a.png",
        )

    def test_unexpected_field_does_not_raise(self) -> None:
        self.assertEqual(t("ui.button.cancel", unused=1), "Cancelar")

    def test_template_without_fields_is_returned_verbatim(self) -> None:
        self.assertIn("{name}", t("ui.status.file_selected"))

    def test_incomplete_fields_return_template_instead_of_raising(self) -> None:
        with self.assertLogs("i18n", level="ERROR"):
            self.assertIn("{total}", t("ui.status.converting", index=1))


if __name__ == "__main__":
    unittest.main()
