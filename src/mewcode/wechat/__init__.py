"""Windows WeChat desktop adapter for MewCode."""

from .config import WechatConfig, parse_wechat_config
from .models import WechatDesktopEvent

__all__ = ["WechatConfig", "WechatDesktopEvent", "parse_wechat_config"]
