from __future__ import annotations


class MewCodeError(Exception):
    """MewCode 可预期错误的基类。"""


class ConfigError(MewCodeError):
    """配置读取或校验失败。"""


class ProviderError(MewCodeError):
    """LLM Provider 请求或响应失败。"""


class StreamProtocolError(ProviderError):
    """流式协议解析失败。"""
