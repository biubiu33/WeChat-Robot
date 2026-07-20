from __future__ import annotations

from typing import Final

from mewcode.permission import Mode
from mewcode.prompt import EXECUTE_DIRECTIVE

from .model import Command, CommandContext, CommandKind
from .registry import CommandRegistry


REVIEW_PROMPT: Final = (
    "请审查当前工作区中的代码变更，重点关注正确性、安全性、回归风险和测试缺口，"
    "并按严重程度报告问题。"
)


async def _help(context: CommandContext, argument: str) -> None:
    if not argument:
        commands = context.registry.public_commands()
        width = max(len(f"/{command.name}") for command in commands)
        lines = [
            f"/{command.name:<{width - 1}}  {command.description}"
            for command in commands
        ]
        await context.control.show_message("\n".join(lines))
        return
    parts = argument.split()
    if len(parts) != 1:
        await context.control.show_message("用法: /help [命令名]")
        return
    name = parts[0].removeprefix("/")
    command = context.registry.resolve(name)
    if command is None:
        await context.control.show_message(
            f"未知命令 /{name}。输入 /help 查看可用命令。"
        )
        return
    aliases = "、".join(f"/{alias}" for alias in command.aliases) or "无"
    argument_hint = command.argument_hint or "无"
    kind = {
        CommandKind.LOCAL: "纯本地",
        CommandKind.UI: "影响界面",
        CommandKind.PROMPT: "提示词",
    }[command.kind]
    await context.control.show_message(
        "\n".join(
            (
                f"名称: /{command.name}",
                f"别名: {aliases}",
                f"类型: {kind}",
                f"描述: {command.description}",
                f"用法: {command.usage}",
                f"参数: {argument_hint}",
            )
        )
    )


async def _status(context: CommandContext, _: str) -> None:
    status = context.control.status_snapshot()
    await context.control.show_message(
        "\n".join(
            (
                f"权限模式: {status.mode}",
                f"累计 Token: input={status.input_tokens}, output={status.output_tokens}",
                f"可用工具数量: {status.tool_count}",
                f"已加载记忆条目数: {status.memory_count}",
                f"当前模型: {status.model}",
                f"当前工作目录: {status.working_directory}",
            )
        )
    )


async def _memory(context: CommandContext, _: str) -> None:
    memory = context.control.memory_snapshot()
    project = "\n".join(f"- {name}" for name in memory.project) or "- 无"
    user = "\n".join(f"- {name}" for name in memory.user) or "- 无"
    await context.control.show_message(f"项目层:\n{project}\n用户层:\n{user}")


async def _permission(context: CommandContext, _: str) -> None:
    await context.control.show_message(context.control.status_snapshot().mode)


async def _session(context: CommandContext, _: str) -> None:
    session = context.control.session_snapshot()
    if session is None:
        await context.control.show_message("当前尚未创建会话")
        return
    await context.control.show_message(
        f"Session ID: {session.session_id}\n档案路径: {session.archive_path}"
    )


async def _exit(context: CommandContext, _: str) -> None:
    await context.control.exit_app()


async def _plan(context: CommandContext, _: str) -> None:
    context.control.set_mode(Mode.PLAN)
    context.control.refresh_status()
    await context.control.show_message("已进入计划模式（只允许只读工具）")


async def _do(context: CommandContext, _: str) -> None:
    context.control.set_mode(Mode.DEFAULT)
    context.control.refresh_status()
    await context.control.send_user_message(EXECUTE_DIRECTIVE)


async def _compact(context: CommandContext, _: str) -> None:
    await context.control.compact_context()


async def _resume(context: CommandContext, _: str) -> None:
    await context.control.resume_session()


async def _clear(context: CommandContext, _: str) -> None:
    await context.control.clear_session()


async def _review(context: CommandContext, _: str) -> None:
    await context.control.send_user_message(REVIEW_PROMPT)


def new_default_command_registry() -> CommandRegistry:
    registry = CommandRegistry()
    commands = (
        Command(
            "exit",
            (),
            "退出 MewCode",
            "/exit",
            CommandKind.UI,
            _exit,
        ),
        Command(
            "plan",
            (),
            "进入计划模式",
            "/plan",
            CommandKind.UI,
            _plan,
        ),
        Command(
            "do",
            (),
            "退出计划模式并执行计划",
            "/do",
            CommandKind.PROMPT,
            _do,
        ),
        Command(
            "compact",
            (),
            "手动压缩当前上下文",
            "/compact",
            CommandKind.UI,
            _compact,
        ),
        Command(
            "resume",
            (),
            "打开历史会话列表",
            "/resume",
            CommandKind.UI,
            _resume,
        ),
        Command(
            "clear",
            ("c",),
            "结束当前会话并开启新会话",
            "/clear",
            CommandKind.UI,
            _clear,
        ),
        Command(
            "help",
            ("h",),
            "显示命令列表或命令详情",
            "/help [命令名]",
            CommandKind.LOCAL,
            _help,
            argument_hint="[命令名]",
        ),
        Command(
            "status",
            (),
            "显示当前运行状态",
            "/status",
            CommandKind.LOCAL,
            _status,
        ),
        Command(
            "memory",
            (),
            "列出当前加载的记忆文件",
            "/memory",
            CommandKind.LOCAL,
            _memory,
        ),
        Command(
            "permission",
            (),
            "显示当前权限模式",
            "/permission",
            CommandKind.LOCAL,
            _permission,
        ),
        Command(
            "session",
            (),
            "显示当前会话标识",
            "/session",
            CommandKind.LOCAL,
            _session,
        ),
        Command(
            "review",
            (),
            "请求 AI 审查当前代码变更",
            "/review",
            CommandKind.PROMPT,
            _review,
        ),
    )
    for command in commands:
        registry.register(command)
    return registry
