from __future__ import annotations

import sys
from pathlib import Path

from mewcode import __version__
from mewcode.config import ConfigError, discover_config_path, load
from mewcode.permission import new_engine
from mewcode.tool import new_default_registry


def main() -> None:
    try:
        config_path = discover_config_path().path
        cfg = load(str(config_path))
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    engine, engine_error = new_engine(Path.cwd())
    if engine_error is not None:
        print(f"权限引擎降级: {engine_error}", file=sys.stderr)

    try:
        from mewcode.tui.app import MewCodeApp

        MewCodeApp(
            cfg.providers,
            version=__version__,
            registry=new_default_registry(),
            engine=engine,
        ).run()
    except KeyboardInterrupt:
        raise SystemExit(0) from None
    except Exception as exc:
        print(f"运行错误: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
