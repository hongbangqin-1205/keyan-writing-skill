"""工作区布局：<ws>/{source,template,match,plan,chapters,drafts,normalized,reports}。"""
import os
from pathlib import Path

from .jsonio import dump_json, load_json

WORKSPACE_ENV = "KEYAN_WORKSPACE"
DEFAULT_WORKSPACE = "keyan-work"
SUBDIRS = ("source", "template", "match", "plan", "chapters", "drafts", "normalized", "reports",
           "cache")

# 交付约定：成品 md 落在项目根的中文名目录，方便用户直接翻看；
# 一次性临时脚本一律集中到另一个中文名目录，收尾时整个删掉，不污染项目根。
DELIVERABLE_DIRNAME = "可研成果"
TEMP_SCRIPT_DIRNAME = "临时脚本"


def resolve_workspace(explicit=None):
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get(WORKSPACE_ENV)
    if env:
        return Path(env).expanduser().resolve()
    return (Path.cwd() / DEFAULT_WORKSPACE).resolve()


def project_root(ws=None):
    """项目根 = 工作区的父目录（工作区自身已是盘根时退回工作区）。"""
    base = Path(ws) if ws else resolve_workspace()
    base = base.expanduser().resolve()
    parent = base.parent
    return parent if parent != base else base


def deliverable_dir(ws=None):
    """成品目录：<项目根>/可研成果/。"""
    return project_root(ws) / DELIVERABLE_DIRNAME


def temp_script_dir(ws=None):
    """临时脚本目录：<项目根>/临时脚本/，收尾时整体删除。"""
    return project_root(ws) / TEMP_SCRIPT_DIRNAME


def ensure(ws):
    ws = Path(ws)
    ws.mkdir(parents=True, exist_ok=True)
    for name in SUBDIRS:
        (ws / name).mkdir(parents=True, exist_ok=True)
    return ws


def project_path(ws):
    return Path(ws) / "project.json"


def load_project(ws, default=None):
    path = project_path(ws)
    if not path.exists():
        if default is None:
            return {"workspace": str(ws), "inputs": [], "scans": {}}
        return default
    return load_json(path)


def save_project(ws, project):
    return dump_json(project_path(ws), project)


def register_input(ws, role, path, *, extras=None):
    project = load_project(ws)
    entry = {"role": role, "path": str(Path(path).resolve()), "name": Path(path).name}
    if extras:
        entry.update(extras)
    project["inputs"] = [item for item in project.get("inputs", [])
                         if not (item.get("role") == role and item.get("path") == entry["path"])]
    project["inputs"].append(entry)
    save_project(ws, project)
    return project
