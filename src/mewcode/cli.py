from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mewcode import __version__
from mewcode.command import new_default_command_registry
from mewcode.config import ConfigError, discover_config_path, load
from mewcode.hook import HookEngine
from mewcode.mcp import load_config as load_mcp_config
from mewcode.mcp import new_manager
from mewcode.memory import InstructionLoader, MemoryManager
from mewcode.permission import new_engine
from mewcode.session.paths import ensure_project_layout
from mewcode.session.repository import SessionRepository
from mewcode.skill import SkillCatalog, SkillRuntime
from mewcode.subagent import AgentCatalog
from mewcode.tool import new_default_registry


async def _run_app(
    providers: object,
    root: Path,
    enable_subagent_background: bool = True,
) -> None:
    command_registry = new_default_command_registry()
    registry = new_default_registry()
    manager = await new_manager(load_mcp_config(), version=__version__)
    try:
        for mcp_tool in manager.tools():
            registry.register(mcp_tool)

        skill_runtime = SkillRuntime(SkillCatalog.load(root), registry.ordinary_names())
        agent_catalog = AgentCatalog.load(root)

        engine, engine_error = new_engine(root)
        if engine_error is not None:
            print(f"权限引擎降级: {engine_error}", file=sys.stderr)
        hook_engine = HookEngine.load(root)

        ensure_project_layout(root)
        instructions = InstructionLoader(root).load_once()
        memory_manager = MemoryManager(root)
        session_repository = SessionRepository(root)
        cleanup_task = asyncio.create_task(
            asyncio.to_thread(session_repository.cleanup_expired)
        )

        from mewcode.tui.app import MewCodeApp

        app = MewCodeApp(
            providers,
            version=__version__,
            registry=registry,
            command_registry=command_registry,
            engine=engine,
            root=root,
            instructions=instructions,
            memory_manager=memory_manager,
            session_repository=session_repository,
            skill_runtime=skill_runtime,
            hook_engine=hook_engine,
            agent_catalog=agent_catalog,
            enable_subagent_background=enable_subagent_background,
        )
        await app.run_async()
        await asyncio.gather(cleanup_task, return_exceptions=True)
    finally:
        await manager.close()


def main() -> None:
    try:
        config_path = discover_config_path().path
        cfg = load(str(config_path))
        asyncio.run(
            _run_app(
                cfg.providers,
                Path.cwd(),
                cfg.enable_subagent_background,
            )
        )
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        raise SystemExit(0) from None
    except Exception as exc:
        print(f"运行错误: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
