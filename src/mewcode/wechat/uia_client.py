from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any

from .models import ConversationRow, VisibleMessage


SUPPORTED_WECHAT_VERSION = "4.1.12.55"
MAIN_WINDOW_CLASS = "mmui::MainWindow"
SESSION_LIST_ID = "session_list"
MESSAGE_LIST_ID = "chat_message_list"
INPUT_ID = "chat_input_field"
INPUT_CLASS = "mmui::ChatInputField"
SEARCH_EDIT_CLASS = "mmui::XValidatorTextEdit"
SEARCH_RESULT_CLASS = "mmui::SearchContentCellView"
SEARCH_ITEM_PREFIX = "search_item_"
CHAT_NAME_ID_SUFFIX = "current_chat_name_label"
CHAT_COUNT_ID_SUFFIX = "current_chat_count_label"
SESSION_ITEM_PREFIX = "session_item_"
UNREAD_RE = re.compile(r"\[(\d+)条\]")


class WechatUiaError(RuntimeError):
    pass


class WechatUiaClient:
    def __init__(self, *, expected_version: str = SUPPORTED_WECHAT_VERSION) -> None:
        try:
            import uiautomation as auto
        except ImportError as exc:
            raise WechatUiaError(
                "缺少 uiautomation，请安装 MewCode 的 wechat 可选依赖"
            ) from exc
        self._auto = auto
        self._expected_version = expected_version
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

    def visible_private_conversations(self) -> list[ConversationRow]:
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
                unread_count = int(unread_match.group(1)) if unread_match else 0
                signature = hashlib.sha256(raw_name.encode("utf-8")).hexdigest()
                rows.append(
                    ConversationRow(
                        key=":".join(map(str, runtime_id)) or name,
                        name=name,
                        runtime_id=runtime_id,
                        signature=signature,
                        unread_count=unread_count,
                    )
                )
            return rows

    def focus_conversation(self, row: ConversationRow) -> None:
        with self._thread_context():
            if self.current_conversation_name() == row.name:
                return
            window = self._main_window()
            automation_id = f"{SESSION_ITEM_PREFIX}{row.name}"
            matches = self._find_all(window, automation_id=automation_id)
            if len(matches) != 1:
                raise WechatUiaError(
                    f"无法唯一定位微信会话 {row.name!r}，匹配到 {len(matches)} 项"
                )
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

    def visible_text_messages(self, row: ConversationRow) -> list[VisibleMessage]:
        with self._thread_context():
            if self.current_conversation_name() != row.name:
                raise WechatUiaError("读取消息前目标会话已变化")
            if not self.current_conversation_is_private():
                return []
            window = self._main_window()
            message_list = self._find_unique(window, automation_id=MESSAGE_LIST_ID)
            messages: list[VisibleMessage] = []
            for control in message_list.GetChildren():
                if control.ClassName != "mmui::ChatTextItemView":
                    continue
                text = (control.Name or "").strip()
                if not text:
                    continue
                runtime_id = tuple(
                    int(value) for value in (control.GetRuntimeId() or ())
                )
                messages.append(
                    VisibleMessage(
                        key=":".join(map(str, runtime_id)) or text,
                        conversation_key=row.key,
                        text=text,
                        incoming=True,
                        sender_name=row.name,
                    )
                )
            return messages

    def validate_target(self, conversation_name: str) -> bool:
        with self._thread_context():
            return (
                self.current_conversation_name() == conversation_name
                and self.current_conversation_is_private()
            )

    def send_text(self, row: ConversationRow, text: str) -> None:
        with self._thread_context():
            if not text:
                return
            self.focus_conversation(row)
            if not self.validate_target(row.name):
                raise WechatUiaError("发送前无法确认原微信会话")
            window = self._main_window()
            input_control = self._find_unique(window, automation_id=INPUT_ID)
            value = input_control.GetValuePattern()
            if value is None:
                raise WechatUiaError("微信输入框不支持 ValuePattern")
            if value.Value:
                raise WechatUiaError("微信输入框存在未发送内容，已拒绝覆盖")
            value.SetValue(text)
            if not self.validate_target(row.name):
                value.SetValue("")
                raise WechatUiaError("写入后微信目标会话发生变化，已取消发送")
            self._send_with_enter(input_control, value, row.name, text)

    def _open_conversation_with_search(
        self,
        window: Any,
        conversation_name: str,
        *,
        timeout_seconds: float = 2.0,
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

        result_id = f"{SEARCH_ITEM_PREFIX}{conversation_name}"
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
                for control in self._find_all(
                    self._main_window(), automation_id=result_id
                )
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

        self._auto.SendKeys("{Enter}", waitTime=0.3)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.current_conversation_name() == conversation_name:
                return
            time.sleep(0.05)
        self._dismiss_search()
        raise WechatUiaError(f"切换到微信会话 {conversation_name!r} 超时")

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
    ) -> None:
        input_control.SetFocus()
        focused = self._auto.GetFocusedControl()
        if (
            focused is None
            or focused.AutomationId != INPUT_ID
            or focused.ClassName != INPUT_CLASS
            or value.Value != text
            or not self.validate_target(conversation_name)
        ):
            if value.Value == text:
                value.SetValue("")
            raise WechatUiaError("按 Enter 前无法确认微信输入框和目标会话")

        self._auto.SendKeys("{Enter}", waitTime=0.2)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not value.Value:
                if not self.validate_target(conversation_name):
                    raise WechatUiaError("发送后微信目标会话发生变化")
                return
            time.sleep(0.05)
        if not value.Value:
            return
        if value.Value.rstrip("\r\n") == text:
            value.SetValue("")
        raise WechatUiaError("按 Enter 后微信输入框未清空，消息可能未发送")

    def _dismiss_search(self) -> None:
        focused = self._auto.GetFocusedControl()
        if focused is not None and focused.ClassName == SEARCH_EDIT_CLASS:
            self._auto.SendKeys("{Esc}", waitTime=0.1)

    @contextmanager
    def _thread_context(self) -> Iterable[None]:
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
        windows = [
            control
            for control in self._auto.GetRootControl().GetChildren()
            if control.ClassName == MAIN_WINDOW_CLASS
        ]
        if len(windows) != 1:
            raise WechatUiaError(
                f"需要且只允许一个微信主窗口，当前找到 {len(windows)} 个"
            )
        window = windows[0]
        hwnd = int(window.NativeWindowHandle)
        if hwnd != self._validated_hwnd:
            actual = self._wechat_version(window)
            if actual != self._expected_version:
                raise WechatUiaError(
                    f"仅支持微信 {self._expected_version}，当前版本为 {actual}"
                )
            self._validated_hwnd = hwnd
        return window

    def _wechat_version(self, window: Any) -> str:
        try:
            import win32api
            import win32con
            import win32process

            handle = win32api.OpenProcess(
                win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                False,
                int(window.ProcessId),
            )
            try:
                path = win32process.GetModuleFileNameEx(handle, 0)
            finally:
                win32api.CloseHandle(handle)
            info = win32api.GetFileVersionInfo(path, "\\")
            ms, ls = info["FileVersionMS"], info["FileVersionLS"]
            return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
        except Exception as exc:
            raise WechatUiaError(f"无法读取微信客户端版本: {exc}") from exc

    def _conversation_name(self, control: Any, raw_name: str) -> str:
        automation_id = control.AutomationId or ""
        if automation_id.startswith(SESSION_ITEM_PREFIX):
            return automation_id.removeprefix(SESSION_ITEM_PREFIX).strip()
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


__all__ = [
    "SUPPORTED_WECHAT_VERSION",
    "WechatUiaClient",
    "WechatUiaError",
]
