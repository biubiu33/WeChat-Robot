from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from mewcode.config import ConfigError, discover_config_path, load

from .bot import WechatBot
from .config import parse_wechat_config
from .runtime import WechatAgentRuntime
from .store import WechatStateStore
from .uia_client import SUPPORTED_WECHAT_VERSION, WechatUiaClient, WechatUiaError
from .uia_driver import WechatUiaDriver


def main() -> None:
    parser = argparse.ArgumentParser(description="MewCode 本地微信聊天机器人")
    parser.add_argument(
        "--probe",
        action="store_true",
        help=f"只读输出微信 {SUPPORTED_WECHAT_VERSION} 必要 UIA 控件，不启动机器人",
    )
    args = parser.parse_args()
    try:
        if os.name != "nt":
            raise ConfigError("微信机器人仅支持 Windows")
        if args.probe:
            WechatUiaClient().probe()
            return

        config_path = discover_config_path().path
        project_config = load(str(config_path))
        if project_config.wechat is None:
            raise ConfigError("未配置顶层 wechat 对象")
        wechat_config = parse_wechat_config(
            project_config.wechat,
            {provider.name for provider in project_config.providers},
        )
        if not wechat_config.enabled:
            raise ConfigError("wechat.enabled 为 false，微信机器人未启用")
        provider_config = next(
            provider
            for provider in project_config.providers
            if provider.name == wechat_config.provider
        )
        logging.basicConfig(
            level=getattr(logging, wechat_config.log_level),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        root = Path.cwd()
        store = WechatStateStore(root)
        client = WechatUiaClient()
        driver = WechatUiaDriver(
            client,
            allowed_contacts=wechat_config.allowed_contacts,
        )
        runtime = WechatAgentRuntime(
            root,
            provider_config,
            wechat_config,
            store,
        )
        asyncio.run(WechatBot(wechat_config, driver, runtime, store).run())
    except (ConfigError, WechatUiaError) as exc:
        print(f"微信机器人配置错误: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        raise SystemExit(0) from None
    except Exception as exc:
        print(f"微信机器人运行错误: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
