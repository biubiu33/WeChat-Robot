from __future__ import annotations

from mewcode.errors import ProviderError
from mewcode.models import ProviderProfile
from mewcode.providers.anthropic import AnthropicProvider
from mewcode.providers.base import ChatProvider
from mewcode.providers.openai import OpenAIProvider


def create_provider(profile: ProviderProfile) -> ChatProvider:
    if profile.protocol == "openai":
        return OpenAIProvider(profile)
    if profile.protocol == "anthropic":
        return AnthropicProvider(profile)
    raise ProviderError(f"不支持的 Provider 协议：{profile.protocol}")
