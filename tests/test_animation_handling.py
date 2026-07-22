from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image

from animation_handling import (
    AnimationMode,
    animation_supported,
    frame_directory,
    webp_frame_durations,
)
from image_resize import ResizeConfig, ResizeMode
from png_a_webp import PanelImagen


class ImmediateRoot:
    def after(self, _delay, callback, *args):
        callback(*args)


class DummyState:
    def set(self, _value):
        pass


class CountingCancel:
    def __init__(self, trigger: int) -> None:
        self.calls = 0
        self.trigger = trigger

    def is_set(self) -> bool:
        self.calls += 1
        return self.calls >= self.trigger


def make_animation(path: Path) -> None:
    first = Image.new("RGBA", (6, 4), (255, 0, 0, 0))
    first.putpixel((0, 0), (255, 0, 0, 255))
    second = Image.new("RGBA", (6, 4), (0, 0, 255, 128))
    first.save(
        path,
        save_all=True,
        append_images=[second],
        duration=[70, 130],
        loop=3,
        disposal=[2, 2],
        transparency=0,
    )


def make_panel(cancel_event=None):
    panel = PanelImagen.__new__(PanelImagen)
    panel.raiz = ImmediateRoot()
    panel.estado = DummyState()
    panel.cancel_event = cancel_event or threading.Event()
    panel.notificar_avance = lambda *_args: None
    panel.modos_seleccionados = {}
    completion: dict[str, object] = {}
    panel.finalizar_resultados = lambda destination, results, errors, *args: (
        completion.update(
            destination=destination,
            results=results,
            errors=errors,
            cancelled=args[0] if args else False,
        )
    )
    return panel, completion


class AnimationHandlingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temporary.name)
        self.source = self.root / "animated.gif"
        make_animation(self.source)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_capability_uses_registered_pillow_writers(self) -> None:
        self.assertTrue(animation_supported("GIF"))
        self.assertFalse(animation_supported("JPEG"))
        self.assertIsInstance(animation_supported("WEBP"), bool)

    def test_frame_directory_never_reuses_existing_folder(self) -> None:
        existing = self.root / "asset_frames"
        existing.mkdir()
        self.assertEqual(frame_directory(existing).name, "asset_frames_2")

    def test_preserve_animation_metadata_transparency_and_order(self) -> None:
        panel, completion = make_panel()
        panel.convertir_lote(
            self.root,
            [self.source],
            "GIF",
            85,
            opciones={"animation_mode": AnimationMode.PRESERVE.value},
        )
        result = completion["results"][0]
        self.assertEqual(result.animation_mode, "preserve")
        self.assertEqual(result.frame_count, 2)
        self.assertEqual(result.frame_durations_ms, (70, 130))
        output = self.root / "convertidos_gif" / "animated.gif"
        with Image.open(output) as image:
            self.assertEqual(image.n_frames, 2)
            self.assertEqual(image.info.get("loop"), 3)
            durations = []
            alpha_minima = []
            disposals = []
            for index in range(image.n_frames):
                image.seek(index)
                durations.append(image.info.get("duration"))
                alpha_minima.append(
                    image.convert("RGBA").getchannel("A").getextrema()[0]
                )
                disposals.append(getattr(image, "disposal_method", None))
            self.assertEqual(durations, [70, 130])
            self.assertTrue(any(value < 255 for value in alpha_minima))
            self.assertEqual(disposals, [2, 2])

    def test_extract_all_frames_resizes_and_records_durations(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        source = nested / "animated.gif"
        make_animation(source)
        panel, completion = make_panel()
        panel.convertir_lote(
            self.root,
            [source],
            "PNG",
            85,
            opciones={
                "animation_mode": AnimationMode.EXTRACT_FRAMES.value,
                "resize_config": ResizeConfig(ResizeMode.MAX_WIDTH, width=3),
            },
        )
        result = completion["results"][0]
        expected = self.root / "convertidos_png" / "nested" / "animated_frames"
        self.assertEqual(result.output_path, expected)
        self.assertEqual([frame.duration_ms for frame in result.frames], [70, 130])
        self.assertEqual(
            [frame.output_path.name for frame in result.frames],
            ["frame_0001.png", "frame_0002.png"],
        )
        for frame in result.frames:
            with Image.open(frame.output_path) as image:
                self.assertEqual(image.size, (3, 2))

    def test_existing_frame_folder_is_preserved_during_extraction(self) -> None:
        existing = self.root / "convertidos_png" / "animated_frames"
        existing.mkdir(parents=True)
        marker = existing / "unrelated.txt"
        marker.write_text("keep", encoding="utf-8")
        panel, completion = make_panel()
        panel.convertir_lote(
            self.root,
            [self.source],
            "PNG",
            85,
            opciones={"animation_mode": AnimationMode.EXTRACT_FRAMES.value},
        )
        result = completion["results"][0]
        self.assertEqual(result.output_path.name, "animated_frames_2")
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_animated_webp_input_is_detected_when_supported(self) -> None:
        if not animation_supported("WEBP"):
            self.skipTest("Animated WebP is unavailable in this Pillow build")
        source = self.root / "animated.webp"
        first = Image.new("RGBA", (3, 3), (255, 0, 0, 255))
        second = Image.new("RGBA", (3, 3), (0, 0, 255, 128))
        first.save(
            source,
            save_all=True,
            append_images=[second],
            duration=[50, 80],
            loop=1,
        )
        self.assertEqual(webp_frame_durations(source), (50, 80))
        panel, completion = make_panel()
        panel.convertir_lote(
            self.root,
            [source],
            "GIF",
            85,
            opciones={"animation_mode": AnimationMode.PRESERVE.value},
        )
        result = completion["results"][0]
        self.assertEqual(result.frame_count, 2)
        self.assertEqual(result.frame_durations_ms, (50, 80))
        with Image.open(result.output_path) as output:
            self.assertEqual(output.n_frames, 2)

    def test_first_frame_only_is_explicit_and_static(self) -> None:
        panel, completion = make_panel()
        panel.convertir_lote(
            self.root,
            [self.source],
            "PNG",
            85,
            opciones={"animation_mode": AnimationMode.FIRST_FRAME.value},
        )
        result = completion["results"][0]
        self.assertEqual(result.animation_mode, "first_frame")
        self.assertIn(
            "ANIMATION_INTENTIONALLY_DISCARDED",
            {warning.code.value for warning in result.warnings},
        )
        with Image.open(result.output_path) as image:
            self.assertFalse(getattr(image, "is_animated", False))

    def test_preserve_to_unsupported_destination_blocks_only_that_file(self) -> None:
        static = self.root / "static.png"
        Image.new("RGB", (2, 2), "green").save(static)
        panel, completion = make_panel()
        panel.convertir_lote(
            self.root,
            [self.source, static],
            "JPEG",
            85,
            opciones={"animation_mode": AnimationMode.PRESERVE.value},
        )
        statuses = [result.status.value for result in completion["results"]]
        self.assertEqual(statuses, ["failed", "converted"])
        self.assertIn(
            "ANIMATED_DESTINATION_UNSUPPORTED",
            {warning.code.value for warning in completion["results"][0].warnings},
        )

    def test_static_gif_ignores_animation_policy(self) -> None:
        static = self.root / "static.gif"
        Image.new("P", (2, 2)).save(static)
        panel, completion = make_panel()
        panel.convertir_lote(
            self.root,
            [static],
            "PNG",
            85,
            opciones={"animation_mode": AnimationMode.EXTRACT_FRAMES.value},
        )
        result = completion["results"][0]
        self.assertIsNone(result.animation_mode)
        self.assertTrue(result.output_path.is_file())

    def test_cancellation_during_extraction_removes_partial_folder(self) -> None:
        panel, completion = make_panel(CountingCancel(trigger=3))
        panel.convertir_lote(
            self.root,
            [self.source],
            "PNG",
            85,
            opciones={"animation_mode": AnimationMode.EXTRACT_FRAMES.value},
        )
        self.assertTrue(completion["cancelled"])
        self.assertEqual(completion["results"], [])
        output_root = self.root / "convertidos_png"
        self.assertEqual(list(output_root.rglob("*_frames")), [])


if __name__ == "__main__":
    unittest.main()
