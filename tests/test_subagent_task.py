from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mewcode.agent import Completion
from mewcode.subagent import TaskManager, TaskStatus


class ControlledAgent:
    def __init__(self, results: list[Completion], *, wait: bool = False) -> None:
        self.results = results
        self.wait = wait
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[str] = []

    async def run_to_completion(self, conversation, task, mode, cancel) -> Completion:
        self.calls.append(task)
        self.started.set()
        if self.wait:
            released = asyncio.create_task(self.release.wait())
            cancelled = asyncio.create_task(cancel.wait())
            done, _ = await asyncio.wait(
                {released, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
            for pending in {released, cancelled} - done:
                pending.cancel()
            if cancelled in done:
                return Completion("cancelled", cancelled=True)
        return self.results.pop(0)


class Host:
    async def run_inline(self, runtime, task, cancel):
        return await runtime.agent.run_to_completion(
            runtime.conversation, task, runtime.mode, cancel
        )


def runtime(agent: ControlledAgent):
    return SimpleNamespace(
        agent=agent,
        conversation=object(),
        mode=object(),
        definition=SimpleNamespace(name="worker"),
    )


async def wait_terminal(manager: TaskManager, task_id: str):
    for _ in range(20):
        task = manager.get(task_id)
        assert task is not None
        if task.status is not TaskStatus.RUNNING:
            return task
        await asyncio.sleep(0)
    raise AssertionError("task did not reach terminal state")


def test_background_launch_retains_result_and_emits_one_shot_notification() -> None:
    async def scenario() -> None:
        agent = ControlledAgent([Completion("finished")])
        manager = TaskManager(Host())
        task = await manager.launch(runtime(agent), "do work", "named")
        terminal = await wait_terminal(manager, task.id)

        assert terminal.status is TaskStatus.COMPLETED
        assert terminal.result == "finished"
        notifications = manager.take_notifications()
        assert len(notifications) == 1
        assert "<task-notification>" in notifications[0]
        assert manager.take_notifications() == ()

    asyncio.run(scenario())


def test_timeout_detaches_the_same_running_child_without_restart() -> None:
    async def scenario() -> None:
        agent = ControlledAgent([Completion("finished")], wait=True)
        manager = TaskManager(Host())
        running = manager.start(runtime(agent), "long work", "long")
        await agent.started.wait()

        summary = await manager.await_or_detach(running, timeout=0.001)

        assert summary.status == TaskStatus.RUNNING.value
        assert agent.calls == ["long work"]
        agent.release.set()
        terminal = await wait_terminal(manager, summary.task_id)
        assert terminal.result == "finished"
        assert agent.calls == ["long work"]

    asyncio.run(scenario())


def test_stop_requests_cancellation_and_keeps_task_queryable() -> None:
    async def scenario() -> None:
        agent = ControlledAgent([Completion("unused")], wait=True)
        manager = TaskManager(Host())
        task = await manager.launch(runtime(agent), "long work")
        await agent.started.wait()

        assert manager.stop(task.id)
        terminal = await wait_terminal(manager, task.id)

        assert terminal.status is TaskStatus.CANCELLED
        assert manager.get(task.id) is terminal
        assert not manager.stop(task.id)

    asyncio.run(scenario())


def test_name_collision_keeps_old_id_and_send_reuses_completed_runtime() -> None:
    async def scenario() -> None:
        first_agent = ControlledAgent([Completion("old")])
        second_agent = ControlledAgent([Completion("new"), Completion("continued")])
        manager = TaskManager(Host())
        first = await manager.launch(runtime(first_agent), "old task", "same")
        await wait_terminal(manager, first.id)
        second = await manager.launch(runtime(second_agent), "new task", "same")
        await wait_terminal(manager, second.id)

        continued = await manager.send("same", "follow up")
        assert continued is not None and continued.id == second.id
        terminal = await wait_terminal(manager, second.id)

        assert manager.get(first.id) is not None
        assert terminal.result == "continued"
        assert second_agent.calls == ["new task", "follow up"]

    asyncio.run(scenario())
