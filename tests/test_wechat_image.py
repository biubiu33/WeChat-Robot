from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from PIL import Image

from mewcode.llm import ImageContent
from mewcode.wechat.image import MAX_BATCH_BYTES, WechatImageError, encode_capture, validate_batch
from mewcode.wechat.models import ImageCapture


@pytest.mark.parametrize(
    ("image_format", "media_type"),
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("GIF", "image/gif"), ("WEBP", "image/webp")],
)
def test_encode_capture_uses_actual_format_and_original_bytes(
    tmp_path: Path, image_format: str, media_type: str
) -> None:
    path = tmp_path / "misleading.bin"
    Image.new("RGB", (12, 8), "red").save(path, format=image_format)
    raw = path.read_bytes()

    encoded = encode_capture(ImageCapture(path, degraded=True), 123)

    assert encoded.media_type == media_type
    assert base64.b64decode(encoded.data) == raw
    assert encoded.sha256 == hashlib.sha256(raw).hexdigest()
    assert (encoded.width, encoded.height) == (12, 8)
    assert encoded.degraded is True
    assert encoded.created_at == 123


def test_encode_capture_rejects_broken_and_oversized_images(tmp_path: Path) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    with pytest.raises(WechatImageError, match="invalid_image"):
        encode_capture(ImageCapture(broken, False), 0)

    oversized = tmp_path / "oversized.png"
    Image.new("1", (8193, 1)).save(oversized, format="PNG")
    with pytest.raises(WechatImageError, match="dimensions_exceeded"):
        encode_capture(ImageCapture(oversized, False), 0)


def _content(size: int = 1) -> ImageContent:
    return ImageContent(
        media_type="image/png",
        data="eA==",
        width=1,
        height=1,
        size_bytes=size,
    )


def test_validate_batch_rejects_too_many_or_too_large_as_one_batch() -> None:
    validate_batch([_content(), _content(), _content(), _content()])
    with pytest.raises(WechatImageError, match="batch_limit"):
        validate_batch([_content()] * 5)
    with pytest.raises(WechatImageError, match="batch_limit"):
        validate_batch([_content(MAX_BATCH_BYTES), _content()])
