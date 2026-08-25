from __future__ import annotations

import base64
import hashlib
from collections.abc import Sequence

from PIL import Image

from mewcode.llm import ImageContent

from .models import ImageCapture


MAX_IMAGES_PER_BATCH = 4
MAX_BATCH_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_IMAGE_BYTES = 256 * 1024 * 1024
MAX_IMAGE_SIDE = 8192
FOLLOWUP_IMAGE_TURNS = 3

_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


class WechatImageError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def encode_capture(capture: ImageCapture, created_at: int) -> ImageContent:
    try:
        with Image.open(capture.path) as opened:
            actual_format = opened.format
            opened.verify()
        with Image.open(capture.path) as reopened:
            width, height = reopened.size
    except (OSError, ValueError) as exc:
        raise WechatImageError("invalid_image") from exc
    media_type = _FORMATS.get(str(actual_format or "").upper())
    if media_type is None:
        raise WechatImageError("unsupported_format")
    if width < 1 or height < 1 or max(width, height) > MAX_IMAGE_SIDE:
        raise WechatImageError("dimensions_exceeded")
    try:
        raw = capture.path.read_bytes()
    except OSError as exc:
        raise WechatImageError("read_failed") from exc
    if not raw:
        raise WechatImageError("invalid_image")
    return ImageContent(
        media_type=media_type,  # type: ignore[arg-type]
        data=base64.b64encode(raw).decode("ascii"),
        sha256=hashlib.sha256(raw).hexdigest(),
        width=width,
        height=height,
        size_bytes=len(raw),
        created_at=created_at,
        degraded=capture.degraded,
    )


def validate_batch(images: Sequence[ImageContent]) -> None:
    if not images or len(images) > MAX_IMAGES_PER_BATCH:
        raise WechatImageError("batch_limit")
    total = 0
    supported = set(_FORMATS.values())
    for image in images:
        if (
            image.media_type not in supported
            or image.detail != "original"
            or image.cleared
            or not image.data
        ):
            raise WechatImageError("invalid_image")
        if (
            image.width < 1
            or image.height < 1
            or max(image.width, image.height) > MAX_IMAGE_SIDE
        ):
            raise WechatImageError("dimensions_exceeded")
        if image.size_bytes < 1:
            raise WechatImageError("invalid_image")
        total += image.size_bytes
    if total > MAX_BATCH_BYTES:
        raise WechatImageError("batch_limit")


__all__ = [
    "FOLLOWUP_IMAGE_TURNS",
    "MAX_ARCHIVE_IMAGE_BYTES",
    "MAX_BATCH_BYTES",
    "MAX_IMAGES_PER_BATCH",
    "MAX_IMAGE_SIDE",
    "WechatImageError",
    "encode_capture",
    "validate_batch",
]
