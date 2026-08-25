"""会话历史摘要。"""

from __future__ import annotations

from mewcode.llm import Message, Provider
from mewcode.llm.generation import generate_text


SUMMARY_SYSTEM = "你是会话摘要器。禁止工具调用。先在内部分析，再只输出正式摘要。"
SECTIONS = (
    "主要请求和意图",
    "关键技术概念",
    "文件和代码段",
    "错误和修复",
    "问题解决过程",
    "所有用户消息",
    "待办任务",
    "当前工作",
    "可能的下一步",
)


async def summarize(provider: Provider, messages: list[Message]) -> str:
    history = "\n".join(
        f"[{message.role}] {_summary_content(message)}" for message in messages
    )
    headings = "\n".join(f"## {section}" for section in SECTIONS)
    prompt = (
        "请总结以下早期会话。正式输出必须包含下列九个 Markdown 标题；"
        "‘所有用户消息’必须逐字保留用户原话，‘当前工作’必须最详细。"
        "不要调用工具，不要输出分析草稿。\n"
        f"{headings}\n\n会话：\n{history}"
    )
    result = await generate_text(provider, system=SUMMARY_SYSTEM, prompt=prompt)
    missing = [section for section in SECTIONS if f"## {section}" not in result]
    if missing:
        raise ValueError(f"摘要缺少固定段落: {', '.join(missing)}")
    return result


def _summary_content(message: Message) -> str:
    if message.content:
        return message.content
    if message.images:
        return "[好友发送了图片]"
    return ""
