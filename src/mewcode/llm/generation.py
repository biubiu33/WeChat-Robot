"""无工具的短文本生成辅助函数。"""

from __future__ import annotations

from . import Message, Provider, Request, System


class GenerationError(RuntimeError):
    """后台生成没有得到可安全使用的文本。"""


async def generate_text(provider: Provider, *, system: str, prompt: str) -> str:
    """使用既有流式 Provider 完成一次禁止工具调用的文本请求。"""
    request = Request(
        messages=[Message(role="user", content=prompt)],
        system=System(stable=system),
    )
    parts: list[str] = []
    async for event in provider.stream(request):
        if event.err is not None:
            raise GenerationError(provider.redact(str(event.err))) from event.err
        if event.tool_calls:
            raise GenerationError("后台生成请求不允许工具调用")
        if event.text:
            parts.append(event.text)

    text = "".join(parts).strip()
    if not text:
        raise GenerationError("后台生成请求未返回文本")
    return text


__all__ = ["GenerationError", "generate_text"]
