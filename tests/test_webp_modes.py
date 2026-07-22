from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from png_a_webp import PanelImagen
from webp_encoding import (
    WebPMode,
    choose_automatic_webp_mode,
    resolve_webp_mode,
    webp_controls_visible,
    webp_save_options,
)


def detailed_rgba(size: tuple[int, int], alpha: int = 255) -> Image.Image:
    image = Image.new("RGBA", size)
    pixels = image.load()
    for y in range(size[1]):
        for x in range(size[0]):
            pixels[x, y] = (
                (x * 17 + y) % 256,
                (x + y * 19) % 256,
                (x * y) % 256,
                alpha,
            )
    return image


class WebPDecisionTests(unittest.TestCase):
    def test_explicit_modes_are_preserved(self) -> None:
        image = Image.new("RGBA", (8, 8), (1, 2, 3, 100))
        self.assertEqual(
            resolve_webp_mode(WebPMode.LOSSY, image, "x.png"), WebPMode.LOSSY
        )
        self.assertEqual(
            resolve_webp_mode(WebPMode.LOSSLESS, image, "x.png"), WebPMode.LOSSLESS
        )

    def test_jpeg_is_automatic_lossy(self) -> None:
        image = Image.new("RGB", (32, 32), "red")
        image.format = "JPEG"
        self.assertEqual(choose_automatic_webp_mode(image, "photo.jpg"), WebPMode.LOSSY)

    def test_large_opaque_detailed_image_is_lossy(self) -> None:
        image = detailed_rgba((1000, 1000)).convert("RGB")
        self.assertEqual(choose_automatic_webp_mode(image, "large.png"), WebPMode.LOSSY)

    def test_transparent_low_color_image_is_lossless(self) -> None:
        image = Image.new("RGBA", (128, 128), (20, 40, 60, 80))
        self.assertEqual(
            choose_automatic_webp_mode(image, "icon.png"), WebPMode.LOSSLESS
        )

    def test_transparent_high_detail_image_is_lossy(self) -> None:
        image = detailed_rgba((256, 256), alpha=120)
        self.assertEqual(
            choose_automatic_webp_mode(image, "illustration.png"), WebPMode.LOSSY
        )

    def test_animated_images_follow_lossless_policy(self) -> None:
        first = Image.new("RGBA", (4, 4), "red")
        second = Image.new("RGBA", (4, 4), "blue")
        stream = BytesIO()
        first.save(stream, format="GIF", save_all=True, append_images=[second])
        stream.seek(0)
        animated = Image.open(stream)
        self.assertEqual(
            choose_automatic_webp_mode(animated, "animated.gif"), WebPMode.LOSSLESS
        )


class WebPEncodingTests(unittest.TestCase):
    def test_lossy_uses_quality_and_preserves_alpha(self) -> None:
        image = detailed_rgba((32, 32), alpha=77)
        converted, options, mode = PanelImagen.preparar_estatica(
            image, "WEBP", 73, "image.png", WebPMode.LOSSY
        )
        self.assertEqual(mode, WebPMode.LOSSY)
        self.assertEqual(options["quality"], 73)
        stream = BytesIO()
        converted.save(stream, format="WEBP", **options)
        stream.seek(0)
        self.assertEqual(Image.open(stream).convert("RGBA").getpixel((0, 0))[3], 77)

    def test_lossless_is_true_lossless_and_ignores_quality(self) -> None:
        image = Image.new("RGBA", (16, 16), (12, 34, 56, 78))
        converted, options, mode = PanelImagen.preparar_estatica(
            image, "WEBP", 5, "icon.png", WebPMode.LOSSLESS
        )
        self.assertEqual(mode, WebPMode.LOSSLESS)
        self.assertTrue(options["lossless"])
        self.assertNotIn("quality", options)
        stream = BytesIO()
        converted.save(stream, format="WEBP", **options)
        stream.seek(0)
        self.assertEqual(
            Image.open(stream).convert("RGBA").getpixel((0, 0)), (12, 34, 56, 78)
        )

    def test_quality_is_clamped(self) -> None:
        self.assertEqual(webp_save_options(WebPMode.LOSSY, 500)["quality"], 100)
        self.assertEqual(webp_save_options(WebPMode.LOSSY, -1)["quality"], 1)

    def test_webp_ui_visibility_contract(self) -> None:
        self.assertTrue(webp_controls_visible("WebP"))
        self.assertFalse(webp_controls_visible("PNG"))

    def test_batch_can_select_different_automatic_modes(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            jpeg = root / "photo.jpg"
            palette = root / "icon.png"
            Image.new("RGB", (20, 20), "red").save(jpeg)
            Image.new("P", (20, 20), 1).save(palette)
            with Image.open(jpeg) as photo, Image.open(palette) as icon:
                self.assertEqual(
                    choose_automatic_webp_mode(photo, jpeg), WebPMode.LOSSY
                )
                self.assertEqual(
                    choose_automatic_webp_mode(icon, palette), WebPMode.LOSSLESS
                )


if __name__ == "__main__":
    unittest.main()
