from __future__ import annotations

import hashlib
import re
import threading
import unicodedata
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from typing import ClassVar

from .models import VisibleMessage

UNKNOWN_SENDER = ""


class GroupSenderOcrUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrTextLine:
    text: str
    score: float
    bounds: tuple[int, int, int, int]

    @property
    def width(self) -> int:
        return max(0, self.bounds[2] - self.bounds[0])

    @property
    def height(self) -> int:
        return max(0, self.bounds[3] - self.bounds[1])


class GroupSenderOcr:
    """Resolve group message direction and sender without replacing UIA text."""

    _IGNORED_NAMES: ClassVar[set[str]] = {
        "头像",
        "群头像",
        "已读",
        "未读",
        "发送失败",
        "重发",
        "撤回",
        "更多",
    }

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._engine = None
        self._cached_digest = ""
        self._cached_lines: tuple[OcrTextLine, ...] = ()

    @staticmethod
    def _normalized(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalized)

    @classmethod
    def _similarity(cls, left: str, right: str) -> float:
        left_value = cls._normalized(left)
        right_value = cls._normalized(right)
        if not left_value or not right_value:
            return 0.0
        if left_value == right_value:
            return 1.0
        if left_value in right_value or right_value in left_value:
            short = min(len(left_value), len(right_value))
            long = max(len(left_value), len(right_value))
            return max(0.82, short / long)
        return SequenceMatcher(None, left_value, right_value).ratio()

    @staticmethod
    def _center(line: OcrTextLine) -> tuple[float, float]:
        left, top, right, bottom = line.bounds
        return (left + right) / 2.0, (top + bottom) / 2.0

    @classmethod
    def _valid_name(cls, line: OcrTextLine) -> bool:
        value = line.text.strip()
        if (
            line.score < 0.75
            or not value
            or value in cls._IGNORED_NAMES
            or len(value) > 40
            or "\n" in value
            or value.startswith("@")
        ):
            return False
        return not re.fullmatch(r"(?:(?:今天|昨天|星期.|周.)\s*)?\d{1,2}:\d{2}", value)

    @classmethod
    def _match_body(
        cls,
        message: VisibleMessage,
        lines: list[OcrTextLine],
        used: set[int],
    ) -> OcrTextLine | None:
        body_texts = tuple(
            dict.fromkeys(
                value.strip()
                for value in (message.text, message.raw_text)
                if value.strip()
            )
        )
        if message.kind != "text" or not message.bounds or not body_texts:
            return None
        left, top, right, bottom = message.bounds
        geometric: list[tuple[float, OcrTextLine]] = []
        textual: list[tuple[float, OcrTextLine]] = []
        for line in lines:
            if id(line) in used or line.score < 0.6:
                continue
            similarity = max(cls._similarity(value, line.text) for value in body_texts)
            if similarity < 0.78:
                continue
            ranked = (similarity * line.score, line)
            textual.append(ranked)
            center_x, center_y = cls._center(line)
            if left <= center_x <= right and top <= center_y <= bottom:
                geometric.append(ranked)
        candidates = geometric or textual
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        if (
            not geometric
            and len(candidates) > 1
            and candidates[0][1].text != candidates[1][1].text
            and candidates[0][0] - candidates[1][0] < 0.08
        ):
            return None
        return candidates[0][1]

    @classmethod
    def _incoming(
        cls,
        body: OcrTextLine,
        pane_bounds: tuple[int, int, int, int],
    ) -> bool | None:
        left, _, right, _ = pane_bounds
        center = (left + right) / 2.0
        threshold = max(12.0, (right - left) * 0.06)
        body_center, _ = cls._center(body)
        if body_center < center - threshold:
            return True
        if body_center > center + threshold:
            return False
        return None

    @classmethod
    def _sender_above(
        cls,
        body: OcrTextLine,
        lines: list[OcrTextLine],
    ) -> str:
        max_gap = 48
        tolerance = max(24, min(120, body.width // 2))
        candidates: list[tuple[float, OcrTextLine]] = []
        for line in lines:
            if line is body or not cls._valid_name(line):
                continue
            gap = body.bounds[1] - line.bounds[3]
            if gap < -3 or gap > max_gap:
                continue
            if abs(line.bounds[0] - body.bounds[0]) > tolerance:
                continue
            if line.height > max(28, int(body.height * 1.1)):
                continue
            candidates.append(((max_gap - max(0, gap)) / max_gap + line.score, line))
        if not candidates:
            return ""
        candidates.sort(key=lambda item: item[0], reverse=True)
        best_rank, best = candidates[0]
        if (
            len(candidates) > 1
            and candidates[1][1].text != best.text
            and best_rank - candidates[1][0] < 0.12
        ):
            return ""
        return best.text.strip()

    @classmethod
    def assign(
        cls,
        messages: list[VisibleMessage],
        lines: list[OcrTextLine],
        pane_bounds: tuple[int, int, int, int],
    ) -> list[VisibleMessage]:
        resolved: list[VisibleMessage] = []
        used: set[int] = set()
        for message in messages:
            body = cls._match_body(message, lines, used)
            if body is None:
                resolved.append(replace(message, incoming=False, sender_name=""))
                continue
            used.add(id(body))
            incoming = cls._incoming(body, pane_bounds)
            sender = cls._sender_above(body, lines) if incoming is True else ""
            resolved.append(
                replace(
                    message,
                    incoming=incoming is True,
                    sender_name=sender if incoming is True else "",
                )
            )
        return resolved

    def preload(self) -> None:
        engine = self._get_engine()
        try:
            import numpy as np

            with self._lock:
                engine(np.zeros((32, 32, 3), dtype=np.uint8))
        except Exception:  # noqa: BLE001 - warm-up is best-effort after load
            # Model construction is the availability gate. Some engines reject
            # an intentionally tiny warm-up image, which does not affect use.
            return

    def enrich(
        self,
        messages: list[VisibleMessage],
        pane_bounds: tuple[int, int, int, int] | None,
    ) -> list[VisibleMessage]:
        if not messages or not pane_bounds:
            return messages
        try:
            import numpy as np
            from PIL import ImageGrab

            image = ImageGrab.grab(bbox=pane_bounds, all_screens=True)
            digest = hashlib.sha256(image.tobytes()).hexdigest()
            with self._lock:
                if digest == self._cached_digest:
                    lines = list(self._cached_lines)
                else:
                    output = self._get_engine()(np.asarray(image))
                    lines = self._output_lines(output, (pane_bounds[0], pane_bounds[1]))
                    self._cached_digest = digest
                    self._cached_lines = tuple(lines)
            return self.assign(messages, lines, pane_bounds)
        except GroupSenderOcrUnavailable:
            raise
        except Exception:  # noqa: BLE001 - OCR failures must fail closed
            return [
                replace(message, incoming=False, sender_name="") for message in messages
            ]

    def _get_engine(self):
        with self._lock:
            if self._engine is not None:
                return self._engine
            try:
                from rapidocr import RapidOCR

                self._engine = RapidOCR()
            except Exception as exc:
                raise GroupSenderOcrUnavailable(
                    "微信群聊需要 OCR 依赖，请安装 MewCode 的 wechat 可选依赖"
                ) from exc
            return self._engine

    @staticmethod
    def _output_lines(result, offset: tuple[int, int]) -> list[OcrTextLine]:
        boxes = getattr(result, "boxes", None)
        texts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is None or texts is None or scores is None:
            return []
        offset_x, offset_y = offset
        lines: list[OcrTextLine] = []
        for box, value, score in zip(boxes, texts, scores):
            points = list(box)
            if not points:
                continue
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            lines.append(
                OcrTextLine(
                    str(value or "").strip(),
                    float(score),
                    (
                        int(min(xs)) + offset_x,
                        int(min(ys)) + offset_y,
                        int(max(xs)) + offset_x,
                        int(max(ys)) + offset_y,
                    ),
                )
            )
        return lines


__all__ = [
    "GroupSenderOcr",
    "GroupSenderOcrUnavailable",
    "OcrTextLine",
]
