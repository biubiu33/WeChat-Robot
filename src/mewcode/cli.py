from __future__ import annotations

import sys

from mewcode.config import ConfigError, discover_config_path, load


def main() -> None:
    try:
        config_path = discover_config_path().path
        cfg = load(str(config_path))
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        from mewcode.tui.app import MewCodeApp

        MewCodeApp(cfg.providers).run()
    except KeyboardInterrupt:
        raise SystemExit(0) from None
    except Exception as exc:
        print(f"运行错误: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
