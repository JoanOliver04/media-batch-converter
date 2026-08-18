"""Pure resize validation and dimension calculation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from i18n import t


class ResizeMode(StrEnum):
    ORIGINAL = "original"
    MAX_WIDTH = "max_width"
    MAX_HEIGHT = "max_height"
    FIT = "fit"
    PERCENT = "percent"


MAX_DIMENSION = 16_384
MAX_UPSCALE_PERCENT = 1_000


@dataclass(frozen=True, slots=True)
class ResizeConfig:
    mode: ResizeMode = ResizeMode.ORIGINAL
    width: int | None = None
    height: int | None = None
    percentage: float | None = None
    never_upscale: bool = True


def validate_resize_config(config: ResizeConfig) -> None:
    if config.mode in {ResizeMode.MAX_WIDTH, ResizeMode.FIT}:
        _validate_dimension(config.width, t("resize.label.width"))
    if config.mode in {ResizeMode.MAX_HEIGHT, ResizeMode.FIT}:
        _validate_dimension(config.height, t("resize.label.height"))
    if config.mode is ResizeMode.PERCENT:
        if config.percentage is None or config.percentage <= 0:
            raise ValueError(t("resize.percent_positive"))
        limit = 100 if config.never_upscale else MAX_UPSCALE_PERCENT
        if config.percentage > limit:
            raise ValueError(t("resize.percent_limit", limit=limit))


def _validate_dimension(value: int | None, label: str) -> None:
    if value is None or value <= 0:
        raise ValueError(t("resize.dimension_positive", label=label))
    if value > MAX_DIMENSION:
        raise ValueError(
            t("resize.dimension_limit", label=label, limit=f"{MAX_DIMENSION:,}")
        )


def calculate_resize_dimensions(
    original_width: int, original_height: int, config: ResizeConfig
) -> tuple[int, int]:
    """Calculate a proportional target size without cropping or distortion."""
    if original_width <= 0 or original_height <= 0:
        raise ValueError(t("resize.original_positive"))
    validate_resize_config(config)
    if config.mode is ResizeMode.ORIGINAL:
        return original_width, original_height

    if config.mode is ResizeMode.MAX_WIDTH:
        scale = config.width / original_width
    elif config.mode is ResizeMode.MAX_HEIGHT:
        scale = config.height / original_height
    elif config.mode is ResizeMode.FIT:
        scale = min(config.width / original_width, config.height / original_height)
    else:
        scale = config.percentage / 100

    if config.never_upscale:
        scale = min(scale, 1.0)
    width = max(1, round(original_width * scale))
    height = max(1, round(original_height * scale))
    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        raise ValueError(t("resize.result_limit", limit=f"{MAX_DIMENSION:,}"))
    return width, height
