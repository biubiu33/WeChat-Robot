from __future__ import annotations

import hashlib
import json
import ntpath
import re
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import (
    ConversationRow,
    ImageCapture,
    MessageReference,
    ReferenceKind,
    ResolvedReference,
    VisibleMessage,
)

SUPPORTED_WECHAT_VERSIONS = ("4.0.5.15", "4.1.9.30")
MAIN_WINDOW_CLASS = "mmui::MainWindow"
SESSION_LIST_ID = "session_list"
MESSAGE_LIST_ID = "chat_message_list"
IMAGE_ITEM_CLASS = "mmui::ChatImageItemView"
REFER_IMAGE_ITEM_CLASS = "mmui::ChatBubbleReferItemView"
INPUT_ID = "chat_input_field"
INPUT_CLASS = "mmui::ChatInputField"
SEARCH_EDIT_CLASS = "mmui::XValidatorTextEdit"
SEARCH_RESULT_CLASS = "mmui::SearchContentCellView"
CHAT_NAME_ID_SUFFIX = "current_chat_name_label"
CHAT_COUNT_ID_SUFFIX = "current_chat_count_label"
SESSION_ITEM_PREFIX = "session_item_"
UNREAD_RE = re.compile(r"(?:\[(\d+)\s*条\]|(\d+)\s*条未读)")
MENTION_MARKERS = ("[有人@我]", "有人@我", "[Someone mentioned me]")


class WechatUiaError(RuntimeError):
    pass


class WechatReferenceTargetError(WechatUiaError):
    pass


class WechatUiaClient:
    def __init__(
        self,
        *,
        expected_versions: tuple[str, ...] = SUPPORTED_WECHAT_VERSIONS,
    ) -> None:
        try:
            import uiautomation as auto
        except ImportError as exc:
            raise WechatUiaError(
                "缺少 uiautomation，请安装 MewCode 的 wechat 可选依赖"
            ) from exc
        self._auto = auto
        self._expected_versions = expected_versions
        self._validated_hwnd = 0
        self._thread_state = threading.local()

    def probe(self) -> None:
        with self._thread_context():
            window = self._main_window()
            records = {
                "version": self._wechat_version(window),
                "main_window": self._describe(window),
                "session_list": self._describe(
                    self._find_unique(window, automation_id=SESSION_LIST_ID)
                ),
                "message_list": self._describe(
                    self._find_unique(window, automation_id=MESSAGE_LIST_ID)
                ),
                "input": self._describe(
                    self._find_unique(window, automation_id=INPUT_ID)
                ),
            }
            print(json.dumps(records, ensure_ascii=False, indent=2))

    def process_ids(self) -> set[int]:
        with self._thread_context():
            return {int(self._main_window().ProcessId)}

    def visible_conversations(self) -> list[ConversationRow]:
        with self._thread_context():
            window = self._main_window()
            session_list = self._find_unique(window, automation_id=SESSION_LIST_ID)
            rows: list[ConversationRow] = []
            for control in session_list.GetChildren():
                if control.ClassName != "mmui::ChatSessionCell":
                    continue
                raw_name = control.Name or ""
                name = self._conversation_name(control, raw_name)
                if not name:
                    continue
                runtime_id = tuple(
                    int(value) for value in (control.GetRuntimeId() or ())
                )
                unread_match = UNREAD_RE.search(raw_name)
                unread_count = (
                    int(unread_match.group(1) or unread_match.group(2))
                    if unread_match
                    else 0
                )
                signature = hashlib.sha256(raw_name.encode("utf-8")).hexdigest()
                rows.append(
                    ConversationRow(
                        key=":".join(map(str, runtime_id)) or name,
                        name=name,
                        runtime_id=runtime_id,
                        signature=signature,
                        unread_count=unread_count,
                        private=None,
                        mentions_self=any(
                            marker in raw_name for marker in MENTION_MARKERS
                        ),
                    )
                )
            return rows

    def visible_private_conversations(self) -> list[ConversationRow]:
        """Compatibility alias retained for callers outside the driver."""

        return self.visible_conversations()

    def focus_conversation(self, row: ConversationRow) -> None:
        with self._thread_context():
            window = self._main_window()
            self._activate_window(window)
            if self.current_conversation_name() == row.name:
                return
            if row.private is False and self._open_visible_group(window, row):
                return
            if row.private is False:
                self._open_conversation_with_search(
                    window,
                    row.name,
                    click_result=True,
                )
                return
            self._open_conversation_with_search(window, row.name)

    def current_conversation_name(self) -> str:
        with self._thread_context():
            window = self._main_window()
            matches = [
                control
                for control in self._walk(window)
                if control.AutomationId.endswith(CHAT_NAME_ID_SUFFIX)
            ]
            return matches[0].Name.strip() if len(matches) == 1 else ""

    def current_conversation_is_private(self) -> bool:
        with self._thread_context():
            window = self._main_window()
            count_labels = [
                control
                for control in self._walk(window)
                if control.AutomationId.endswith(CHAT_COUNT_ID_SUFFIX)
                and control.Name.strip()
            ]
            return not count_labels

    def current_conversation_is_group(self) -> bool:
        return not self.current_conversation_is_private()

    def visible_messages(self, row: ConversationRow) -> list[VisibleMessage]:
        with self._thread_context():
            if self.current_conversation_name() != row.name:
                raise WechatUiaError("读取消息前目标会话已变化")
            private = self.current_conversation_is_private()
            window = self._main_window()
            message_list = self._find_unique(window, automation_id=MESSAGE_LIST_ID)
            messages: list[VisibleMessage] = []
            for control in message_list.GetChildren():
                raw_name = (control.Name or "").strip()
                parsed_reference = self._parse_reference_label(raw_name)
                kind = _control_message_kind(control)
                if not kind:
                    continue
                reference = None
                if parsed_reference is not None:
                    text, reference = parsed_reference
                else:
                    text = raw_name if kind == "text" else "[图片]"
                if kind == "text" and not text:
                    continue
                runtime_id = tuple(
                    int(value) for value in (control.GetRuntimeId() or ())
                )
                messages.append(
                    VisibleMessage(
                        key=":".join(map(str, runtime_id)) or text,
                        conversation_key=row.key,
                        text=text,
                        incoming=private,
                        kind=kind,
                        sender_name=row.name if private else "",
                        bounds=self._bounds(control),
                        reference=reference,
                        raw_text=raw_name,
                    )
                )
            return messages

    @staticmethod
    def _parse_reference_label(
        content: str,
    ) -> tuple[str, MessageReference] | None:
        match = re.match(
            r"^(?P<current>.*?)引用\s+(?P<sender>.+?)\s+的消息\s*[:：]\s*(?P<preview>.*)$",
            str(content or ""),
            re.DOTALL,
        )
        if match is None:
            return None
        current = match.group("current").strip()
        sender = match.group("sender").strip()
        preview = match.group("preview").strip()
        if not sender:
            return None
        kind, unsupported_type = _reference_kind(preview)
        return current, MessageReference(
            sender,
            preview,
            kind,
            unsupported_type,
        )

    def visible_text_messages(self, row: ConversationRow) -> list[VisibleMessage]:
        return [
            message for message in self.visible_messages(row) if message.kind == "text"
        ]

    def capture_private_image(
        self,
        row: ConversationRow,
        message_key: str,
        bounds: tuple[int, int, int, int] | None,
        target_dir: Path,
    ) -> ImageCapture | None:
        with self._thread_context():
            self.focus_conversation(row)
            if not self.validate_target(row.name, True):
                return None
            window = self._main_window()
            message_list = self._find_unique(window, automation_id=MESSAGE_LIST_ID)
            control = self._find_image_control(message_list, message_key, bounds)
            actual_bounds = self._bounds(control) if control is not None else bounds
            if control is None or not _valid_bounds(actual_bounds):
                return None
            target_dir.mkdir(parents=True, exist_ok=True)
            identity = f"{row.key}\0{message_key}\0{actual_bounds}"
            target = target_dir / (
                hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16] + ".png"
            )
            viewer_result = self._capture_viewer(control, window, target)
            if viewer_result:
                if self.validate_target(row.name, True):
                    return ImageCapture(target, degraded=False)
                target.unlink(missing_ok=True)
                return None
            target.unlink(missing_ok=True)
            if viewer_result is None:
                return None
            if not self.validate_target(row.name, True):
                return None
            if self._capture_bounds(actual_bounds, target):
                return ImageCapture(target, degraded=True)
            target.unlink(missing_ok=True)
            return None

    def _find_image_control(
        self,
        message_list: Any,
        message_key: str,
        bounds: tuple[int, int, int, int] | None,
    ) -> Any | None:
        candidates = [
            control
            for control in message_list.GetChildren()
            if _control_message_kind(control) == "image"
        ]
        for control in candidates:
            runtime_id = ":".join(
                map(str, tuple(int(value) for value in (control.GetRuntimeId() or ())))
            )
            if runtime_id and runtime_id == message_key:
                return control
        if bounds is None:
            return None
        close = [
            control
            for control in candidates
            if _bounds_close(self._bounds(control), bounds)
        ]
        return close[0] if len(close) == 1 else None

    def resolve_reference(
        self,
        row: ConversationRow,
        message_key: str,
        bounds: tuple[int, int, int, int] | None,
        current_text: str,
        reference: MessageReference,
        target_dir: Path,
    ) -> ResolvedReference:
        with self._thread_context():
            self.focus_conversation(row)
            if not self.validate_target(row.name, bool(row.private)):
                raise WechatReferenceTargetError("引用解析前回复目标无法确认")
            if reference.kind == "unsupported":
                return ResolvedReference(reference, strategy="unsupported")
            target_dir.mkdir(parents=True, exist_ok=True)
            window = self._main_window()
            message_list = self._find_unique(window, automation_id=MESSAGE_LIST_ID)
            control = self._find_reference_control(
                message_list,
                message_key,
                bounds,
                current_text,
                reference,
            )
            if control is None:
                return self._reference_preview(reference)
            if reference.kind == "image":
                return self._resolve_reference_image(
                    row,
                    control,
                    message_key,
                    current_text,
                    reference,
                    target_dir,
                    window,
                )

            original = self._locate_referenced_original(control, reference)
            reclassified_image: MessageReference | None = None
            try:
                if original is not None:
                    original_name = str(getattr(original, "Name", "") or "").strip()
                    parsed = self._parse_reference_label(original_name)
                    original_text = parsed[0] if parsed is not None else original_name
                    original_kind, unsupported = _original_kind(original)
                    if original_kind == "text" and original_text:
                        return ResolvedReference(
                            reference,
                            content=original_text,
                            strategy="wechat_locate_original",
                        )
                    if original_kind == "unsupported":
                        return ResolvedReference(
                            MessageReference(
                                reference.sender_name,
                                reference.preview,
                                "unsupported",
                                unsupported,
                            ),
                            strategy="wechat_locate_original",
                        )
                    if original_kind == "image":
                        reclassified_image = MessageReference(
                            reference.sender_name,
                            reference.preview,
                            "image",
                        )
                        identity = (
                            f"{row.key}\0{message_key}\0{self._bounds(original)}"
                            "\0reclassified-reference"
                        )
                        target = target_dir / (
                            hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
                            + ".png"
                        )
                        captured = self._capture_viewer(original, window, target)
                        if captured:
                            return ResolvedReference(
                                reclassified_image,
                                capture=ImageCapture(target, degraded=False),
                                strategy="wechat_locate_original_image_viewer",
                            )
                        if captured is None:
                            raise WechatReferenceTargetError(
                                "重分类原图片查看器未安全恢复"
                            )
            finally:
                self._restore_reference_target(row)
            if reclassified_image is not None:
                restored_window = self._main_window()
                restored_list = self._find_unique(
                    restored_window, automation_id=MESSAGE_LIST_ID
                )
                restored_quote = self._find_reference_control(
                    restored_list,
                    message_key,
                    bounds,
                    current_text,
                    reference,
                )
                if restored_quote is None:
                    return ResolvedReference(
                        reclassified_image,
                        strategy="unavailable",
                    )
                return self._resolve_reference_image(
                    row,
                    restored_quote,
                    message_key,
                    current_text,
                    reference,
                    target_dir,
                    restored_window,
                    resolved_source=reclassified_image,
                )
            return self._reference_preview(reference)

    @staticmethod
    def _reference_preview(reference: MessageReference) -> ResolvedReference:
        if reference.kind != "text":
            return ResolvedReference(reference, strategy="unavailable")
        return ResolvedReference(
            reference,
            content=reference.preview,
            degraded=True,
            strategy="uia_reference_preview_only",
        )

    def _find_reference_control(
        self,
        message_list: Any,
        message_key: str,
        bounds: tuple[int, int, int, int] | None,
        current_text: str,
        reference: MessageReference,
    ) -> Any | None:
        exact: list[Any] = []
        identity: list[Any] = []
        for control in message_list.GetChildren():
            parsed = self._parse_reference_label(
                str(getattr(control, "Name", "") or "")
            )
            if parsed != (current_text, reference):
                continue
            identity.append(control)
            runtime_id = ":".join(
                map(str, tuple(int(value) for value in (control.GetRuntimeId() or ())))
            )
            if (message_key and runtime_id == message_key) or (
                bounds is not None and _bounds_close(self._bounds(control), bounds)
            ):
                exact.append(control)
        if len(exact) == 1:
            return exact[0]
        return identity[0] if len(identity) == 1 else None

    @staticmethod
    def _reference_activation_point(
        bounds: tuple[int, int, int, int],
    ) -> tuple[int, int]:
        left, top, right, bottom = bounds
        return (
            int(left + (right - left) * 0.25),
            int(top + (bottom - top) * 0.76),
        )

    @staticmethod
    def _reference_thumbnail_bounds(
        bounds: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int]:
        left, top, right, bottom = bounds
        return (left, int(top + (bottom - top) * 0.45), right, bottom)

    def _locate_referenced_original(
        self,
        control: Any,
        reference: MessageReference,
    ) -> Any | None:
        bounds = self._bounds(control)
        if not _valid_bounds(bounds):
            return None
        assert bounds is not None
        self._right_click_point(self._reference_activation_point(bounds))
        time.sleep(0.3)
        menu = self._find_desktop_control("定位到原文位置", "mmui::XMenuView")
        if menu is None:
            return None
        self._click_preserving_cursor(menu)
        time.sleep(0.6)
        window = self._main_window()
        message_list = self._find_unique(window, automation_id=MESSAGE_LIST_ID)
        return self._pick_located_original_control(message_list, reference)

    def _pick_located_original_control(
        self,
        message_list: Any,
        reference: MessageReference,
    ) -> Any | None:
        preview = _normalized_reference_text(reference.preview)
        matches: list[Any] = []
        for control in message_list.GetChildren():
            name = str(getattr(control, "Name", "") or "").strip()
            if self._parse_reference_label(name) is not None:
                continue
            kind, _ = _original_kind(control)
            if reference.kind == "image":
                if kind == "image":
                    matches.append(control)
                continue
            normalized = _normalized_reference_text(name)
            if preview and normalized and (preview in normalized or normalized in preview):
                matches.append(control)
        return matches[0] if len(matches) == 1 else None

    def _restore_reference_target(self, row: ConversationRow) -> None:
        button = self._find_desktop_control("回到引用位置", "mmui::UnreadBarView")
        if button is not None:
            self._click_preserving_cursor(button)
            time.sleep(0.3)
        self.focus_conversation(row)
        if not self.validate_target(row.name, bool(row.private)):
            raise WechatReferenceTargetError("引用解析后回复目标无法恢复")

    def _resolve_reference_image(
        self,
        row: ConversationRow,
        control: Any,
        message_key: str,
        current_text: str,
        reference: MessageReference,
        target_dir: Path,
        main_window: Any,
        *,
        resolved_source: MessageReference | None = None,
    ) -> ResolvedReference:
        source = resolved_source or reference
        bounds = self._bounds(control)
        if not _valid_bounds(bounds):
            return ResolvedReference(source, strategy="unavailable")
        assert bounds is not None
        identity = f"{row.key}\0{message_key}\0{bounds}\0reference"
        target = target_dir / (
            hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16] + ".png"
        )
        direct = self._capture_viewer_from_point(
            self._reference_activation_point(bounds), main_window, target
        )
        if direct:
            if not self.validate_target(row.name, bool(row.private)):
                target.unlink(missing_ok=True)
                raise WechatReferenceTargetError("引用大图后回复目标已变化")
            return ResolvedReference(
                source,
                capture=ImageCapture(target, degraded=False),
                strategy="wechat_reference_image_viewer",
            )
        if direct is None:
            raise WechatReferenceTargetError("引用大图查看器未安全恢复")
        if not self.validate_target(row.name, bool(row.private)):
            raise WechatReferenceTargetError("引用大图失败后回复目标已变化")

        original = self._locate_referenced_original(control, reference)
        try:
            if original is not None and _original_kind(original)[0] == "image":
                original_target = target.with_stem(target.stem + "-original")
                captured = self._capture_viewer(original, main_window, original_target)
                if captured:
                    return ResolvedReference(
                        source,
                        capture=ImageCapture(original_target, degraded=False),
                        strategy="wechat_locate_original_image_viewer",
                    )
                if captured is None:
                    raise WechatReferenceTargetError("原图片查看器未安全恢复")
        finally:
            self._restore_reference_target(row)

        window = self._main_window()
        message_list = self._find_unique(window, automation_id=MESSAGE_LIST_ID)
        quote = self._find_reference_control(
            message_list,
            message_key,
            bounds,
            current_text,
            reference,
        )
        quote_bounds = self._bounds(quote) if quote is not None else None
        if not _valid_bounds(quote_bounds):
            return ResolvedReference(source, strategy="unavailable")
        assert quote_bounds is not None
        thumb_target = target.with_stem(target.stem + "-thumbnail")
        if self._capture_bounds(
            self._reference_thumbnail_bounds(quote_bounds), thumb_target
        ):
            return ResolvedReference(
                source,
                capture=ImageCapture(thumb_target, degraded=True),
                degraded=True,
                strategy="uia_reference_thumbnail",
            )
        return ResolvedReference(source, strategy="unavailable")

    def _capture_viewer(
        self, control: Any, main_window: Any, target: Path
    ) -> bool | None:
        return self._capture_viewer_action(
            lambda: self._click_preserving_cursor(control), main_window, target
        )

    def _capture_viewer_from_point(
        self,
        point: tuple[int, int],
        main_window: Any,
        target: Path,
    ) -> bool | None:
        return self._capture_viewer_action(
            lambda: self._left_click_point(point), main_window, target
        )

    def _capture_viewer_action(
        self,
        click: Any,
        main_window: Any,
        target: Path,
    ) -> bool | None:
        try:
            import win32gui  # type: ignore[import-untyped]
            from PIL import ImageGrab

            main_hwnd = int(main_window.NativeWindowHandle or 0)
            visible_before = _visible_window_handles()
            click()
            time.sleep(0.6)
            viewer_hwnd = self._opened_image_viewer(main_hwnd, visible_before)
            if not viewer_hwnd:
                self._activate_window(main_window)
                return False
            captured = False
            closed = False
            try:
                raw_bounds = win32gui.GetWindowRect(viewer_hwnd)
                viewer_bounds = (
                    int(raw_bounds[0]),
                    int(raw_bounds[1]),
                    int(raw_bounds[2]),
                    int(raw_bounds[3]),
                )
                image = ImageGrab.grab(bbox=viewer_bounds, all_screens=True)
                if image.width >= 2 and image.height >= 2:
                    image.save(target, format="PNG")
                    captured = True
            finally:
                closed = self._close_image_viewer(viewer_hwnd)
                self._activate_window(main_window)
            if not closed:
                target.unlink(missing_ok=True)
                return None
            return captured
        except Exception:
            try:
                self._activate_window(main_window)
            except Exception:
                pass
            target.unlink(missing_ok=True)
            return None

    @staticmethod
    def _left_click_point(point: tuple[int, int]) -> None:
        import win32api  # type: ignore[import-untyped]
        import win32con  # type: ignore[import-untyped]

        cursor = win32api.GetCursorPos()
        try:
            win32api.SetCursorPos(point)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        finally:
            win32api.SetCursorPos(cursor)

    @staticmethod
    def _right_click_point(point: tuple[int, int]) -> None:
        import win32api  # type: ignore[import-untyped]
        import win32con  # type: ignore[import-untyped]

        cursor = win32api.GetCursorPos()
        try:
            win32api.SetCursorPos(point)
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        finally:
            win32api.SetCursorPos(cursor)

    def _find_desktop_control(self, name: str, class_name: str) -> Any | None:
        root = self._auto.GetRootControl()
        controls = [root, *self._walk(root)]
        matches = [
            control
            for control in controls
            if str(getattr(control, "Name", "") or "") == name
            and str(getattr(control, "ClassName", "") or "") == class_name
        ]
        return matches[0] if len(matches) == 1 else None

    def _opened_image_viewer(
        self,
        main_hwnd: int,
        visible_before: set[int],
    ) -> int:
        try:
            import win32gui  # type: ignore[import-untyped]
            import win32process  # type: ignore[import-untyped]

            if not main_hwnd or not win32gui.IsWindow(main_hwnd):
                return 0
            _, main_pid = win32process.GetWindowThreadProcessId(main_hwnd)
            candidates: list[int] = []

            def collect(hwnd: int, _: object) -> bool:
                value = int(hwnd or 0)
                if (
                    not value
                    or value in visible_before
                    or not win32gui.IsWindowVisible(value)
                ):
                    return True
                _, pid = win32process.GetWindowThreadProcessId(value)
                title = str(win32gui.GetWindowText(value) or "").strip().casefold()
                if int(pid) == int(main_pid) and title in {
                    "图片和视频",
                    "images and videos",
                }:
                    candidates.append(value)
                return True

            win32gui.EnumWindows(collect, None)
            verified = [
                hwnd
                for hwnd in candidates
                if self._viewer_close_control(hwnd) is not None
            ]
            return verified[0] if len(verified) == 1 else 0
        except Exception:
            return 0

    def _viewer_close_control(self, viewer_hwnd: int) -> Any | None:
        try:
            root = self._auto.ControlFromHandle(viewer_hwnd)
            controls = [root, *self._walk(root)]
            return next(
                (
                    control
                    for control in controls
                    if str(getattr(control, "Name", "")).strip().casefold()
                    in {"关闭", "close"}
                    and str(getattr(control, "ClassName", "")) == "mmui::XButton"
                ),
                None,
            )
        except Exception:
            return None

    def _close_image_viewer(self, viewer_hwnd: int) -> bool:
        control = self._viewer_close_control(viewer_hwnd)
        if control is None:
            return False
        try:
            import win32gui  # type: ignore[import-untyped]

            self._click_preserving_cursor(control)
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                if not win32gui.IsWindowVisible(viewer_hwnd):
                    return True
                time.sleep(0.05)
            return not win32gui.IsWindowVisible(viewer_hwnd)
        except Exception:
            return False

    @staticmethod
    def _capture_bounds(
        bounds: tuple[int, int, int, int] | None,
        target: Path,
    ) -> bool:
        if not _valid_bounds(bounds):
            return False
        try:
            from PIL import ImageGrab

            image = ImageGrab.grab(bbox=bounds, all_screens=True)
            if image.width < 2 or image.height < 2:
                return False
            image.save(target, format="PNG")
            return True
        except Exception:
            return False

    def message_list_bounds(self) -> tuple[int, int, int, int] | None:
        with self._thread_context():
            window = self._main_window()
            return self._bounds(
                self._find_unique(window, automation_id=MESSAGE_LIST_ID)
            )

    def validate_target(self, conversation_name: str, private: bool = True) -> bool:
        with self._thread_context():
            return (
                self.current_conversation_name() == conversation_name
                and self.current_conversation_is_private() is private
            )

    def send_text(self, row: ConversationRow, text: str) -> None:
        with self._thread_context():
            if not text:
                return
            self.focus_conversation(row)
            private = row.private is not False
            if not self._target_matches(row.name, private):
                raise WechatUiaError("发送前无法确认原微信会话")
            window = self._main_window()
            input_control = self._find_unique(window, automation_id=INPUT_ID)
            value = input_control.GetValuePattern()
            if value is None:
                raise WechatUiaError("微信输入框不支持 ValuePattern")
            if value.Value:
                raise WechatUiaError("微信输入框存在未发送内容，已拒绝覆盖")
            value.SetValue(text)
            if not self._target_matches(row.name, private):
                value.SetValue("")
                raise WechatUiaError("写入后微信目标会话发生变化，已取消发送")
            self._send_with_enter(
                input_control,
                value,
                row.name,
                text,
                private=private,
            )

    def send_group_text_with_mention(
        self,
        row: ConversationRow,
        sender_name: str,
        text: str,
        *,
        timeout_seconds: float = 1.5,
    ) -> bool:
        """Send one group bubble, preferring a real WeChat mention.

        Returns True for a selected member mention and False for the safe text
        fallback. It never retries the final send.
        """

        with self._thread_context():
            self.focus_conversation(row)
            if not self._target_matches(row.name, False):
                raise WechatUiaError("发送前无法确认原微信群聊")
            window = self._main_window()
            input_control = self._find_unique(window, automation_id=INPUT_ID)
            value = input_control.GetValuePattern()
            if value is None:
                raise WechatUiaError("微信输入框不支持 ValuePattern")
            if value.Value:
                raise WechatUiaError("微信输入框存在未发送内容，已拒绝覆盖")

            fallback_reason = "按 Enter 后未生成微信原生 @"
            owned_values = {f"@{sender_name}"}
            try:
                input_control.SetFocus()
                self._auto.SendKeys("@", waitTime=0.15)
                self._type_unicode_text(sender_name)
                time.sleep(min(0.15, max(0.0, timeout_seconds)))
                draft = str(value.Value or "")
                if draft != f"@{sender_name}":
                    raise WechatUiaError("输入 @ 人名时微信输入框内容发生变化")
                self._auto.SendKeys("{Enter}", waitTime=0.15)
                prefix = str(value.Value or "")
                owned_values.add(prefix)
                if prefix == draft:
                    fallback_reason = "按 Enter 后未生成微信原生 @"
                elif not self._target_matches(row.name, False):
                    fallback_reason = "选择群成员后目标群发生变化"
                else:
                    self._type_unicode_text(text)
                    final_value = str(value.Value or "")
                    if not final_value or text not in final_value:
                        raise WechatUiaError("追加群回复正文失败")
                    self._send_with_enter(
                        input_control,
                        value,
                        row.name,
                        final_value,
                        private=False,
                    )
                    return True
            except WechatUiaError:
                raise
            except Exception as exc:  # noqa: BLE001 - fall back after UI variance
                fallback_reason = f"群成员菜单操作失败: {type(exc).__name__}"

            self._clear_owned_input(value, tuple(owned_values))
            fallback = f"@{sender_name}\n{text}"
            value.SetValue(fallback)
            if not self._target_matches(row.name, False):
                self._clear_owned_input(value, (fallback,))
                raise WechatUiaError("文本 @ 降级前目标群发生变化")
            self._send_with_enter(
                input_control,
                value,
                row.name,
                fallback,
                private=False,
            )
            self._last_mention_fallback_reason = fallback_reason
            return False

    def mention_fallback_reason(self) -> str:
        return str(getattr(self, "_last_mention_fallback_reason", ""))

    def _open_conversation_with_search(
        self,
        window: Any,
        conversation_name: str,
        *,
        timeout_seconds: float = 2.0,
        click_result: bool = False,
    ) -> None:
        self._activate_window(window, timeout_seconds=timeout_seconds)
        self._auto.SendKeys("{Ctrl}f", waitTime=0.2)
        search = self._auto.GetFocusedControl()
        if search is None or search.ClassName != SEARCH_EDIT_CLASS:
            raise WechatUiaError("Ctrl+F 后微信搜索框未获得焦点")
        value = search.GetValuePattern()
        if value is None:
            raise WechatUiaError("微信搜索框不支持 ValuePattern")
        self._auto.SendKeys("{Ctrl}a", waitTime=0.1)
        self._auto.SendKeys(conversation_name, interval=0.03, waitTime=0.3)

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            focused = self._auto.GetFocusedControl()
            if focused is None or focused.ClassName != SEARCH_EDIT_CLASS:
                raise WechatUiaError("搜索微信会话期间键盘焦点已变化")
            if value.Value != conversation_name:
                self._dismiss_search()
                raise WechatUiaError("微信搜索内容与目标好友不一致")
            results = [
                control
                for control in self._find_all(self._main_window())
                if control.ClassName == SEARCH_RESULT_CLASS
                and control.Name == conversation_name
            ]
            if len(results) == 1:
                break
            if len(results) > 1:
                self._dismiss_search()
                raise WechatUiaError(f"微信搜索结果 {conversation_name!r} 不唯一")
            time.sleep(0.05)
        else:
            self._dismiss_search()
            raise WechatUiaError(f"未找到微信好友 {conversation_name!r} 的搜索结果")

        if click_result:
            self._click_preserving_cursor(results[0])
        else:
            self._auto.SendKeys("{Enter}", waitTime=0.3)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.current_conversation_name() == conversation_name:
                return
            time.sleep(0.05)
        self._dismiss_search()
        raise WechatUiaError(f"切换到微信会话 {conversation_name!r} 超时")

    def _open_visible_group(self, window: Any, row: ConversationRow) -> bool:
        session_list = self._find_unique(window, automation_id=SESSION_LIST_ID)
        candidates = [
            control
            for control in session_list.GetChildren()
            if control.ClassName == "mmui::ChatSessionCell"
            and self._conversation_name(control, control.Name or "") == row.name
        ]
        if len(candidates) != 1:
            return False
        self._click_preserving_cursor(candidates[0])
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if self.current_conversation_name() == row.name:
                return True
            time.sleep(0.05)
        raise WechatUiaError(f"点击微信群聊 {row.name!r} 后详情页未激活")

    @staticmethod
    def _click_preserving_cursor(control: Any) -> None:
        import win32api  # type: ignore[import-untyped]

        cursor = win32api.GetCursorPos()
        try:
            control.Click()
        finally:
            win32api.SetCursorPos(cursor)

    @staticmethod
    def _activate_window(window: Any, *, timeout_seconds: float = 2.0) -> None:
        import win32gui

        window.SetActive()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if win32gui.GetForegroundWindow() == int(window.NativeWindowHandle):
                time.sleep(0.05)
                return
            time.sleep(0.05)
        raise WechatUiaError("微信主窗口未能获得前台焦点")

    def _send_with_enter(
        self,
        input_control: Any,
        value: Any,
        conversation_name: str,
        text: str,
        *,
        timeout_seconds: float = 2.0,
        private: bool = True,
    ) -> None:
        input_control.SetFocus()
        focused = self._auto.GetFocusedControl()
        if (
            focused is None
            or focused.AutomationId != INPUT_ID
            or focused.ClassName != INPUT_CLASS
            or value.Value != text
            or not self._target_matches(conversation_name, private)
        ):
            if value.Value == text:
                value.SetValue("")
            raise WechatUiaError("按 Enter 前无法确认微信输入框和目标会话")

        self._auto.SendKeys("{Enter}", waitTime=0.2)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not value.Value:
                if not self._target_matches(conversation_name, private):
                    raise WechatUiaError("发送后微信目标会话发生变化")
                return
            time.sleep(0.05)
        if not value.Value:
            return
        if value.Value.rstrip("\r\n") == text:
            value.SetValue("")
        raise WechatUiaError("按 Enter 后微信输入框未清空，消息可能未发送")

    def _type_unicode_text(self, text: str) -> None:
        for character in text:
            if not self._auto.SendUnicodeChar(character):
                raise WechatUiaError("向微信输入群回复正文失败")
        time.sleep(0.05)

    def _clear_owned_input(self, value: Any, owned_values: tuple[str, ...]) -> None:
        current = str(value.Value or "")
        if current and current not in owned_values:
            raise WechatUiaError("微信输入框内容发生变化，无法安全清理本次 @ 草稿")
        if current:
            value.SetValue("")
        if value.Value:
            raise WechatUiaError("无法清理由本次 @ 操作写入的输入内容")

    def _dismiss_search(self) -> None:
        focused = self._auto.GetFocusedControl()
        if focused is not None and focused.ClassName == SEARCH_EDIT_CLASS:
            self._auto.SendKeys("{Esc}", waitTime=0.1)

    def _target_matches(self, conversation_name: str, private: bool) -> bool:
        try:
            return self.validate_target(conversation_name, private)
        except TypeError:
            # Retains compatibility with injected legacy clients in focused
            # tests and third-party wrappers that only accepted the name.
            return self.validate_target(conversation_name)

    @contextmanager
    def _thread_context(self) -> Iterator[None]:
        depth = getattr(self._thread_state, "depth", 0)
        initializer = None
        if depth == 0:
            initializer = self._auto.UIAutomationInitializerInThread()
        self._thread_state.depth = depth + 1
        try:
            yield
        finally:
            self._thread_state.depth -= 1
            if initializer is not None:
                initializer.Uninitialize()

    def _main_window(self) -> Any:
        controls = self._auto.GetRootControl().GetChildren()
        windows = [
            control for control in controls if control.ClassName == MAIN_WINDOW_CLASS
        ]
        if not windows and any(self._is_weixin_shell(control) for control in controls):
            raise WechatUiaError(
                "微信 UI Automation 未激活，请先启动 Windows 讲述人并重启微信"
            )
        if len(windows) != 1:
            raise WechatUiaError(
                f"需要且只允许一个微信主窗口，当前找到 {len(windows)} 个"
            )
        window = windows[0]
        hwnd = int(window.NativeWindowHandle)
        if hwnd != self._validated_hwnd:
            actual = self._wechat_version(window)
            if actual not in self._expected_versions:
                supported = "、".join(self._expected_versions)
                raise WechatUiaError(f"仅支持微信 {supported}，当前版本为 {actual}")
            self._validated_hwnd = hwnd
        return window

    def _is_weixin_shell(self, control: Any) -> bool:
        class_name = str(getattr(control, "ClassName", ""))
        if not (class_name.startswith("Qt") and class_name.endswith("QWindowIcon")):
            return False
        try:
            executable = self._wechat_process_path(control)
        except WechatUiaError:
            return False
        return ntpath.basename(executable).casefold() == "weixin.exe"

    @staticmethod
    def _wechat_process_path(window: Any) -> str:
        try:
            import win32api
            import win32con  # type: ignore[import-untyped]
            import win32process

            handle = win32api.OpenProcess(
                win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                False,
                int(window.ProcessId),
            )
            try:
                return str(win32process.GetModuleFileNameEx(handle, 0))
            finally:
                win32api.CloseHandle(handle)
        except Exception as exc:
            raise WechatUiaError(f"无法读取微信客户端进程路径: {exc}") from exc

    def _wechat_version(self, window: Any) -> str:
        try:
            import win32api

            path = self._wechat_process_path(window)
            info = win32api.GetFileVersionInfo(path, "\\")
            ms, ls = info["FileVersionMS"], info["FileVersionLS"]
            return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
        except Exception as exc:
            raise WechatUiaError(f"无法读取微信客户端版本: {exc}") from exc

    def _conversation_name(self, control: Any, raw_name: str) -> str:
        automation_id = control.AutomationId or ""
        if automation_id.startswith(SESSION_ITEM_PREFIX):
            return automation_id.removeprefix(SESSION_ITEM_PREFIX).strip()
        unread_match = UNREAD_RE.search(raw_name)
        if unread_match:
            return raw_name[: unread_match.start()].strip()
        return raw_name.splitlines()[0].strip() if raw_name else ""

    def _find_unique(self, root: Any, *, automation_id: str | None = None) -> Any:
        matches = self._find_all(root, automation_id=automation_id)
        if len(matches) != 1:
            raise WechatUiaError(
                f"UIA 控件 {automation_id!r} 需要唯一，实际匹配 {len(matches)} 项"
            )
        return matches[0]

    def _find_all(self, root: Any, *, automation_id: str | None = None) -> list[Any]:
        return [
            control
            for control in self._walk(root)
            if automation_id is None or control.AutomationId == automation_id
        ]

    def _walk(self, root: Any) -> Iterable[Any]:
        return (control for control, _ in self._auto.WalkControl(root, True, 30))

    @staticmethod
    def _describe(control: Any) -> dict[str, object]:
        return {
            "name": control.Name,
            "control_type": control.ControlTypeName,
            "class_name": control.ClassName,
            "automation_id": control.AutomationId,
            "runtime_id": list(control.GetRuntimeId() or ()),
        }

    @staticmethod
    def _bounds(control: Any) -> tuple[int, int, int, int] | None:
        rectangle = getattr(control, "BoundingRectangle", None)
        if rectangle is None:
            return None
        values = (
            getattr(rectangle, "left", getattr(rectangle, "Left", None)),
            getattr(rectangle, "top", getattr(rectangle, "Top", None)),
            getattr(rectangle, "right", getattr(rectangle, "Right", None)),
            getattr(rectangle, "bottom", getattr(rectangle, "Bottom", None)),
        )
        if any(value is None for value in values):
            return None
        return tuple(int(value) for value in values)  # type: ignore[arg-type,return-value]


def _valid_bounds(bounds: tuple[int, int, int, int] | None) -> bool:
    return bool(
        bounds
        and bounds[2] > bounds[0]
        and bounds[3] > bounds[1]
    )


def _control_message_kind(control: Any) -> str:
    class_name = str(getattr(control, "ClassName", ""))
    name = str(getattr(control, "Name", "") or "").strip()
    if WechatUiaClient._parse_reference_label(name) is not None:
        return "text"
    if class_name == "mmui::ChatTextItemView":
        return "text"
    if class_name == IMAGE_ITEM_CLASS:
        return "image"
    if class_name == REFER_IMAGE_ITEM_CLASS and name.casefold() in {"图片", "image"}:
        return "image"
    return ""


def _reference_kind(preview: str) -> tuple[ReferenceKind, str]:
    value = str(preview or "").strip()
    folded = value.strip("[]【】").strip().casefold()
    if folded in {"图片", "image", "[图片]", "[image]"}:
        return "image", ""
    markers = {
        "语音": "voice",
        "voice": "voice",
        "视频": "video",
        "video": "video",
        "文件": "file",
        "file": "file",
        "分享卡片": "share_card",
        "share card": "share_card",
    }
    if folded in markers:
        return "unsupported", markers[folded]
    if re.search(
        r"\.(?:docx?|pdf|xlsx?|pptx?|txt|md|csv|zip|rar|7z)$",
        value,
        re.IGNORECASE,
    ):
        return "unsupported", "file"
    return "text", ""


def _original_kind(control: Any) -> tuple[ReferenceKind, str]:
    class_name = str(getattr(control, "ClassName", "") or "").casefold()
    name = str(getattr(control, "Name", "") or "").strip()
    if _control_message_kind(control) == "image":
        return "image", ""
    if "voice" in class_name or name.casefold() in {"语音", "voice"}:
        return "unsupported", "voice"
    if "video" in class_name or name.casefold() in {"视频", "video"}:
        return "unsupported", "video"
    if "file" in class_name:
        return "unsupported", "file"
    parsed = WechatUiaClient._parse_reference_label(name)
    if parsed is not None:
        return "text", ""
    return _reference_kind(name)


def _normalized_reference_text(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").casefold())


def _bounds_close(
    actual: tuple[int, int, int, int] | None,
    expected: tuple[int, int, int, int],
    tolerance: int = 8,
) -> bool:
    return bool(
        actual
        and all(abs(left - right) <= tolerance for left, right in zip(actual, expected))
    )


def _visible_window_handles() -> set[int]:
    import win32gui  # type: ignore[import-untyped]

    handles: set[int] = set()

    def collect(hwnd: int, _: object) -> bool:
        if win32gui.IsWindowVisible(hwnd):
            handles.add(int(hwnd))
        return True

    win32gui.EnumWindows(collect, None)
    return handles


__all__ = [
    "SUPPORTED_WECHAT_VERSIONS",
    "WechatUiaClient",
    "WechatUiaError",
    "WechatReferenceTargetError",
]
