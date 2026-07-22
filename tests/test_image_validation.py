from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from image_validation import (
    ImageWarningCode,
    WarningSeverity,
    output_size_warnings,
    validate_image,
    validate_properties,
)


class ImageValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def codes(self, found) -> set[ImageWarningCode]:
        return {warning.code for warning in found}

    def test_fully_opaque_rgba_is_not_meaningfully_transparent(self) -> None:
        source = self.root / "opaque.png"
        Image.new("RGBA", (2, 2), (1, 2, 3, 255)).save(source)
        codes = self.codes(validate_image(source, "JPEG"))
        self.assertIn(ImageWarningCode.ALPHA_CHANNEL_PRESENT, codes)
        self.assertNotIn(ImageWarningCode.MEANINGFUL_TRANSPARENCY, codes)
        self.assertNotIn(ImageWarningCode.ALPHA_WILL_BE_FLATTENED, codes)

    def test_real_transparency_to_jpeg_warns_about_flattening(self) -> None:
        source = self.root / "transparent.png"
        Image.new("RGBA", (2, 2), (1, 2, 3, 100)).save(source)
        codes = self.codes(validate_image(source, "JPEG"))
        self.assertIn(ImageWarningCode.MEANINGFUL_TRANSPARENCY, codes)
        self.assertIn(ImageWarningCode.ALPHA_WILL_BE_FLATTENED, codes)

    def test_mismatched_extension(self) -> None:
        source = self.root / "actually-jpeg.png"
        Image.new("RGB", (2, 2)).save(source, format="JPEG")
        self.assertIn(
            ImageWarningCode.EXTENSION_FORMAT_MISMATCH,
            self.codes(validate_image(source, "WEBP")),
        )

    def test_corrupted_image_is_blocking(self) -> None:
        source = self.root / "broken.png"
        source.write_bytes(b"not an image")
        found = validate_image(source, "WEBP")
        self.assertIn(ImageWarningCode.CORRUPTED_IMAGE, self.codes(found))
        self.assertTrue(any(warning.blocking for warning in found))

    def test_cmyk_jpeg_and_metadata(self) -> None:
        source = self.root / "cmyk.jpg"
        exif = Image.Exif()
        exif[270] = "metadata"
        Image.new("CMYK", (2, 2)).save(source, exif=exif)
        codes = self.codes(validate_image(source, "WEBP"))
        self.assertIn(ImageWarningCode.CMYK_CONVERTED_TO_RGB, codes)
        self.assertIn(ImageWarningCode.METADATA_DROPPED, codes)

    def test_large_dimensions_pixel_pressure_unusual_mode_and_invalid_dimensions(
        self,
    ) -> None:
        found = validate_properties(
            Path("large.png"),
            "PNG",
            ".png",
            "I;16",
            20_000,
            20_000,
            False,
            False,
            False,
            "WEBP",
        )
        codes = self.codes(found)
        self.assertIn(ImageWarningCode.SOURCE_DIMENSIONS_EXTREME, codes)
        self.assertIn(ImageWarningCode.SOURCE_PIXEL_COUNT_EXCESSIVE, codes)
        self.assertIn(ImageWarningCode.UNUSUAL_COLOR_MODE, codes)
        invalid = validate_properties(
            Path("zero.png"), "PNG", ".png", "RGB", 0, 5, False, False, False, "WEBP"
        )
        self.assertEqual(invalid[0].severity, WarningSeverity.BLOCKING_ERROR)

    def test_animation_to_static_format(self) -> None:
        found = validate_properties(
            Path("a.gif"), "GIF", ".gif", "P", 2, 2, False, False, True, "JPEG"
        )
        self.assertIn(ImageWarningCode.ANIMATION_MAY_BE_LOST, self.codes(found))

    def test_animated_gif_fixture_warns_for_static_output(self) -> None:
        source = self.root / "animated.gif"
        first = Image.new("RGB", (2, 2), "red")
        second = Image.new("RGB", (2, 2), "blue")
        first.save(source, save_all=True, append_images=[second], duration=50)
        self.assertIn(
            ImageWarningCode.ANIMATION_MAY_BE_LOST,
            self.codes(validate_image(source, "JPEG")),
        )

    def test_extreme_reduction_and_output_growth(self) -> None:
        reduced = output_size_warnings(Path("a.png"), 1000, 99)
        grown = output_size_warnings(Path("a.png"), 100, 101)
        self.assertIn(
            ImageWarningCode.OUTPUT_SIZE_REDUCTION_EXTREME, self.codes(reduced)
        )
        self.assertIn(ImageWarningCode.OUTPUT_SIZE_INCREASED, self.codes(grown))

    def test_icc_valid_invalid_and_dropped(self) -> None:
        invalid = validate_properties(
            Path("a.png"),
            "PNG",
            ".png",
            "RGB",
            2,
            2,
            False,
            False,
            False,
            "WEBP",
            has_icc=True,
            icc_valid=False,
        )
        codes = self.codes(invalid)
        self.assertIn(ImageWarningCode.ICC_PROFILE_INVALID, codes)
        self.assertIn(ImageWarningCode.ICC_PROFILE_DROPPED, codes)

    def test_decompression_bomb_error_is_blocking(self) -> None:
        source = self.root / "bomb.png"
        source.write_bytes(b"placeholder")
        with patch(
            "image_validation.Image.open",
            side_effect=Image.DecompressionBombError("bomb"),
        ):
            found = validate_image(source, "WEBP")
        self.assertEqual(found[0].code, ImageWarningCode.DECOMPRESSION_BOMB_ERROR)
        self.assertTrue(found[0].blocking)

    def test_decompression_bomb_warning_is_captured(self) -> None:
        source = self.root / "warn.png"
        Image.new("RGB", (2, 2)).save(source)
        real_open = Image.open

        def warning_open(*args, **kwargs):
            warnings.warn("large", Image.DecompressionBombWarning)
            return real_open(*args, **kwargs)

        with patch("image_validation.Image.open", side_effect=warning_open):
            found = validate_image(source, "WEBP")
        self.assertIn(ImageWarningCode.DECOMPRESSION_BOMB_WARNING, self.codes(found))


if __name__ == "__main__":
    unittest.main()
