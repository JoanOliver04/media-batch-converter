"""Non-destructive image validation and stable warning catalogue."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageCms, UnidentifiedImageError

from animation_handling import animation_supported
from i18n import t

EXTREME_DIMENSION = 16_000
MEMORY_PRESSURE_PIXELS = 80_000_000


class WarningSeverity(StrEnum):
    INFORMATION = "information"
    WARNING = "warning"
    BLOCKING_ERROR = "blocking_error"


class ImageWarningCode(StrEnum):
    ALPHA_CHANNEL_PRESENT = "ALPHA_CHANNEL_PRESENT"
    MEANINGFUL_TRANSPARENCY = "MEANINGFUL_TRANSPARENCY"
    ALPHA_WILL_BE_FLATTENED = "ALPHA_WILL_BE_FLATTENED"
    SOURCE_DIMENSIONS_EXTREME = "SOURCE_DIMENSIONS_EXTREME"
    SOURCE_PIXEL_COUNT_EXCESSIVE = "SOURCE_PIXEL_COUNT_EXCESSIVE"
    CORRUPTED_IMAGE = "CORRUPTED_IMAGE"
    EXTENSION_FORMAT_MISMATCH = "EXTENSION_FORMAT_MISMATCH"
    UNUSUAL_COLOR_MODE = "UNUSUAL_COLOR_MODE"
    ICC_PROFILE_INVALID = "ICC_PROFILE_INVALID"
    ICC_PROFILE_DROPPED = "ICC_PROFILE_DROPPED"
    ANIMATION_MAY_BE_LOST = "ANIMATION_MAY_BE_LOST"
    ANIMATION_INTENTIONALLY_DISCARDED = "ANIMATION_INTENTIONALLY_DISCARDED"
    ANIMATED_DESTINATION_UNSUPPORTED = "ANIMATED_DESTINATION_UNSUPPORTED"
    FRAMES_EXTRACTED = "FRAMES_EXTRACTED"
    OUTPUT_SIZE_REDUCTION_EXTREME = "OUTPUT_SIZE_REDUCTION_EXTREME"
    OUTPUT_SIZE_INCREASED = "OUTPUT_SIZE_INCREASED"
    METADATA_DROPPED = "METADATA_DROPPED"
    CMYK_CONVERTED_TO_RGB = "CMYK_CONVERTED_TO_RGB"
    INVALID_DIMENSIONS = "INVALID_DIMENSIONS"
    DECOMPRESSION_BOMB_WARNING = "DECOMPRESSION_BOMB_WARNING"
    DECOMPRESSION_BOMB_ERROR = "DECOMPRESSION_BOMB_ERROR"


@dataclass(frozen=True, slots=True)
class ImageWarning:
    code: ImageWarningCode
    severity: WarningSeverity
    message: str
    source: Path
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def blocking(self) -> bool:
        return self.severity is WarningSeverity.BLOCKING_ERROR


class ImageValidationError(Exception):
    def __init__(self, warnings_found: list[ImageWarning]) -> None:
        self.warnings = tuple(warnings_found)
        super().__init__("; ".join(warning.message for warning in warnings_found))


def _warning(
    code: ImageWarningCode,
    severity: WarningSeverity,
    message: str,
    source: Path,
    **details: Any,
) -> ImageWarning:
    return ImageWarning(code, severity, message, source, details)


def _has_meaningful_transparency(image: Image.Image) -> tuple[bool, bool]:
    has_alpha = "A" in image.getbands() or (
        image.mode == "P" and "transparency" in image.info
    )
    if not has_alpha:
        return False, False
    alpha = (
        image.getchannel("A")
        if "A" in image.getbands()
        else image.convert("RGBA").getchannel("A")
    )
    minimum, _maximum = alpha.getextrema()
    return True, minimum < 255


def validate_properties(
    source: Path,
    detected_format: str | None,
    extension: str,
    mode: str,
    width: int,
    height: int,
    has_alpha: bool,
    meaningful_transparency: bool,
    animated: bool,
    target_format: str,
    has_metadata: bool = False,
    has_icc: bool = False,
    icc_valid: bool = True,
) -> list[ImageWarning]:
    found: list[ImageWarning] = []
    if width <= 0 or height <= 0:
        found.append(
            _warning(
                ImageWarningCode.INVALID_DIMENSIONS,
                WarningSeverity.BLOCKING_ERROR,
                t("validation.invalid_dimensions"),
                source,
                width=width,
                height=height,
            )
        )
    if width >= EXTREME_DIMENSION or height >= EXTREME_DIMENSION:
        found.append(
            _warning(
                ImageWarningCode.SOURCE_DIMENSIONS_EXTREME,
                WarningSeverity.WARNING,
                t("validation.extreme_dimensions"),
                source,
                width=width,
                height=height,
            )
        )
    if width * height >= MEMORY_PRESSURE_PIXELS:
        found.append(
            _warning(
                ImageWarningCode.SOURCE_PIXEL_COUNT_EXCESSIVE,
                WarningSeverity.WARNING,
                t("validation.excessive_pixels"),
                source,
                pixels=width * height,
            )
        )
    expected = {
        "JPEG": {".jpg", ".jpeg"},
        "PNG": {".png"},
        "WEBP": {".webp"},
        "ICO": {".ico"},
        "GIF": {".gif"},
        "BMP": {".bmp"},
        "TIFF": {".tif", ".tiff"},
    }.get((detected_format or "").upper(), set())
    if expected and extension.casefold() not in expected:
        found.append(
            _warning(
                ImageWarningCode.EXTENSION_FORMAT_MISMATCH,
                WarningSeverity.WARNING,
                t("validation.extension_mismatch"),
                source,
                detectedFormat=detected_format,
                extension=extension,
            )
        )
    usual_modes = {"1", "L", "LA", "P", "RGB", "RGBA", "CMYK"}
    if mode not in usual_modes:
        found.append(
            _warning(
                ImageWarningCode.UNUSUAL_COLOR_MODE,
                WarningSeverity.WARNING,
                t("validation.unusual_color_mode", mode=mode),
                source,
                mode=mode,
            )
        )
    if mode == "CMYK":
        found.append(
            _warning(
                ImageWarningCode.CMYK_CONVERTED_TO_RGB,
                WarningSeverity.WARNING,
                t("validation.cmyk_to_rgb"),
                source,
            )
        )
    if has_alpha:
        found.append(
            _warning(
                ImageWarningCode.ALPHA_CHANNEL_PRESENT,
                WarningSeverity.INFORMATION,
                t("validation.alpha_present"),
                source,
            )
        )
    if meaningful_transparency:
        found.append(
            _warning(
                ImageWarningCode.MEANINGFUL_TRANSPARENCY,
                WarningSeverity.INFORMATION,
                t("validation.transparent_pixels"),
                source,
            )
        )
        if target_format.upper() in {"JPEG", "BMP"}:
            found.append(
                _warning(
                    ImageWarningCode.ALPHA_WILL_BE_FLATTENED,
                    WarningSeverity.WARNING,
                    t("validation.alpha_flattened"),
                    source,
                    targetFormat=target_format,
                )
            )
    if animated and not animation_supported(target_format):
        found.append(
            _warning(
                ImageWarningCode.ANIMATION_MAY_BE_LOST,
                WarningSeverity.WARNING,
                t("validation.single_frame_output"),
                source,
                targetFormat=target_format,
            )
        )
    if has_metadata:
        found.append(
            _warning(
                ImageWarningCode.METADATA_DROPPED,
                WarningSeverity.INFORMATION,
                t("validation.metadata_dropped"),
                source,
            )
        )
    if has_icc:
        if not icc_valid:
            found.append(
                _warning(
                    ImageWarningCode.ICC_PROFILE_INVALID,
                    WarningSeverity.WARNING,
                    t("validation.icc_unreadable"),
                    source,
                )
            )
        found.append(
            _warning(
                ImageWarningCode.ICC_PROFILE_DROPPED,
                WarningSeverity.INFORMATION,
                t("validation.icc_not_copied"),
                source,
            )
        )
    return found


def validate_image(source: Path, target_format: str) -> list[ImageWarning]:
    found: list[ImageWarning] = []
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", Image.DecompressionBombWarning)
            with Image.open(source) as probe:
                probe.verify()
            for item in caught:
                if issubclass(item.category, Image.DecompressionBombWarning):
                    found.append(
                        _warning(
                            ImageWarningCode.DECOMPRESSION_BOMB_WARNING,
                            WarningSeverity.WARNING,
                            str(item.message),
                            source,
                        )
                    )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            image = Image.open(source)
        with image:
            has_alpha, meaningful = _has_meaningful_transparency(image)
            icc = image.info.get("icc_profile")
            icc_valid = True
            if icc:
                try:
                    ImageCms.ImageCmsProfile(BytesIO(icc))
                except (OSError, TypeError, ValueError):
                    icc_valid = False
            found.extend(
                validate_properties(
                    source,
                    image.format,
                    source.suffix,
                    image.mode,
                    image.width,
                    image.height,
                    has_alpha,
                    meaningful,
                    bool(getattr(image, "is_animated", False)),
                    target_format,
                    bool(image.getexif())
                    or any(key in image.info for key in ("comment", "xmp")),
                    bool(icc),
                    icc_valid,
                )
            )
    except Image.DecompressionBombError as error:
        found.append(
            _warning(
                ImageWarningCode.DECOMPRESSION_BOMB_ERROR,
                WarningSeverity.BLOCKING_ERROR,
                str(error),
                source,
            )
        )
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        found.append(
            _warning(
                ImageWarningCode.CORRUPTED_IMAGE,
                WarningSeverity.BLOCKING_ERROR,
                t("validation.corrupted", detail=error),
                source,
            )
        )
    return found


def output_size_warnings(
    source: Path, original_bytes: int, output_bytes: int
) -> list[ImageWarning]:
    if original_bytes <= 0:
        return []
    found: list[ImageWarning] = []
    reduction = 1 - output_bytes / original_bytes
    if reduction > 0.90:
        found.append(
            _warning(
                ImageWarningCode.OUTPUT_SIZE_REDUCTION_EXTREME,
                WarningSeverity.WARNING,
                t("validation.size_reduction_extreme"),
                source,
                reductionPercent=round(reduction * 100, 2),
            )
        )
    if output_bytes > original_bytes:
        found.append(
            _warning(
                ImageWarningCode.OUTPUT_SIZE_INCREASED,
                WarningSeverity.INFORMATION,
                t("validation.size_increased"),
                source,
                increaseBytes=output_bytes - original_bytes,
            )
        )
    return found
