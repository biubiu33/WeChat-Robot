from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from mewcode.chat import run_chat
from mewcode.config import load_profiles, select_profile
from mewcode.errors import MewCodeError
from mewcode.io import configure_utf8_stdio
from mewcode.providers.factory import create_provider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mewcode",
        description="MewCode 命令行 AI 对话助手。",
    )
    parser.add_argument(
        "--profile",
        required=True,
        help="要使用的 provider profile 名称。",
    )
    parser.add_argument(
        "--config",
        default="mewcode.yaml",
        help="配置文件路径，默认 mewcode.yaml。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    try:
        profiles = load_profiles(Path(args.config))
        profile = select_profile(profiles, args.profile)
        provider = create_provider(profile)
        return run_chat(provider, profile.name)
    except MewCodeError as exc:
        sys.stderr.write(f"错误：{exc}\n")
        sys.stderr.flush()
        return 1
