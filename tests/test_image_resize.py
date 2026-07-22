from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from image_resize import ResizeConfig, ResizeMode, calculate_resize_dimensions
from png_a_webp import PanelImagen


class DimensionCalculationTests(unittest.TestCase):
    def test_landscape_max_width(self) -> None:
        config = ResizeConfig(ResizeMode.MAX_WIDTH, width=1000)
        self.assertEqual(calculate_resize_dimensions(2000, 1000, config), (1000, 500))

    def test_portrait_max_height(self) -> None:
        config = ResizeConfig(ResizeMode.MAX_HEIGHT, height=900)
        self.assertEqual(calculate_resize_dimensions(1000, 2000, config), (450, 900))

    def test_square_fit_box(self) -> None:
        config = ResizeConfig(ResizeMode.FIT, width=600, height=400)
        self.assertEqual(calculate_resize_dimensions(1000, 1000, config), (400, 400))

    def test_fit_preserves_landscape_aspect_ratio(self) -> None:
        config = ResizeConfig(ResizeMode.FIT, width=800, height=800)
        self.assertEqual(calculate_resize_dimensions(1600, 900, config), (800, 450))

    def test_percentage_scaling(self) -> None:
        config = ResizeConfig(ResizeMode.PERCENT, percentage=25)
        self.assertEqual(calculate_resize_dimensions(800, 600, config), (200, 150))

    def test_never_upscale_small_image(self) -> None:
        config = ResizeConfig(ResizeMode.MAX_WIDTH, width=1000, never_upscale=True)
        self.assertEqual(calculate_resize_dimensions(32, 16, config), (32, 16))

    def test_explicit_upscaling(self) -> None:
        config = ResizeConfig(ResizeMode.PERCENT, percentage=200, never_upscale=False)
        self.assertEqual(calculate_resize_dimensions(20, 10, config), (40, 20))

    def test_very_small_result_never_reaches_zero(self) -> None:
        config = ResizeConfig(ResizeMode.PERCENT, percentage=1)
        self.assertEqual(calculate_resize_dimensions(2, 2, config), (1, 1))

    def test_invalid_values(self) -> None:
        invalid = (
            ResizeConfig(ResizeMode.MAX_WIDTH, width=0),
            ResizeConfig(ResizeMode.MAX_HEIGHT, height=-1),
            ResizeConfig(ResizeMode.FIT, width=10, height=None),
            ResizeConfig(ResizeMode.PERCENT, percentage=101, never_upscale=True),
        )
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ValueError):
                calculate_resize_dimensions(100, 100, config)


class ResizePipelineTests(unittest.TestCase):
    def test_exif_orientation_is_applied_before_dimensions(self) -> None:
        image = Image.new("RGB", (40, 20), "red")
        exif = Image.Exif()
        exif[274] = 6
        stream = BytesIO()
        image.save(stream, format="JPEG", exif=exif)
        stream.seek(0)
        with Image.open(stream) as loaded:
            resized, target = PanelImagen.resize_frame(loaded, ResizeConfig())
        self.assertEqual(target, (20, 40))
        self.assertEqual(resized.size, (20, 40))

    def test_transparency_survives_lanczos_resize(self) -> None:
        image = Image.new("RGBA", (20, 20), (1, 2, 3, 80))
        config = ResizeConfig(ResizeMode.MAX_WIDTH, width=10)
        resized, _target = PanelImagen.resize_frame(image, config)
        self.assertEqual(resized.size, (10, 10))
        self.assertLess(resized.getchannel("A").getextrema()[0], 255)

    def test_all_animated_frames_share_resized_dimensions(self) -> None:
        first = Image.new("RGBA", (20, 10), "red")
        second = Image.new("RGBA", (20, 10), "blue")
        source = BytesIO()
        first.save(
            source, format="GIF", save_all=True, append_images=[second], duration=50
        )
        source.seek(0)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            output = Path(temporary) / "animation.webp"
            with Image.open(source) as animated:
                panel = PanelImagen.__new__(PanelImagen)
                panel.guardar_imagen(
                    animated,
                    output,
                    "WEBP",
                    80,
                    "animation.gif",
                    "lossless",
                    ResizeConfig(ResizeMode.MAX_WIDTH, width=10),
                )
            with Image.open(output) as converted:
                self.assertEqual(converted.n_frames, 2)
                for frame_index in range(converted.n_frames):
                    converted.seek(frame_index)
                    self.assertEqual(converted.size, (10, 5))


if __name__ == "__main__":
    unittest.main()
