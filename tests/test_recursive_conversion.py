from __future__ import annotations

import inspect
import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image

from batch_processing import discover_files, safe_output_directory
from png_a_webp import PanelImagen


class ImmediateRoot:
    def after(self, _delay: int, callback, *args):
        callback(*args)


class DummyState:
    def set(self, _value: str) -> None:
        pass


class StepCancel:
    def __init__(self, allowed_checks: int) -> None:
        self.allowed_checks = allowed_checks
        self.checks = 0

    def is_set(self) -> bool:
        self.checks += 1
        return self.checks > self.allowed_checks


class InterfaceContractTests(unittest.TestCase):
    def test_prepare_batch_accepts_captured_recursive_flag(self) -> None:
        parameters = inspect.signature(PanelImagen.preparar_lote).parameters
        self.assertIn("recursivo", parameters)


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def touch(self, relative: str, content: bytes = b"data") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_non_recursive_discovery(self) -> None:
        root_file = self.touch("root.png")
        self.touch("nested/child.png")
        result = discover_files(self.root, {".png"}, recursive=False)
        self.assertEqual(result.files, [root_file])

    def test_recursive_discovery_is_sorted(self) -> None:
        self.touch("z/image.png")
        self.touch("a/image.png")
        result = discover_files(self.root, {".png"})
        relative = [path.relative_to(self.root).as_posix() for path in result.files]
        self.assertEqual(relative, ["a/image.png", "z/image.png"])

    def test_output_directories_are_ignored(self) -> None:
        expected = self.touch("source.png")
        self.touch("converted_webp/old.png")
        self.touch("convertidos_png/nested/old.png")
        result = discover_files(self.root, {".png"})
        self.assertEqual(result.files, [expected])

    def test_empty_and_unsupported_directories(self) -> None:
        self.assertEqual(discover_files(self.root, {".png"}).files, [])
        self.touch("notes.txt")
        self.assertEqual(discover_files(self.root, {".png"}).files, [])

    def test_unicode_spaces_and_duplicate_names(self) -> None:
        first = self.touch("grupo á/imagen común.png")
        second = self.touch("otro grupo/imagen común.png")
        result = discover_files(self.root, {".png"})
        self.assertEqual(set(result.files), {first, second})

    def test_cancellation_during_discovery(self) -> None:
        for index in range(20):
            self.touch(f"folder_{index}/image.png")
        result = discover_files(self.root, {".png"}, cancel_event=StepCancel(5))
        self.assertTrue(result.cancelled)
        self.assertLess(len(result.files), 20)

    def test_directory_symlinks_are_not_followed(self) -> None:
        target = self.root / "target"
        target.mkdir()
        self.touch("target/image.png")
        link = self.root / "linked"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Directory symlinks are unavailable on this platform")
        result = discover_files(self.root, {".png"})
        relative = [path.relative_to(self.root).as_posix() for path in result.files]
        self.assertEqual(relative, ["target/image.png"])

    def test_safe_output_preserves_relative_parent(self) -> None:
        source = self.touch("nested/deep/image.png")
        output = self.root / "convertidos_webp"
        destination = safe_output_directory(output, self.root, source)
        self.assertEqual(destination, output / "nested" / "deep")


class ImageBatchTests(unittest.TestCase):
    def test_nested_structure_and_invalid_file_do_not_stop_batch(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            valid = root / "grupo á" / "same.png"
            invalid = root / "otro grupo" / "same.png"
            valid.parent.mkdir(parents=True)
            invalid.parent.mkdir(parents=True)
            Image.new("RGBA", (4, 4), (255, 0, 0, 100)).save(valid)
            invalid.write_text("not an image", encoding="utf-8")

            panel = PanelImagen.__new__(PanelImagen)
            panel.raiz = ImmediateRoot()
            panel.estado = DummyState()
            panel.cancel_event = threading.Event()
            panel.notificar_avance = lambda *_args: None
            completion: dict[str, object] = {}
            panel.finalizar_resultados = lambda destination, results, errors, *args: (
                completion.update(
                    destination=destination, results=results, discovery_errors=errors
                )
            )

            panel.convertir_lote(root, [valid, invalid], "WebP", 85)

            self.assertTrue(
                root.joinpath("convertidos_webp", "grupo á", "same.webp").is_file()
            )
            self.assertEqual(
                sum(
                    result.status.value == "converted"
                    for result in completion["results"]
                ),
                1,
            )
            self.assertEqual(
                sum(
                    result.status.value == "failed" for result in completion["results"]
                ),
                1,
            )

    def test_normalized_batch_collision_uses_unique_policy_and_is_reported(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            first = root / "My-File.png"
            second = root / "My File.jpg"
            Image.new("RGB", (4, 4), "red").save(first)
            Image.new("RGB", (4, 4), "blue").save(second)

            panel = PanelImagen.__new__(PanelImagen)
            panel.raiz = ImmediateRoot()
            panel.estado = DummyState()
            panel.cancel_event = threading.Event()
            panel.notificar_avance = lambda *_args: None
            completion: dict[str, object] = {}
            panel.finalizar_resultados = lambda destination, results, errors, *args: (
                completion.update(destination=destination, results=results)
            )

            panel.convertir_lote(
                root,
                [first, second],
                "WebP",
                85,
                opciones={
                    "normalize_filenames": True,
                    "output_policy": "unique",
                },
            )

            output = root / "convertidos_webp"
            self.assertTrue((output / "my_file.webp").is_file())
            self.assertTrue((output / "my_file_2.webp").is_file())
            self.assertTrue(
                all(result.name_collision for result in completion["results"])
            )
            self.assertEqual(
                [result.output_action for result in completion["results"]],
                ["converted", "renamed"],
            )


if __name__ == "__main__":
    unittest.main()
