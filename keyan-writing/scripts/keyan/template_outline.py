"""内置可研目录骨架：无外部模板时自动物化到工作区。"""
from pathlib import Path
import re

from .headings import normalize_title
from .jsonio import AppError, dump_json
from .tree import node_by_number, render_leaf_index_markdown, render_tree_markdown
from .workspace import ensure, load_project


BUILTIN_OUTLINE = Path(__file__).resolve().parents[2] / "references" / "template-outline" / "可研报告目录骨架.md"
_HEADING = re.compile(r"^(#{1,9})\s+(\d+(?:\.\d+)*)\s+(.+?)\s*$")


def _key(number):
    return "chapter_" + "_".join("%02d" % int(part) for part in number.split("."))


def load_builtin_outline(path=BUILTIN_OUTLINE):
    """把纯 Markdown 标题目录编译成与 scan 产物一致的树结构。"""
    path = Path(path)
    if not path.exists():
        raise AppError("技能内置可研目录骨架不存在：%s" % path, status="error")
    chapters, stack, order = [], [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _HEADING.match(line)
        if not match:
            continue
        hashes, number, title = match.groups()
        depth = len(number.split("."))
        if len(hashes) != depth:
            raise AppError("内置目录层级与编号不一致：%s" % line, status="error")
        order += 1
        node = {
            "key": _key(number), "number": number, "level": depth, "depth": depth,
            "title": title, "norm_title": normalize_title(title), "style": "Heading %d" % depth,
            "leaf": True, "own_chars": 0, "subtree_chars": 0, "tables": 0, "images": 0,
            "children_count": 0, "doc_order": order, "own_start": 0, "own_end": 0,
            "path_titles": [], "children": [],
        }
        while len(stack) >= depth:
            stack.pop()
        if depth == 1:
            chapters.append(node)
        elif len(stack) != depth - 1:
            raise AppError("内置目录存在断层：%s" % line, status="error")
        else:
            stack[-1]["children"].append(node)
        stack.append(node)
        node["path_titles"] = [item["title"] for item in stack]

    def finalize(node):
        for child in node["children"]:
            finalize(child)
        node["children_count"] = len(node["children"])
        node["leaf"] = not node["children"]

    for chapter in chapters:
        finalize(chapter)
    nodes = []

    def collect(node):
        nodes.append(node)
        for child in node["children"]:
            collect(child)

    for chapter in chapters:
        collect(chapter)
    return {
        "name": "内置可研报告目录骨架", "path": str(path),
        "stats": {"builtin": True, "blocks": 0, "chars": 0, "headings": len(nodes),
                  "images": 0, "paragraphs": 0, "tables": 0},
        "max_depth": max((node["depth"] for node in nodes), default=0),
        "node_count": len(nodes), "leaf_count": sum(1 for node in nodes if node["leaf"]),
        "chapters": chapters,
    }


def ensure_builtin_template(ws):
    """外部模板未注册时，将技能自带的纯目录骨架安装到工作区。"""
    ws = ensure(ws)
    role_dir = ws / "template"
    tree_path = role_dir / "目录树.json"
    if tree_path.exists():
        return {"created": False, "artifacts": [], "tree_path": tree_path}

    registered = [item for item in load_project(ws).get("inputs", [])
                  if item.get("role") == "template"]
    if registered:
        raise AppError("template 目录树不存在：已注册外部可研模板，请重新运行 scan --role template",
                       status="partial")
    tree = load_builtin_outline()
    if not tree["chapters"] or node_by_number(tree, "5.6") is None:
        raise AppError("技能内置可研目录骨架无效：缺少章节或 5.6 系统设计方案", status="error")

    dump_json(tree_path, tree)
    tree_md = role_dir / "目录树.md"
    leaves_md = role_dir / "叶子清单.md"
    tree_md.write_text(render_tree_markdown(tree, title="内置可研报告目录骨架"), encoding="utf-8")
    leaves_md.write_text(render_leaf_index_markdown(tree), encoding="utf-8")
    marker = role_dir / "内置模板说明.json"
    dump_json(marker, {
        "builtin": True,
        "resource": str(BUILTIN_OUTLINE),
        "description": "仅含固定目录结构，不含示例项目正文；5.6 子树由本次建设方案动态派生。",
    })
    return {"created": True,
            "artifacts": [str(tree_path), str(tree_md), str(leaves_md), str(marker)],
            "tree_path": tree_path}
