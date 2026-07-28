"""Fixed-schema main-agent tools for child-agent execution and task control."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from mewcode.tool import Result, error_result, parse_arguments, require_string

from .model import LaunchRequest, TaskStatus
from .runtime import ModelUnavailableError, ParentContext, SubAgentError, SubAgentHost
from .task import BackgroundTask, RunningChild, TaskManager


FOREGROUND_TIMEOUT = 120.0


class AgentTool:
    read_only = True
    system = True

    def __init__(
        self,
        host: SubAgentHost,
        tasks: TaskManager,
        parent_context: Callable[[], ParentContext],
        *,
        enable_background: bool = True,
        foreground_timeout: float = FOREGROUND_TIMEOUT,
    ) -> None:
        self._host = host
        self._tasks = tasks
        self._parent_context = parent_context
        self._enable_background = enable_background
        self._foreground_timeout = foreground_timeout
        self._foreground: tuple[RunningChild, asyncio.Event] | None = None

    def name(self) -> str:
        return "Agent"

    def description(self) -> str:
        return "Delegate a focused task to an isolated defined or Forked sub-agent."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Task to complete"},
                "description": {"type": "string", "description": "Short task summary"},
                "subagent_type": {
                    "type": "string",
                    "description": "Defined role name; omit for a Fork",
                },
                "model": {
                    "type": "string",
                    "description": "Configured provider profile name",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "Return a task ID without waiting",
                },
                "name": {"type": "string", "description": "Optional task name"},
            },
            "required": ["prompt", "description"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        values, error = parse_arguments(args)
        if error is not None:
            return error
        assert values is not None
        prompt, error = require_string(values, "prompt")
        if error is not None:
            return error
        description, error = require_string(values, "description")
        if error is not None:
            return error
        optional, error = _optional_request_values(values)
        if error is not None:
            return error
        assert prompt is not None and description is not None and optional is not None
        request = LaunchRequest(prompt, description, **optional)
        forked = not bool(request.subagent_type)
        if forked and not self._enable_background:
            return error_result("background_disabled", "Fork sub-agents require background tasks")
        try:
            runtime = self._host.prepare(request, self._parent_context())
        except ModelUnavailableError as exc:
            return error_result("model_unavailable", str(exc))
        except SubAgentError as exc:
            return error_result("invalid_subagent", str(exc))

        background = forked or (
            self._enable_background
            and (request.run_in_background or runtime.definition.background)
        )
        if background:
            task = await self._tasks.launch(runtime, request.prompt, request.name)
            return _task_result(task, background=True)

        running = self._tasks.start(runtime, request.prompt, request.name)
        handoff = asyncio.Event()
        self._foreground = (running, handoff)
        try:
            summary = await self._tasks.await_or_detach(
                running, self._foreground_timeout, handoff
            )
        finally:
            if self._foreground is not None and self._foreground[0] is running:
                self._foreground = None
        if summary.task_id:
            task = self._tasks.get(summary.task_id)
            assert task is not None
            return _task_result(task, background=True)
        if summary.status == TaskStatus.COMPLETED.value:
            return Result(summary.result)
        return error_result("subagent_failed", summary.result or summary.status)

    def detach_foreground(self) -> BackgroundTask | None:
        if self._foreground is None:
            return None
        running, handoff = self._foreground
        task = self._tasks.detach(running)
        handoff.set()
        return task


class TaskListTool:
    read_only = True
    system = True

    def __init__(self, tasks: TaskManager) -> None:
        self._tasks = tasks

    def name(self) -> str:
        return "TaskList"

    def description(self) -> str:
        return "List in-process background sub-agent tasks."

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self, args: str) -> Result:
        _, error = parse_arguments(args)
        if error is not None:
            return error
        return Result(
            json.dumps(
                [_task_payload(task, include_result=False) for task in self._tasks.list()],
                ensure_ascii=False,
            )
        )


class TaskGetTool:
    read_only = True
    system = True

    def __init__(self, tasks: TaskManager) -> None:
        self._tasks = tasks

    def name(self) -> str:
        return "TaskGet"

    def description(self) -> str:
        return "Get a background sub-agent task by ID."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        values, error = parse_arguments(args)
        if error is not None:
            return error
        task_id, error = require_string(values or {}, "task_id")
        if error is not None:
            return error
        task = self._tasks.get(task_id or "")
        if task is None:
            return error_result("task_not_found", f"Unknown task: {task_id}")
        return Result(json.dumps(_task_payload(task), ensure_ascii=False))


class TaskStopTool:
    read_only = False
    system = True

    def __init__(self, tasks: TaskManager) -> None:
        self._tasks = tasks

    def name(self) -> str:
        return "TaskStop"

    def description(self) -> str:
        return "Request cancellation of a running background task."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        values, error = parse_arguments(args)
        if error is not None:
            return error
        task_id, error = require_string(values or {}, "task_id")
        if error is not None:
            return error
        if not self._tasks.stop(task_id or ""):
            return error_result("task_not_running", f"Task cannot be stopped: {task_id}")
        return Result(json.dumps({"task_id": task_id, "status": "cancelling"}))


class SendMessageTool:
    read_only = False
    system = True

    def __init__(self, tasks: TaskManager) -> None:
        self._tasks = tasks

    def name(self) -> str:
        return "SendMessage"

    def description(self) -> str:
        return "Continue a completed named background sub-agent with a new task."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["name", "message"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        values, error = parse_arguments(args)
        if error is not None:
            return error
        name, error = require_string(values or {}, "name")
        if error is not None:
            return error
        message, error = require_string(values or {}, "message")
        if error is not None:
            return error
        task = await self._tasks.send(name or "", message or "")
        if task is None:
            return error_result("task_not_available", f"No completed task named: {name}")
        return _task_result(task, background=True)


def _optional_request_values(
    values: dict[str, Any],
) -> tuple[dict[str, Any] | None, Result | None]:
    optional: dict[str, Any] = {}
    for key, target in (("subagent_type", "subagent_type"), ("model", "model_profile"), ("name", "name")):
        value = values.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            return None, error_result("invalid_arguments", f"Parameter {key} must be a string")
        optional[target] = value.strip() or None
    background = values.get("run_in_background", False)
    if not isinstance(background, bool):
        return None, error_result("invalid_arguments", "Parameter run_in_background must be a boolean")
    optional["run_in_background"] = background
    return optional, None


def _task_result(task: BackgroundTask, *, background: bool) -> Result:
    return Result(
        json.dumps(
            {**_task_payload(task, include_result=False), "background": background},
            ensure_ascii=False,
        )
    )


def _task_payload(task: BackgroundTask, *, include_result: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": task.id,
        "name": task.name,
        "status": task.status.value,
        "description": task.task_text,
        "usage": {
            "input_tokens": task.runtime.usage.input_tokens,
            "output_tokens": task.runtime.usage.output_tokens,
            "cache_write": task.runtime.usage.cache_write,
            "cache_read": task.runtime.usage.cache_read,
        },
    }
    if include_result:
        payload.update({"result": task.result, "error": task.error})
    return payload


def new_subagent_tools(
    host: SubAgentHost,
    tasks: TaskManager,
    parent_context: Callable[[], ParentContext],
    *,
    enable_background: bool = True,
) -> tuple[AgentTool, TaskListTool, TaskGetTool, TaskStopTool, SendMessageTool]:
    return (
        AgentTool(host, tasks, parent_context, enable_background=enable_background),
        TaskListTool(tasks),
        TaskGetTool(tasks),
        TaskStopTool(tasks),
        SendMessageTool(tasks),
    )


__all__ = [
    "AgentTool",
    "FOREGROUND_TIMEOUT",
    "SendMessageTool",
    "TaskGetTool",
    "TaskListTool",
    "TaskStopTool",
    "new_subagent_tools",
]
