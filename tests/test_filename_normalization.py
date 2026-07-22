from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from output_policy import OutputAction, OutputPolicy, cleanup_temporary, plan_output

from filename_normalization import (
    MAX_BASENAME_LENGTH,
    collision_keys,
    normalize_basename,
    output_filename,
)


class FilenameNormalizationTests(unittest.TestCase):
    def test_normalization_table(self) -> None:
        cases = {
            "My File.png": "my_file",
            "My-File.png": "my_file",
            "Árbol Ñandú Ç.png": "arbol_nandu_c",
            "MiXeD Case.JPG": "mixed_case",
            "one---__...two.png": "one_two",
            "123 hero.png": "asset_123_hero",
            "hero😀.png": "hero",
            "😀!!!.png": "asset",
            "CON.txt": "asset_con",
            "lPt9.wav": "asset_lpt9",
            ".hidden": "hidden",
            "archive.final.v2.png": "archive_final_v2",
            "trailing...   ": "trailing",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(normalize_basename(source), expected)

    def test_long_name_is_limited(self) -> None:
        result = normalize_basename("a" * 200 + ".png")
        self.assertEqual(len(result), MAX_BASENAME_LENGTH)
        self.assertEqual(result, "a" * MAX_BASENAME_LENGTH)

    def test_different_extensions_preserve_selected_destination_extension(self) -> None:
        for source in (Path("My File.png"), Path("My File.jpg"), Path("My File.tiff")):
            with self.subTest(source=source):
                self.assertEqual(output_filename(source, ".webp", True), "my_file.webp")

    def test_disabled_mode_preserves_existing_basename(self) -> None:
        self.assertEqual(
            output_filename(Path("My Original.File.png"), ".webp", False),
            "My Original.File.webp",
        )

    def test_collisions_are_case_insensitive(self) -> None:
        paths = [
            Path("out/my_file.webp"),
            Path("out/MY_FILE.webp"),
            Path("out/other.webp"),
        ]
        collisions = collision_keys(paths)
        self.assertEqual(len(collisions), 1)

    def test_same_basename_in_different_recursive_folders_does_not_collide(
        self,
    ) -> None:
        paths = [Path("out/a/item.webp"), Path("out/b/item.webp")]
        self.assertEqual(collision_keys(paths), set())

    def test_existing_file_policies_apply_to_normalized_collision(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            first = root / "My-File.png"
            second = root / "My File.jpg"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            target = root / output_filename(first, ".webp", True)
            target.write_bytes(b"existing")

            skip = plan_output(second, target, OutputPolicy.SKIP)
            overwrite = plan_output(second, target, OutputPolicy.OVERWRITE)
            unique = plan_output(second, target, OutputPolicy.UNIQUE)
            try:
                self.assertEqual(skip.action, OutputAction.SKIP_EXISTS)
                self.assertEqual(overwrite.action, OutputAction.OVERWRITE)
                self.assertEqual(unique.action, OutputAction.RENAME)
                self.assertEqual(unique.target.name, "my_file_2.webp")
            finally:
                cleanup_temporary(overwrite)
                cleanup_temporary(unique)

    def test_invalid_maximum_length_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_basename("name.png", 4)


if __name__ == "__main__":
    unittest.main()
