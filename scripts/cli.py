#!/usr/bin/env python3
"""可研编写技能 CLI 入口：python scripts/cli.py <command> [options]

全部实现位于同目录 keyan/ 包内；本文件只负责把包目录加入 sys.path。
所有命令输出单行 JSON；退出码 0=ok/完成，2=partial/待补，3=conflict，1=error。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from keyan.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
