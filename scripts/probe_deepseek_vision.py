from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

from PIL import Image

from mewcode.config import discover_config_path, load


MODEL = "deepseek-v4-flash-vision-exp"


def _config_path() -> Path:
    local = Path.cwd() / ".mewcode" / "config.yaml"
    return local if local.is_file() else discover_config_path().path


def _image_url() -> str:
    import base64

    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


async def _probe() -> int:
    import openai

    config = load(str(_config_path()))
    provider = next(
        (
            item
            for item in config.providers
            if item.name == "openai" and item.protocol == "openai"
        ),
        None,
    )
    if provider is None or provider.model != MODEL:
        print(f"model={provider.model if provider else 'missing'} ok=false")
        return 1
    client = openai.AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url)
    content = [
        {"type": "text", "text": "只回答图片的主要颜色。"},
        {"type": "image_url", "image_url": {"url": _image_url(), "detail": "original"}},
    ]

    text_chunks = 0
    text_chars = 0
    usage_seen = False
    stream = await client.chat.completions.create(
        model=provider.model,
        messages=[{"role": "user", "content": content}],
        stream=True,
        stream_options={"include_usage": True},
    )
    async for chunk in stream:
        if chunk.usage is not None:
            usage_seen = True
        if chunk.choices and isinstance(chunk.choices[0].delta.content, str):
            delta = chunk.choices[0].delta.content
            if delta:
                text_chunks += 1
                text_chars += len(delta)

    buffers: dict[int, dict[str, str]] = {}
    tool_deltas = 0
    tool_stream = await client.chat.completions.create(
        model=provider.model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "使用工具报告这张图的主要颜色。"},
                    content[1],
                ],
            }
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "inspect_image",
                    "description": "报告图片的主要颜色",
                    "parameters": {
                        "type": "object",
                        "properties": {"dominant_color": {"type": "string"}},
                        "required": ["dominant_color"],
                    },
                },
            }
        ],
        tool_choice="auto",
        stream=True,
    )
    async for chunk in tool_stream:
        if not chunk.choices:
            continue
        for item in chunk.choices[0].delta.tool_calls or []:
            tool_deltas += 1
            index = int(item.index)
            buffer = buffers.setdefault(index, {"name": "", "arguments": ""})
            if item.function is not None:
                buffer["name"] += item.function.name or ""
                buffer["arguments"] += item.function.arguments or ""
    tool_ok = any(
        value["name"] == "inspect_image"
        and isinstance(json.loads(value["arguments"] or "{}"), dict)
        and bool(json.loads(value["arguments"] or "{}").get("dominant_color"))
        for value in buffers.values()
    )
    text_ok = text_chunks > 0 and text_chars > 0
    print(
        f"model={provider.model} text_stream={str(text_ok).lower()} "
        f"usage={str(usage_seen).lower()} tool_calls={str(tool_ok).lower()} "
        f"text_chunks={text_chunks} text_chars={text_chars} tool_deltas={tool_deltas}"
    )
    return 0 if text_ok and usage_seen and tool_ok else 1


def main() -> None:
    raise SystemExit(asyncio.run(_probe()))


if __name__ == "__main__":
    main()
