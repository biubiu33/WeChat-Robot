from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import os
import signal
import subprocess
from typing import Any

from . import Result, error_result, parse_arguments, require_string, truncate

MAX_OUTPUT_CHARS = 30_000


class BashTool:
    def name(self) -> str:
        return "bash"

    def description(self) -> str:
        return "在 MewCode 启动目录执行 shell 命令，返回输出和退出码。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"}
            },
            "required": ["command"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        values, err = parse_arguments(args)
        if err:
            return err
        assert values is not None
        command, err = require_string(values, "command")
        if err:
            return err
        assert command is not None

        process: asyncio.subprocess.Process | None = None
        stdout_task: asyncio.Task[tuple[bytes, bool]] | None = None
        stderr_task: asyncio.Task[tuple[bytes, bool]] | None = None
        try:
            process_options: dict[str, Any]
            if os.name == "nt":
                process_options = {
                    "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
                }
            else:
                process_options = {"start_new_session": True}
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **process_options,
            )
            assert process.stdout is not None and process.stderr is not None
            stdout_task = asyncio.create_task(_read_limited(process.stdout))
            stderr_task = asyncio.create_task(_read_limited(process.stderr))
            (stdout_bytes, stdout_truncated), (stderr_bytes, stderr_truncated), _ = (
                await asyncio.gather(
                    stdout_task,
                    stderr_task,
                    process.wait(),
                )
            )
        except asyncio.CancelledError:
            if process is not None:
                await _terminate_process_tree(process)
            for task in (stdout_task, stderr_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (stdout_task, stderr_task) if task is not None),
                return_exceptions=True,
            )
            raise
        except OSError as exc:
            return error_result("command_error", f"无法启动命令: {exc}")

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if stdout_truncated:
            stdout += "\n[truncated]"
        if stderr_truncated:
            stderr += "\n[truncated]"
        combined = (
            f"stdout:\n{stdout or '(empty)'}\n"
            f"stderr:\n{stderr or '(empty)'}\n"
            f"exit_code: {process.returncode}"
        )
        combined, _ = truncate(combined, MAX_OUTPUT_CHARS)
        if process.returncode != 0:
            return Result(content=combined, is_error=True)
        return Result(content=combined)


async def _read_limited(
    stream: asyncio.StreamReader,
    limit: int = MAX_OUTPUT_CHARS,
) -> tuple[bytes, bool]:
    collected = bytearray()
    truncated = False
    while chunk := await stream.read(8_192):
        remaining = limit - len(collected)
        if remaining > 0:
            collected.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
    return bytes(collected), truncated


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    if os.name == "nt":
        await asyncio.to_thread(_terminate_windows_process_tree, process.pid)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(process.wait(), timeout=1)
    except TimeoutError:
        process.kill()
        await process.wait()


def _terminate_windows_process_tree(root_pid: int) -> None:
    process_ids = _windows_descendant_process_ids(root_pid)
    for process_id in reversed(process_ids):
        _terminate_windows_process(process_id)
    _terminate_windows_process(root_pid)


def _windows_descendant_process_ids(root_pid: int) -> list[int]:
    snapshot_process = 0x00000002
    invalid_handle_value = ctypes.c_void_p(-1).value

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.wintypes.DWORD),
            ("cntUsage", ctypes.wintypes.DWORD),
            ("th32ProcessID", ctypes.wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.wintypes.DWORD),
            ("cntThreads", ctypes.wintypes.DWORD),
            ("th32ParentProcessID", ctypes.wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("szExeFile", ctypes.wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(snapshot_process, 0)
    if snapshot == invalid_handle_value:
        return []

    pairs: list[tuple[int, int]] = []
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            pairs.append((entry.th32ProcessID, entry.th32ParentProcessID))
            has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    family = {root_pid}
    descendants: list[int] = []
    changed = True
    while changed:
        changed = False
        for process_id, parent_id in pairs:
            if parent_id in family and process_id not in family:
                family.add(process_id)
                descendants.append(process_id)
                changed = True
    return descendants


def _terminate_windows_process(process_id: int) -> None:
    process_terminate = 0x0001
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
    handle = kernel32.OpenProcess(process_terminate, False, process_id)
    if not handle:
        return
    try:
        kernel32.TerminateProcess(handle, 1)
    finally:
        kernel32.CloseHandle(handle)
