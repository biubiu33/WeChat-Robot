from __future__ import annotations

import ctypes
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterable


HSHELL_FLASH = 0x8006


class WindowsShellHook:
    """Wake the observer when an allowed WeChat window flashes."""

    def __init__(
        self,
        allowed_process_ids: Callable[[], Iterable[int]],
        debounce_seconds: float = 0.25,
    ) -> None:
        self._allowed_process_ids = allowed_process_ids
        self._debounce_seconds = max(0.0, debounce_seconds)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._hwnd = 0
        self._last_target = 0
        self._last_signal_at = 0.0
        self.error = ""

    @property
    def available(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self.error)

    def start(self) -> bool:
        if os.name != "nt":
            self.error = "Windows Shell Hook 仅支持 Windows"
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self.error = ""
        self._thread = threading.Thread(
            target=self._message_loop,
            name="mewcode-wechat-shell-hook",
            daemon=True,
        )
        self._thread.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not self._hwnd and not self.error:
            time.sleep(0.01)
        return self.available

    def wait(self, timeout: float) -> bool:
        signaled = self._wake.wait(max(0.0, timeout))
        self._wake.clear()
        return signaled

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._hwnd:
            try:
                import win32con
                import win32gui

                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    def notify_for_tests(self, process_id: int, hwnd: int = 1) -> None:
        if process_id in {int(value) for value in self._allowed_process_ids()}:
            self._accept(hwnd)

    def _accept(self, hwnd: int) -> None:
        now = time.monotonic()
        if (
            hwnd == self._last_target
            and now - self._last_signal_at < self._debounce_seconds
        ):
            return
        self._last_target = hwnd
        self._last_signal_at = now
        self._wake.set()

    def _message_loop(self) -> None:
        try:
            import win32api
            import win32con
            import win32gui
            import win32process

            shell_message = ctypes.windll.user32.RegisterWindowMessageW("SHELLHOOK")
            class_name = f"MewCodeWechatHook_{uuid.uuid4().hex}"

            def wnd_proc(hwnd: int, message: int, wparam: int, lparam: int) -> int:
                if message == shell_message and int(wparam) == HSHELL_FLASH:
                    target = int(lparam or 0)
                    try:
                        _, process_id = win32process.GetWindowThreadProcessId(target)
                    except Exception:
                        process_id = 0
                    allowed = {int(value) for value in self._allowed_process_ids()}
                    if process_id in allowed:
                        self._accept(target)
                    return 0
                if message == win32con.WM_CLOSE:
                    win32gui.DestroyWindow(hwnd)
                    return 0
                if message == win32con.WM_DESTROY:
                    win32gui.PostQuitMessage(0)
                    return 0
                return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

            window_class = win32gui.WNDCLASS()
            window_class.hInstance = win32api.GetModuleHandle(None)
            window_class.lpszClassName = class_name
            window_class.lpfnWndProc = wnd_proc
            atom = win32gui.RegisterClass(window_class)
            hwnd = win32gui.CreateWindowEx(
                0,
                atom,
                class_name,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                window_class.hInstance,
                None,
            )
            self._hwnd = int(hwnd)
            if not ctypes.windll.user32.RegisterShellHookWindow(hwnd):
                raise ctypes.WinError()
            while not self._stop.is_set():
                win32gui.PumpWaitingMessages()
                self._stop.wait(0.02)
            ctypes.windll.user32.DeregisterShellHookWindow(hwnd)
            if win32gui.IsWindow(hwnd):
                win32gui.DestroyWindow(hwnd)
            win32gui.UnregisterClass(class_name, window_class.hInstance)
        except Exception as exc:
            self.error = str(exc)
            self._wake.set()
        finally:
            self._hwnd = 0


__all__ = ["WindowsShellHook"]
