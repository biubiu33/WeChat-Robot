"""用两轮真实请求观察 Provider 的提示缓存用量。"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from mewcode.agent import Agent
from mewcode.config import ConfigError, discover_config_path, load
from mewcode.conversation import Conversation
from mewcode.llm import new_provider
from mewcode.permission import Mode, new_engine
from mewcode.tool import new_default_registry


async def run(profile: str, first: str, second: str) -> None:
    try:
        config = load(str(discover_config_path().path))
    except ConfigError as exc:
        raise SystemExit(f"配置错误: {exc}") from exc

    selected = next((item for item in config.providers if item.name == profile), None)
    if selected is None:
        names = ", ".join(item.name for item in config.providers)
        raise SystemExit(f"未找到 profile: {profile}；可用值: {names}")

    engine, engine_error = new_engine(Path.cwd())
    if engine_error is not None:
        raise SystemExit(f"权限引擎初始化失败: {engine_error}")
    agent = Agent(
        new_provider(selected), new_default_registry(), version="smoke", engine=engine
    )
    conversation = Conversation()
    for index, text in enumerate((first, second), start=1):
        conversation.add_user(text)
        print(f"\n--- 第 {index} 轮 ---")
        async for event in agent.run(conversation, Mode.BYPASS):
            if event.text:
                print(event.text, end="", flush=True)
            if event.usage is not None:
                usage = event.usage
                print(
                    "\n[usage] "
                    f"input={usage.input} output={usage.output} "
                    f"cache_write={usage.cache_write} "
                    f"cache_read={usage.cache_read}"
                )
            if event.err is not None:
                print(f"\n[error] {event.err}")
            if event.notice:
                print(f"\n[notice] {event.notice}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MewCode 提示缓存 smoke 测试")
    parser.add_argument("--profile", required=True, help="配置文件中的 provider name")
    parser.add_argument("--first", default="你好，请简短介绍你自己。")
    parser.add_argument("--second", default="请再次简短介绍你自己。")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run(args.profile, args.first, args.second))
