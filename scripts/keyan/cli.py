#!/usr/bin/env python3
"""可研编写技能 CLI（包内实现；入口见 scripts/cli.py）。

用法：
  python scripts/cli.py <command> [options]

所有命令输出单行 JSON；退出码 0=ok/完成，2=partial/待补，3=conflict，1=error。
"""
import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):
        pass

from . import commands
from .scan import validate_role
from .jsonio import AppError, emit
from .workspace import WORKSPACE_ENV

COMMANDS = {
    "init": commands.cmd_init,
    "scan": commands.cmd_scan,
    "tree": commands.cmd_tree,
    "index": commands.cmd_index,
    "plan": commands.cmd_plan,
    "author": commands.cmd_author,
    "run": commands.cmd_run,
    "assemble": commands.cmd_assemble,
    "check": commands.cmd_check,
    "report": commands.cmd_report,
    "search": commands.cmd_search,
    "kb": commands.cmd_kb,
    "link": commands.cmd_link,
    "anchor": commands.cmd_anchor,
    "project-tree": commands.cmd_project_tree,
    "publish": commands.cmd_publish,
    "clean": commands.cmd_clean,
    "verify": commands.cmd_verify,
}


def _common(parser):
    parser.add_argument("--workspace", "-w", default=None,
                        help="工作区目录（默认 ./keyan-work，可用环境变量 %s 覆盖）" % WORKSPACE_ENV)
    parser.add_argument("--skill-root", default=None, help="技能根目录（含 references/）")


def build_parser():
    parser = argparse.ArgumentParser(prog="keyan", description="可研报告编写技能 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="建立工作区目录")
    _common(p)

    p = sub.add_parser("scan", help="扫描输入文件：目录树（到最小层级）+ Markdown 转换")
    _common(p)
    p.add_argument("--input", "-i", required=True, help="输入文件（建设方案/可研模板：.docx/.md/.txt）")
    p.add_argument("--role", type=validate_role, default="source",
                   help="source=建设方案，template=可研模板，material_01 等=其他用户材料")
    p.add_argument("--rebuild", action="store_true", help="忽略缓存重新解析")

    p = sub.add_parser("tree", help="查看/导出目录树")
    _common(p)
    p.add_argument("--role", type=validate_role, default=None)
    p.add_argument("--grep", default=None, help="按标题关键词过滤")
    p.add_argument("--level", type=int, default=None, help="只看某一层级")
    p.add_argument("--leaves", action="store_true", help="只看叶子节点（最小层级）")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--max-depth", type=int, default=None, help="导出 md 时的最大层级")
    p.add_argument("--output", default=None, help="导出目录树 md 到该路径")

    p = sub.add_parser("index", help="建立标题同名索引与候选映射")
    _common(p)
    p.add_argument("--refresh-cache", action="store_true", help="忽略缓存并重建路由结果")

    p = sub.add_parser("link", help="手工锚点：把模板节点钉到指定建设方案节点")
    _common(p)
    p.add_argument("--node", "-n", default=None, help="模板节点 key/编号/标题（多个用逗号分隔，配合 --remove）")
    p.add_argument("--source", default=None, help="建设方案节点 key/编号/标题")
    p.add_argument("--mode", choices=["copy", "migrate", "write"], default=None,
                   help="copy=整段直复；migrate=整段迁移后按规范补足（默认，标题不同名时）；write=以该节点为素材范围撰写")
    p.add_argument("--note", default="", help="锚点理由，写入 来源覆盖.json")
    p.add_argument("--remove", action="store_true", help="删除指定节点（或全部）的锚点")
    p.add_argument("--list", action="store_true", help="列出已有锚点")

    p = sub.add_parser("project-tree", help="按本次建设方案派生 5.6 的项目系统目录")
    _common(p)
    p.add_argument("--from", dest="source_scope", default=None,
                   help="建设方案的系统域编号；省略时仅在唯一高置信度域下自动选择")
    p.add_argument("--systems", default=None,
                   help="确认纳入 5.6 的直接子节点编号，逗号分隔；省略时只列候选，不落盘")

    p = sub.add_parser("anchor", help="自动锚点：保序最优分配把模板域对到建设方案域，低置信度交判读")
    _common(p)
    p.add_argument("--scope", "-s", default=None, help="模板域节点：5.6 / chapter_05_06 / 第五章第六节")
    p.add_argument("--from", dest="source_scope", default=None,
                   help="建设方案域节点：9（省略则自动挑选与模板域最合得来的来源域）")
    p.add_argument("--depth", type=int, default=2, help="向下派生层数（1=只对子级，2=对到孙级，默认 2）")
    p.add_argument("--exclude", default=None, help="不参与自动派生的模板节点 key，逗号分隔")
    p.add_argument("--dry-run", action="store_true", help="只算不落盘（仍打印结果）")
    p.add_argument("--review", action="store_true", help="只输出待判读清单（读已落盘的自动锚点）")
    p.add_argument("--apply", nargs="?", const="", default=None, metavar="判读.json",
                   help="应用判读结论后重算；省略路径用 match/锚点判读.json")
    p.add_argument("--limit", type=int, default=40, help="输出条目上限（默认 40）")

    p = sub.add_parser("plan", help="对 scope 内节点做来源路由，产出任务单")
    _common(p)
    p.add_argument("--scope", "-s", required=True, help="章节/小节：5 / 5.6 / chapter_05_06 / 第五章第六节 / all")
    p.add_argument("--node", action="store_true", help="只处理该节点本身（默认自动展开到下一层）")
    p.add_argument("--deep", action="store_true", help="展开整棵子树到最小层级")
    p.add_argument("--top-k", type=int, default=5, help="语义候选/知识库条数")
    p.add_argument("--kb", action="store_true", default=True, help="查询知识库（默认开）")
    p.add_argument("--no-kb", action="store_true", help="关闭知识库查询")
    p.add_argument("--allow-web", action="store_true", help="允许网络检索（默认关闭）")
    p.add_argument("--local-search", action="store_true", default=True, help="本地原文检索")
    p.add_argument("--ignore-claims", action="store_true",
                   help="忽略同名归属仲裁（所有同名候选都按直复处理）")
    p.add_argument("--ignore-overrides", action="store_true", help="忽略手工锚点（来源覆盖.json）")
    p.add_argument("--jobs", type=int, default=3, help="知识库并发数（默认 3；路由仍保持串行）")
    p.add_argument("--refresh-cache", action="store_true", help="重建路由、检索和知识库缓存")

    p = sub.add_parser("author", help="生成正文：同名直复 / 语义迁移 / 证据撰写任务包")
    _common(p)
    p.add_argument("--scope", "-s", required=True)
    p.add_argument("--node", action="store_true", help="只处理该节点本身")
    p.add_argument("--deep", action="store_true", help="展开整棵子树")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--kb", action="store_true", default=True)
    p.add_argument("--no-kb", action="store_true")
    p.add_argument("--allow-web", action="store_true")
    p.add_argument("--force", action="store_true", help="已有草稿也重新生成")
    p.add_argument("--force-write", action="store_true", help="即使同名也改走撰写任务包")
    p.add_argument("--no-assemble", action="store_true", help="不自动装配章节 md")
    p.add_argument("--no-publish", action="store_true", help="不把装配稿发布到「可研成果/」")
    p.add_argument("--ignore-claims", action="store_true",
                   help="忽略同名归属仲裁（所有同名候选都按直复处理）")
    p.add_argument("--ignore-overrides", action="store_true", help="忽略手工锚点（来源覆盖.json）")
    p.add_argument("--jobs", type=int, default=3, help="知识库并发数（默认 3；路由仍保持串行）")
    p.add_argument("--refresh-cache", action="store_true", help="重建路由和知识库缓存")

    p = sub.add_parser("run", help="章节级断点续跑：plan → author → check")
    _common(p)
    p.add_argument("--scope", "-s", required=True)
    p.add_argument("--node", action="store_true", help="只处理该节点本身")
    p.add_argument("--deep", action="store_true", help="展开整棵子树")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--kb", action="store_true", default=True)
    p.add_argument("--no-kb", action="store_true")
    p.add_argument("--allow-web", action="store_true")
    p.add_argument("--local-search", action="store_true", default=True)
    p.add_argument("--force", action="store_true", help="已有草稿也重新生成")
    p.add_argument("--force-write", action="store_true")
    p.add_argument("--no-assemble", action="store_true")
    p.add_argument("--no-publish", action="store_true")
    p.add_argument("--ignore-claims", action="store_true")
    p.add_argument("--ignore-overrides", action="store_true")
    p.add_argument("--jobs", type=int, default=3, help="知识库并发数（默认 3）")
    p.add_argument("--refresh-cache", action="store_true", help="重建所有优化缓存")
    p.add_argument("--limit", type=int, default=40, help="校验输出条目上限")

    p = sub.add_parser("assemble", help="装配 scope 内草稿为章节 md")
    _common(p)
    p.add_argument("--scope", "-s", required=True)
    p.add_argument("--output", "-o", default=None)
    p.add_argument("--no-publish", action="store_true", help="不把装配稿发布到「可研成果/」")

    p = sub.add_parser("publish", help="把装配稿发布到项目根的「可研成果/」（中文标题命名）")
    _common(p)
    p.add_argument("--scope", "-s", default=None, help="只发布该范围；省略则发布 chapters/ 下全部")

    p = sub.add_parser("clean", help="删除项目根的「临时脚本/」目录（收尾清理）")
    _common(p)

    p = sub.add_parser("check", help="校验草稿：规范覆盖/篇幅/空标题/重复/完整性")
    _common(p)
    p.add_argument("--scope", "-s", required=True)
    p.add_argument("--limit", type=int, default=40, help="输出条目上限（默认 40，避免大章刷屏）")

    p = sub.add_parser("report", help="输出编写进度与缺口清单")
    _common(p)

    p = sub.add_parser("search", help="本地原文检索（精确 + 近似）")
    _common(p)
    p.add_argument("--query", "-q", required=True)
    p.add_argument("--dir", "-d", default=None, help="默认工作区 source/")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--exact-only", action="store_true")
    p.add_argument("--refresh-cache", action="store_true", help="重建本地全文索引")

    p = sub.add_parser("kb", help="知识库检索（Dify；无凭据时回退本地 wiki）")
    _common(p)
    p.add_argument("--query", "-q", default="")
    p.add_argument("--kb", default=None, help="库名，逗号分隔（默认全部）")
    p.add_argument("--top-k", type=int, default=4)
    p.add_argument("--list", action="store_true", help="列出可用知识库")
    p.add_argument("--save", action="store_true", help="把命中落盘为 normalized/KB-*.md")
    p.add_argument("--refresh-cache", action="store_true", help="跳过知识库缓存重新查询")

    p = sub.add_parser("verify", help="自检：依赖、规范目录、知识库可达性")
    _common(p)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = COMMANDS[args.command]
    try:
        payload = handler(args)
    except AppError as exc:
        payload = {"command": args.command, "status": exc.status, "artifacts": [],
                   "summary": {"message": exc.message}, "diagnostics": exc.diagnostics or [exc.message]}
    except FileNotFoundError as exc:
        payload = {"command": args.command, "status": "error", "artifacts": [],
                   "summary": {"message": "file not found: %s" % exc}, "diagnostics": [str(exc)]}
    except Exception as exc:  # noqa: BLE001 - CLI 兜底：给单行 JSON，不抛栈
        payload = {"command": args.command, "status": "error", "artifacts": [],
                   "summary": {"message": "%s: %s" % (type(exc).__name__, exc)},
                   "diagnostics": [repr(exc)]}
    return emit(payload)


if __name__ == "__main__":
    sys.exit(main())
