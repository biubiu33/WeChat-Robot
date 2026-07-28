"""In-process lifecycle management for background child-agent tasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from mewcode.agent import Completion

from .model import TaskStatus, TaskSummary
from .runtime import ChildRuntime, SubAgentHost


@dataclass
class RunningChild:
    task_id: str
    runtime: ChildRuntime
    task_text: str
    name: str | None
    cancel: asyncio.Event
    runner: asyncio.Task[Completion]


@dataclass
class BackgroundTask:
    id: str
    name: str | None
    runtime: ChildRuntime
    task_text: str
    status: TaskStatus = TaskStatus.RUNNING
    result: str = ""
    error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tool_calls: int = 0
    running: RunningChild | None = None

    def summary(self) -> TaskSummary:
        return TaskSummary(self.id, self.status.value, self.result or self.error)


class TaskManager:
    """Retain child runtimes and terminal results until the host process exits."""

    def __init__(self, host: SubAgentHost) -> None:
        self._host = host
        self._tasks: dict[str, BackgroundTask] = {}
        self._names: dict[str, str] = {}
        self._notifications: list[str] = []

    def start(
        self, runtime: ChildRuntime, task: str, name: str | None = None, *, task_id: str | None = None
    ) -> RunningChild:
        cancel = asyncio.Event()
        identity = task_id or uuid4().hex
        runner = asyncio.create_task(self._host.run_inline(runtime, task, cancel))
        return RunningChild(identity, runtime, task, name, cancel, runner)

    async def launch(
        self, runtime: ChildRuntime, task: str, name: str | None = None
    ) -> BackgroundTask:
        return self.detach(self.start(runtime, task, name))

    async def await_or_detach(
        self,
        running: RunningChild,
        timeout: float,
        handoff: asyncio.Event | None = None,
    ) -> TaskSummary:
        if handoff is not None:
            requested = asyncio.create_task(handoff.wait())
            try:
                done, _ = await asyncio.wait(
                    {running.runner, requested},
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if requested in done:
                    return self.detach(running).summary()
                if running.runner in done:
                    return _completion_summary(running.runner.result())
                return self.detach(running).summary()
            finally:
                if not requested.done():
                    requested.cancel()
                await asyncio.gather(requested, return_exceptions=True)
        try:
            completion = await asyncio.wait_for(asyncio.shield(running.runner), timeout)
        except TimeoutError:
            return self.detach(running).summary()
        return _completion_summary(completion)

    def detach(self, running: RunningChild) -> BackgroundTask:
        existing = self._tasks.get(running.task_id)
        if existing is not None and existing.running is running:
            return existing
        if existing is None:
            task = BackgroundTask(
                id=running.task_id,
                name=running.name,
                runtime=running.runtime,
                task_text=running.task_text,
                running=running,
            )
            self._tasks[task.id] = task
        else:
            task = existing
            task.name = running.name
            task.runtime = running.runtime
            task.task_text = running.task_text
            task.status = TaskStatus.RUNNING
            task.result = ""
            task.error = ""
            task.running = running
            task.updated_at = datetime.now(timezone.utc)
        if task.name:
            self._names[task.name] = task.id
        running.runner.add_done_callback(
            lambda completed: asyncio.create_task(self._record_terminal(task, completed))
        )
        return task

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def list(self) -> tuple[BackgroundTask, ...]:
        return tuple(self._tasks.values())

    def stop(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status is not TaskStatus.RUNNING or task.running is None:
            return False
        task.running.cancel.set()
        return True

    async def send(self, name: str, message: str) -> BackgroundTask | None:
        task_id = self._names.get(name)
        task = self._tasks.get(task_id) if task_id else None
        if task is None or task.status is not TaskStatus.COMPLETED:
            return None
        return self.detach(self.start(task.runtime, message, task.name, task_id=task.id))

    def take_notifications(self) -> tuple[str, ...]:
        notifications = tuple(self._notifications)
        self._notifications.clear()
        return notifications

    async def close(self) -> None:
        running = [task.running for task in self._tasks.values() if task.running]
        for item in running:
            assert item is not None
            item.cancel.set()
        await asyncio.gather(
            *(item.runner for item in running if item is not None),
            return_exceptions=True,
        )

    async def _record_terminal(
        self, task: BackgroundTask, runner: asyncio.Task[Completion]
    ) -> None:
        try:
            completion = runner.result()
        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            task.error = "Task cancelled"
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = f"{type(exc).__name__}: {exc}"
        else:
            task.result = completion.text
            if completion.cancelled:
                task.status = TaskStatus.CANCELLED
            elif completion.error is not None or completion.limit_reached:
                task.status = TaskStatus.FAILED
                task.error = (
                    str(completion.error)
                    if completion.error is not None
                    else "Sub-agent reached its maximum turns"
                )
            else:
                task.status = TaskStatus.COMPLETED
        task.updated_at = datetime.now(timezone.utc)
        task.running = None
        self._notifications.append(_notification(task))


def _completion_summary(completion: Completion) -> TaskSummary:
    if completion.cancelled:
        return TaskSummary("", TaskStatus.CANCELLED.value, completion.text)
    if completion.error is not None or completion.limit_reached:
        return TaskSummary("", TaskStatus.FAILED.value, completion.text)
    return TaskSummary("", TaskStatus.COMPLETED.value, completion.text)


def _notification(task: BackgroundTask) -> str:
    detail = task.result or task.error or task.status.value
    return (
        "<task-notification>\n"
        f"Task {task.id} ({task.name or task.runtime.definition.name}) {task.status.value}.\n"
        f"Result: {detail}\n"
        "</task-notification>"
    )


__all__ = ["BackgroundTask", "RunningChild", "TaskManager"]
