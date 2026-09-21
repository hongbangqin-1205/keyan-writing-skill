"""输入文件扫描：目录树（到最小层级）+ 建设方案/模板 Markdown 转换。"""
from pathlib import Path
import re

from .docx_blocks import extract_assets, read_document
from .cache import sha256_file, sha256_json
from .jsonio import AppError, dump_json, load_json, slug
from .markdown import blocks_to_markdown
from .tree import build_tree, render_leaf_index_markdown, render_tree_markdown, tree_to_dict
from .workspace import ensure, register_input


def validate_role(role):
    if role not in ("source", "template") and not re.fullmatch(r"material_[A-Za-z0-9][A-Za-z0-9_-]{0,63}", role):
        raise ValueError("材料角色须为 source、template 或 material_<唯一编号>")
    return role


def _cache_valid(cache_path, source_path):
    cache = Path(cache_path)
    source = Path(source_path)
    return cache.exists() and cache.stat().st_mtime >= source.stat().st_mtime


def load_blocks(ws, role, *, source_path=None, rebuild=False):
    """优先读取扫描缓存 blocks.json；必要时重新解析源文件。"""
    ws = ensure(ws)
    cache = ws / role / "blocks.json"
    if not rebuild and cache.exists():
        if source_path is None:
            return load_json(cache)
        if _cache_valid(cache, source_path):
            return load_json(cache)
    if source_path is None:
        raise FileNotFoundError("no cached blocks and no source path given: %s" % cache)
    doc = read_document(source_path)
    dump_json(cache, doc)
    return doc


def scan_input(ws, source_path, role, *, rebuild=False):
    """扫描一个输入文件：落盘目录树、Markdown、素材缓存。"""
    validate_role(role)
    ws = ensure(ws)
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    role_dir = ws / role
    role_dir.mkdir(parents=True, exist_ok=True)
    doc = read_document(str(source_path))
    blocks = doc["blocks"]
    existing = role_dir / "blocks.json"
    if role == "source" and existing.exists() and sha256_json(load_json(existing)) != sha256_json(doc):
        used = (any((ws / "drafts").glob("*.md")) or
                any((ws / "chapters").glob("*.md")) or
                any((ws / "match").glob("*.json")) or
                (ws / "template" / "项目目录元数据.json").exists())
        if used:
            raise AppError("建设方案已变化，现有草稿/锚点属于旧项目：请为新输入创建独立工作区",
                           status="conflict")
    dump_json(role_dir / "blocks.json", doc)

    tree = build_tree(doc)
    dump_json(role_dir / "目录树.json", tree_to_dict(tree))
    (role_dir / "目录树.md").write_text(
        render_tree_markdown(tree, title=source_path.stem), encoding="utf-8")
    (role_dir / "叶子清单.md").write_text(
        render_leaf_index_markdown(tree), encoding="utf-8")

    asset_map = {}
    rids = [block["rid"] for block in blocks if block["kind"] == "image"]
    if rids and source_path.suffix.lower() == ".docx":
        asset_map = extract_assets(str(source_path), rids, role_dir / "assets")

    if asset_map:
        dump_json(role_dir / "assets.json", asset_map)
    else:
        dump_json(role_dir / "assets.json", {})

    markdown = blocks_to_markdown(blocks, asset_map=asset_map)
    md_path = role_dir / (slug(source_path.stem) + ".md")
    md_path.write_text(markdown, encoding="utf-8")

    stats = dict(doc["stats"])
    stats.update({
        "chapters": len(tree["chapters"]),
        "nodes": tree["node_count"],
        "leaves": tree["leaf_count"],
        "max_depth": tree["max_depth"],
        "markdown_chars": len(markdown),
        "assets": len(asset_map),
    })
    register_input(ws, role, source_path, extras={
        "sha256": sha256_file(source_path),
        "tree": "目录树.json",
        "markdown": md_path.name,
        "stats": stats,
        "role_dir": role,
    })
    return {
        "status": "ok",
        "artifacts": [str(role_dir / "目录树.md"), str(role_dir / "目录树.json"),
                      str(role_dir / "叶子清单.md"), str(md_path)],
        "summary": {"role": role, "source": str(source_path), **stats},
        "diagnostics": [],
    }
