from __future__ import annotations

import re
import unittest

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


class PresetCoverageTests(unittest.TestCase):
    def test_every_preset_has_a_name_and_description_in_both_languages(self) -> None:
        from presets import AUDIO_PRESETS, IMAGE_PRESETS, VIDEO_PRESETS

        for preset in (*IMAGE_PRESETS, *AUDIO_PRESETS, *VIDEO_PRESETS):
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
