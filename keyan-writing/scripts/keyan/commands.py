"""CLI 命令实现。"""
import datetime
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import __version__
from .anchoring import (apply_decisions, autodetect_source_parent, derive_anchors,
                        render_review as render_anchor_review)
from .arbitration import build_arbitration, render_report as arbitration_report
from .cache import load_cache, save_cache, sha256_file, sha256_json, tree_fingerprint
from .authoring import (copy_draft, load_source, render_scope_markdown, reuse_draft,
                        source_index, write_task_pack)
from .checking import check_scope
from .headings import normalize_title
from .jsonio import AppError, dump_json, load_json, slug
from .kb import find_kb_root, list_libraries, search as kb_search
from .localsearch import search_dir
from .matching import SourceIndex
from .project_tree import choose_source_domain, derive_project_tree, source_domains
from .reuse import paragraph_records
from .routing import (MODE_LABELS, MODE_PRIORITY, SEMANTIC_MIN_CANDIDATE_CHARS, route_node)
from .scan import scan_input
from .scope import parse_scope
from .specs import Specs
from .template_outline import ensure_builtin_template
from .tree import (find_nodes, iter_nodes, node_by_key, node_by_number, render_tree_markdown,
                    tree_from_dict, tree_to_dict)
from .workspace import (TEMP_SCRIPT_DIRNAME, deliverable_dir, ensure, load_project, project_root,
                        resolve_workspace, save_project, temp_script_dir)


def skill_root():
    return Path(__file__).resolve().parents[2]


def _ws(args):
    return ensure(resolve_workspace(getattr(args, "workspace", None)))


def _load_tree(ws, role, *, base=False):
    path = Path(ws) / role / "目录树.json"
    if role == "template" and not path.exists():
        ensure_builtin_template(ws)
    if not path.exists():
        raise AppError("%s 目录树不存在：先运行 scan --role %s" % (role, role), status="partial")
    if role in ("source", "template"):
        registered = [item for item in load_project(ws).get("inputs", []) if item.get("role") == role]
        if registered and registered[-1].get("sha256"):
            original = Path(registered[-1]["path"])
            if original.exists() and sha256_file(original) != registered[-1]["sha256"]:
                raise AppError("%s 输入文件扫描后发生变化：请在新工作区重新扫描" % role,
                               status="conflict")
    if role == "template" and not base:
        meta = Path(ws) / "template" / "项目目录元数据.json"
        if meta.exists():
            state = load_json(meta)
            source = Path(ws) / "source" / "blocks.json"
            if (not source.exists() or state.get("source_sha256") != sha256_file(source)
                    or state.get("template_sha256") != sha256_file(path)):
                raise AppError("项目目录与当次输入不一致：请使用独立工作区重新扫描并运行 project-tree",
                               status="conflict")
            return tree_from_dict(load_json(Path(ws) / "template" / "项目目录树.json"))
    return tree_from_dict(load_json(path))


def _specs(args):
    return Specs(getattr(args, "skill_root", None) or skill_root())


def _has_own_text(node):
    """节点自身是否有正文：只有标题、没落笔的纯目录容器不构成写作目标。"""
    return bool(node.get("own_chars")) or not node.get("children")


def _writing_level_keys(node):
    """把纯目录容器逐层下钻，返回有正文的写作目标。"""
    if _has_own_text(node):
        return [node["key"]]
    drilled = []
    for child in node["children"]:
        drilled.extend(_writing_level_keys(child))
    return drilled


def _expand_targets(tree, keys, *, mode="auto", deep=False):
    result = []
    for key in keys:
        node = node_by_key(tree, key)
        if node is None:
            continue
        if deep:
            # 整棵子树下钻到最小层级：跳过"1 概述""1.1 项目概况"这类只有标题的目录节点
            drilled = [item["key"] for item in iter_nodes([node]) if _has_own_text(item)]
            result.extend(drilled or [node["key"]])
        elif mode == "node" or not node["children"]:
            result.append(node["key"])
        elif all(not _has_own_text(child) for child in node["children"]):
            # 直接子级全是纯目录容器 → 继续下钻到有正文的层级
            for child in node["children"]:
                result.extend(_writing_level_keys(child))
        else:
            result.extend(child["key"] for child in node["children"])
    seen, ordered = set(), []
    for key in result:
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def _skeleton_draft(node, skeleton):
    """给待撰写节点落一份带标记的草稿，便于统一装配与校验。"""
    header = ("<!-- keyan mode=grounded_write target=%s待撰写：按 plan/%s.任务单.md 撰写，"
              "完成后删除本行与下方待写标记 -->" % (node["key"], node["key"]))
    return header + "\n\n" + skeleton.strip() + "\n"


def _manual_overrides(ws):
    """人工锚点（match/来源覆盖.json）：显式指定，优先级最高，永不被自动派生覆盖。"""
    return load_json(ws / "match" / "来源覆盖.json", default={}) or {}


def _auto_overrides(ws):
    """自动锚点（match/自动锚点.json）：由 anchor 命令按输入文件派生，可随时重算。"""
    payload = load_json(ws / "match" / "自动锚点.json", default={})   # 未派生时为空，不是错误
    return (payload or {}).get("anchors") or {}


def _overrides(ws):
    """生效锚点：人工优先，自动兜底（只在人工未指定的节点上生效）。"""
    manual = _manual_overrides(ws)
    merged = {key: value for key, value in _auto_overrides(ws).items() if key not in manual}
    merged.update(manual)
    project = Path(ws) / "template" / "项目目录元数据.json"
    if project.exists():
        _load_tree(ws, "template")
        merged.update((load_json(project) or {}).get("anchors") or {})
    return merged


def _routing_context(ws, template_tree, index, specs, args):
    """计划/撰写前的路由上下文：手工锚点 + 同名归属仲裁。"""
    overrides = {} if getattr(args, "ignore_overrides", False) else _overrides(ws)
    if getattr(args, "ignore_claims", False):
        return None, overrides
    return _cached_arbitration(ws, template_tree, index, specs, overrides,
                               refresh=bool(getattr(args, "refresh_cache", False))), overrides


def _routing_fingerprint(ws, specs, overrides):
    files = []
    for path in (Path(ws) / "source" / "blocks.json",
                 Path(ws) / "template" / "blocks.json",
                 Path(ws) / "template" / "目录树.json"):
        files.append({"path": str(path), "sha256": sha256_file(path) if path.exists() else None})
    return sha256_json({
        "schema": 2,
        "skill_version": __version__,
        "inputs": files,
        "overrides": overrides,
        "specs": tree_fingerprint(specs.base),
        "routing_code": tree_fingerprint(skill_root() / "scripts" / "keyan", "*.py"),
    })


def _cached_arbitration(ws, template_tree, index, specs, overrides, *, refresh=False):
    cache_path = Path(ws) / "cache" / "routing" / "arbitration.json"
    fingerprint = _routing_fingerprint(ws, specs, overrides)
    if not refresh:
        cached = load_cache(cache_path, fingerprint)
        if isinstance(cached, dict):
            return cached
    result = build_arbitration(template_tree, index, specs, overrides=overrides)
    save_cache(cache_path, fingerprint, result)
    return result


def _kb_batch(ws, kb_root, rows, *, top_k, jobs=1, refresh=False):
    """并发执行已经冻结路由的 KB 查询；结果仍按节点 key 归并。"""
    queries = {row["node"]["key"]: _kb_query(row["node"]) for row in rows
               if row["decision"]["mode"] in ("grounded_write", "gap")}
    if not kb_root or not queries:
        return {}

    def fetch(item):
        key, query = item
        return key, kb_search(kb_root, query, top_k=top_k, cache_dir=Path(ws) / "cache",
                              refresh=refresh)

    if max(1, int(jobs or 1)) == 1:
        return dict(fetch(item) for item in queries.items())
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, int(jobs))) as pool:
        futures = [pool.submit(fetch, item) for item in queries.items()]
        for future in as_completed(futures):
            key, result = future.result()
            results[key] = result
    return results


MODE_SHORT_LABELS = {
    "exact_direct_copy": "同名直复", "semantic_migrate": "语义迁移",
    "title_migrate": "标题迁移", "paragraph_reuse": "段落复用",
    "material_reuse": "材料复用", "grounded_write": "证据撰写", "gap": "缺口",
}


def _material_inputs(ws):
    """用户另传的其他材料（role 非 source/template）：材料复用的检索库。"""
    materials = []
    for item in (load_project(ws).get("inputs") or []):
        role = item.get("role")
        if not role or role in ("source", "template"):
            continue
        role_dir = Path(ws) / (item.get("role_dir") or role)
        tree_path = role_dir / "目录树.json"
        blocks_path = role_dir / "blocks.json"
        if not tree_path.exists() or not blocks_path.exists():
            continue
        tree = tree_from_dict(load_json(tree_path))
        blocks = load_json(blocks_path)["blocks"]
        materials.append({"role": role, "title": item.get("name") or role,
                          "index": SourceIndex(tree, blocks),
                          "paragraphs": paragraph_records(blocks, tree)})
    return materials


def _role_source(ws, index, assets, materials, role):
    """按来源角色取索引与素材表（建设方案 -> 主索引，其他材料 -> 材料索引）。"""
    if not role or role == "source":
        return index, assets
    for item in materials or ():
        if item.get("role") == role:
            return item["index"], load_json(Path(ws) / role / "assets.json", {}) or {}
    return index, assets


def _claimed_orders(decision):
    """已被复用的来源段落序号：同一段原文不在两个节点里重复出现。"""
    if decision.get("reuse_kind") != "paragraphs":
        return ()
    role = decision.get("reuse_role", "source")
    return [(role, ref["order"]) for ref in (decision.get("reuse") or {}).get("refs") or []]


def _kb_query(node):
    """知识库检索词：小节标题 + 所属章节 + 规范要素关键词。"""
    pieces = [node.get("title", ""), " ".join(node.get("path_titles", [])[:-1])]
    return " ".join(piece for piece in pieces if piece).strip()


# ------------------------------------------------------------------ init
def cmd_init(args):
    ws = _ws(args)
    project = load_project(ws)
    project.update({"workspace": str(ws), "skill_version": __version__,
                    "updated_at": datetime.datetime.now().isoformat(timespec="seconds")})
    project.setdefault("inputs", [])
    save_project(ws, project)
    created = [str(ws / name) for name in ("source", "template", "match", "plan", "chapters",
                                           "drafts", "normalized", "reports", "cache")]
    for path in (deliverable_dir(ws), temp_script_dir(ws)):
        path.mkdir(parents=True, exist_ok=True)
        created.append(str(path))
    builtin = ensure_builtin_template(ws)
    created.extend(builtin["artifacts"])
    return {"command": "init", "status": "ok", "artifacts": created,
            "summary": {"workspace": str(ws), "inputs": len(project["inputs"]),
                        "template": "builtin" if builtin["created"] else "existing",
                        "deliverable_dir": str(deliverable_dir(ws)),
                        "temp_script_dir": str(temp_script_dir(ws))},
            "diagnostics": []}


# ------------------------------------------------------------------ scan
def cmd_scan(args):
    ws = _ws(args)
    payload = scan_input(ws, args.input, args.role, rebuild=bool(getattr(args, "rebuild", False)))
    payload["command"] = "scan"
    return payload


def cmd_project_tree(args):
    ws = _ws(args)
    template_tree = _load_tree(ws, "template", base=True)
    source_tree = _load_tree(ws, "source")
    ranked = source_domains(source_tree)
    parent = choose_source_domain(source_tree, args.source_scope)
    candidates = [{"number": node["number"], "title": node["title"],
                   "subtree_chars": node["subtree_chars"], "children": node["children_count"]}
                  for node in parent["children"]]
    if not args.systems:
        return {"command": "project-tree", "status": "partial", "artifacts": [],
                "summary": {"source_domain": parent["number"], "domains": ranked,
                            "candidates": candidates},
                "diagnostics": ["请核对本次系统清单，用 --systems 按来源顺序确认；不自动继承旧项目目录"]}
    systems = [token.strip() for token in args.systems.split(",") if token.strip()]
    tree, anchors = derive_project_tree(template_tree, parent, systems)
    tree_path = ws / "template" / "项目目录树.json"
    meta_path = ws / "template" / "项目目录元数据.json"
    dump_json(tree_path, tree_to_dict(tree))
    dump_json(meta_path, {"source_sha256": sha256_file(ws / "source" / "blocks.json"),
                          "template_sha256": sha256_file(ws / "template" / "目录树.json"),
                          "source_domain": parent["key"], "systems": systems,
                          "anchors": anchors})
    return {"command": "project-tree", "status": "ok",
            "artifacts": [str(tree_path), str(meta_path)],
            "summary": {"source_domain": parent["number"], "systems": systems,
                        "nodes": tree["node_count"]}, "diagnostics": []}


# ------------------------------------------------------------------ tree
def cmd_tree(args):
    ws = _ws(args)
    role = args.role or ("template" if (ws / "template" / "目录树.json").exists() else "source")
    tree = _load_tree(ws, role)
    if args.output:
        Path(args.output).write_text(render_tree_markdown(tree, max_depth=args.max_depth,
                                                          title=tree.get("name")), encoding="utf-8")
    nodes = list(iter_nodes(tree["chapters"]))
    if args.grep:
        needle = normalize_title(args.grep)
        nodes = [node for node in nodes if needle in node["norm_title"]]
    if args.leaves:
        nodes = [node for node in nodes if node["leaf"]]
    if args.level:
        nodes = [node for node in nodes if node["level"] == args.level]
    listed = nodes[: args.limit]
    return {"command": "tree", "status": "ok",
            "artifacts": [args.output] if args.output else [],
            "summary": {"role": role, "chapters": len(tree["chapters"]), "nodes": tree["node_count"],
                        "leaves": tree["leaf_count"], "max_depth": tree["max_depth"],
                        "matched": len(nodes), "listed": len(listed),
                        "stats": tree.get("stats", {})},
            "nodes": [{"key": node["key"], "number": node["number"], "level": node["level"],
                       "title": node["title"], "chars": node["subtree_chars"],
                       "tables": node["tables"], "children": node["children_count"],
                       "leaf": node["leaf"]} for node in listed],
            "diagnostics": []}


# ------------------------------------------------------------------ index
def cmd_index(args):
    ws = _ws(args)
    source_tree, blocks, _assets = load_source(ws)
    template_tree = _load_tree(ws, "template")
    index = SourceIndex(source_tree, blocks)
    specs = _specs(args)
    entries = {}
    for norm, items in sorted(index.by_norm.items()):
        entries[norm] = [{"key": item["key"], "number": item["number"], "title": item["title"],
                          "subtree_chars": item["subtree_chars"], "children": item["children_count"]}
                         for item in items]
    payload = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
               "source": {"name": source_tree.get("name"), "nodes": source_tree["node_count"],
                          "titles": len(entries)},
               "template": {"name": template_tree.get("name"), "nodes": template_tree["node_count"]},
               "exact_index": entries}
    dump_json(ws / "match" / "heading-index.json", payload)

    overrides = _overrides(ws)
    arbitration = _cached_arbitration(
        ws, template_tree, index, specs, overrides,
        refresh=bool(getattr(args, "refresh_cache", False)))
    dump_json(ws / "match" / "同名归属.json", arbitration)
    (ws / "match" / "同名归属.md").write_text(
        arbitration_report(template_tree, index, arbitration), encoding="utf-8")

    rows, counts = [], {"exact": 0, "semantic": 0, "none": 0, "demoted": 0}
    for node in iter_nodes(template_tree["chapters"]):
        best, scored = index.resolve_exact(node)
        dropped = arbitration["demoted"].get(node["key"])
        if best:
            counts["exact"] += 1
            if dropped:
                counts["demoted"] += 1
                verdict = "降级·%s" % dropped["reason"].replace("exact_", "")
            else:
                verdict = "直复"
            rows.append((node, "exact_direct_copy", best["entry"], best["score"], verdict))
        else:
            similar = index.similar_entries(node["title"], k=3,
                                             min_chars=SEMANTIC_MIN_CANDIDATE_CHARS,
                                             min_score=0.34)
            if similar:
                counts["semantic"] += 1
                rows.append((node, "semantic_candidate", similar[0][1], similar[0][0], "迁移候选"))
            else:
                counts["none"] += 1
                rows.append((node, "grounded_write", None, 0.0, "撰写"))
    lines = ["# 同名/候选映射（模板 ← 建设方案）", "",
             "统计：同名直复 %d（其中降级 %d）｜语义候选 %d｜需撰写 %d｜模板节点 %d" % (
                 counts["exact"], counts["demoted"], counts["semantic"], counts["none"], len(rows)), "",
             "> 降级 = 同名候选不在本节素材范围内或已被更贴合的小节占用，详见 同名归属.md。", "",
             "| 模板节点 | 模板标题 | 层级 | 候选路由 | 归属判定 | 来源节点 | 来源标题 | 分数 |",
             "|---|---|---|---|---|---|---|---|"]
    for node, mode, entry, score, verdict in rows:
        lines.append("| %s | %s | L%d | %s | %s | %s | %s | %.2f |" % (
            node["key"], node["title"].replace("|", "/"), node["level"], mode, verdict,
            entry["key"] if entry else "-", (entry["title"].replace("|", "/") if entry else "-"), score))
    (ws / "match" / "同名映射.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"command": "index", "status": "ok",
            "artifacts": [str(ws / "match" / "heading-index.json"), str(ws / "match" / "同名映射.md"),
                          str(ws / "match" / "同名归属.json"), str(ws / "match" / "同名归属.md")],
            "summary": {"titles_indexed": len(entries), "template_nodes": len(rows), **counts,
                        "claims": arbitration["summary"]["claims"],
                        "scoped_nodes": arbitration["summary"]["scoped_nodes"],
                        "demoted_reasons": arbitration["summary"]["demoted_reasons"]},
            "diagnostics": []}


# ------------------------------------------------------------------ plan
def cmd_plan(args):
    ws = _ws(args)
    specs = _specs(args)
    template_tree = _load_tree(ws, "template")
    index, _assets = source_index(ws)
    arbitration, overrides = _routing_context(ws, template_tree, index, specs, args)
    scope = parse_scope(args.scope, template_tree)
    keys = _expand_targets(template_tree, scope["keys"], mode="node" if args.node else "auto",
                           deep=bool(args.deep))
    kb_root = find_kb_root(skill_root()) if (args.kb and not args.no_kb) else None
    paragraphs = paragraph_records(index.blocks, index.tree)
    materials = _material_inputs(ws)
    claimed = set()
    decisions, packs, artifacts, routed = [], [], [], []
    for key in keys:
        node = node_by_key(template_tree, key)
        spec = specs.spec_for_node(node)
        decision = route_node(index, specs, node, allow_web=bool(args.allow_web), top_k=args.top_k,
                              arbitration=arbitration, override=overrides.get(key),
                              paragraphs=paragraphs, materials=materials, exclude_orders=claimed)
        claimed.update(_claimed_orders(decision))
        routed.append({"node": node, "spec": spec, "decision": decision})
    kb_results = _kb_batch(ws, kb_root, routed, top_k=args.top_k,
                           jobs=getattr(args, "jobs", 1),
                           refresh=bool(getattr(args, "refresh_cache", False)))
    refresh_local = bool(getattr(args, "refresh_cache", False))
    for row in routed:
        node, spec, decision = row["node"], row["spec"], row["decision"]
        key = node["key"]
        kb_result = kb_results.get(key)
        if kb_result is not None:
            decision["kb_hits"] = (kb_result or {}).get("hits") or []
            decision["reasons"].append("知识库命中 %d 条（backend=%s）"
                                       % (len(decision["kb_hits"]), (kb_result or {}).get("backend")))
        sources = (search_dir(ws / "source", node["title"], top_k=5,
                              exclude_names=("目录树.md", "叶子清单.md"),
                              cache_dir=ws / "cache",
                              refresh=refresh_local)
                   if args.local_search else [])
        refresh_local = False
        written = write_task_pack(ws, node, decision, kb_result=kb_result, spec=spec, sources=sources)
        artifacts.extend(written["artifacts"])
        decisions.append(decision)
        packs.append({"key": key, "mode": decision["mode"]})
    summary = {"scope": scope["label"], "targets": len(keys),
               "modes": {mode: sum(1 for item in decisions if item["mode"] == mode) for mode in MODE_LABELS}}
    dump_json(ws / "plan" / ("%s.计划.json" % slug(scope["label"] or "all")),
              {"scope": scope, "targets": keys, "decisions": decisions, "summary": summary})
    overview = ["# 章节写作计划 · %s" % (scope["label"] or "all"), "",
                "目标节点 %d：%s%s" % (
                    len(keys),
                    "｜".join("%s %d" % (MODE_SHORT_LABELS[mode], summary["modes"].get(mode, 0))
                              for mode in MODE_PRIORITY),
                    "；用户材料 %d 份参与检索" % len(materials) if materials else ""), ""]
    dropped = [decision for decision in decisions if decision.get("claim_dropped")]
    if dropped:
        overview.append("其中 %d 个节点的同名候选被归属仲裁降级（详见 match/同名归属.md）：" % len(dropped))
        for decision in dropped:
            record = decision["claim_dropped"]
            overview.append("- %s %s：同名候选《%s》%s%s" % (
                decision["key"], decision["title"], record.get("source_title", ""),
                record.get("label", ""),
                ("；素材范围应为 %s" % record["scope_title"]) if record.get("scope_title") else ""))
        overview.append("")
    overview += ["| 节点 | 标题 | 模式 | 来源 | 理由 |", "|---|---|---|---|---|"]
    for decision in decisions:
        source = (decision.get("matched_source") or {}).get("title", "-")
        overview.append("| %s | %s | %s | %s | %s |" % (
            decision["key"], decision["title"].replace("|", "/"), decision["mode"], source,
            "；".join(decision.get("reasons", []))[:150].replace("|", "/")))
    plan_md = ws / "plan" / ("%s.计划总览.md" % slug(scope["label"] or "all"))
    plan_md.write_text("\n".join(overview) + "\n", encoding="utf-8")
    artifacts.append(str(plan_md))
    status = "ok" if keys else "partial"
    return {"command": "plan", "status": status, "artifacts": artifacts,
            "summary": summary, "decisions": decisions,
            "diagnostics": [] if scope["unresolved"] == [] else ["scope_unresolved: %s" % scope["unresolved"]]}


# ------------------------------------------------------------------ author
def cmd_author(args):
    ws = _ws(args)
    specs = _specs(args)
    template_tree = _load_tree(ws, "template")
    index, assets = source_index(ws)
    arbitration, overrides = _routing_context(ws, template_tree, index, specs, args)
    scope = parse_scope(args.scope, template_tree)
    keys = _expand_targets(template_tree, scope["keys"], mode="node" if args.node else "auto",
                           deep=bool(args.deep))
    if not keys:
        raise AppError("scope 未匹配到目标节点：%s" % args.scope, status="partial")
    kb_root = find_kb_root(skill_root()) if (args.kb and not args.no_kb) else None
    paragraphs = paragraph_records(index.blocks, index.tree)
    materials = _material_inputs(ws)
    claimed = set()
    artifacts, results, routed = [], [], []
    counts = {mode: 0 for mode in MODE_LABELS}
    for key in keys:
        node = node_by_key(template_tree, key)
        spec = specs.spec_for_node(node)
        draft_path = ws / "drafts" / ("%s.md" % key)
        if draft_path.exists() and not args.force:
            existing = draft_path.read_text(encoding="utf-8", errors="ignore")
            incomplete = ("待写" in existing or "TODO" in existing or
                          "mode=grounded_write" in existing or
                          not existing.strip())
            project_anchor = ((load_json(ws / "template" / "项目目录元数据.json", default={}) or {})
                              .get("anchors") or {}).get(key)
            if project_anchor:
                sidecar = load_json(ws / "drafts" / ("%s.sidecar.json" % key), default={}) or {}
                incomplete = incomplete or (sidecar.get("source_sha256") !=
                                            sha256_file(ws / "source" / "blocks.json") or
                                            (sidecar.get("source") or {}).get("key") !=
                                            project_anchor["source"])
            if not incomplete:
                results.append({"key": key, "mode": "skipped_existing", "artifacts": []})
                continue
        decision = route_node(index, specs, node, allow_web=bool(args.allow_web), top_k=args.top_k,
                              arbitration=arbitration, override=overrides.get(key),
                              paragraphs=paragraphs, materials=materials, exclude_orders=claimed)
        claimed.update(_claimed_orders(decision))
        routed.append({"node": node, "spec": spec, "decision": decision,
                       "draft_path": draft_path})
    kb_results = _kb_batch(ws, kb_root, routed, top_k=args.top_k,
                           jobs=getattr(args, "jobs", 1),
                           refresh=bool(getattr(args, "refresh_cache", False)))
    for row in routed:
        node, spec, decision = row["node"], row["spec"], row["decision"]
        key, draft_path = node["key"], row["draft_path"]
        kb_result = kb_results.get(key)
        if kb_result is not None:
            decision["kb_hits"] = (kb_result or {}).get("hits") or []
            decision["reasons"].append("知识库命中 %d 条"
                                       % len(decision["kb_hits"]))
        mode = decision["mode"]
        if mode in ("exact_direct_copy", "semantic_migrate", "title_migrate") and not args.force_write:
            written = copy_draft(ws, index, assets, node, decision)
            results.append({"key": key, "mode": mode, "artifacts": written["artifacts"],
                            "chars": written["sidecar"]["chars"],
                            "source": (decision.get("matched_source") or {}).get("key")})
        elif mode in ("paragraph_reuse", "material_reuse") and not args.force_write:
            if decision.get("reuse_kind") == "migrate":
                role_index, role_assets = _role_source(ws, index, assets, materials,
                                                       decision.get("reuse_role"))
                written = copy_draft(ws, role_index, role_assets, node, decision)
                results.append({"key": key, "mode": mode, "artifacts": written["artifacts"],
                                "chars": written["sidecar"]["chars"],
                                "source": (decision.get("matched_source") or {}).get("key")})
            else:
                written = reuse_draft(ws, node, decision, spec=spec)
                results.append({"key": key, "mode": mode, "artifacts": written["artifacts"],
                                "chars": written["sidecar"]["chars"],
                                "source": (decision.get("matched_source") or {}).get("key"),
                                "reused_paragraphs":
                                    (written["sidecar"].get("source") or {}).get("paragraphs")})
        else:
            written = write_task_pack(ws, node, decision, kb_result=kb_result, spec=spec)
            placeholder = _skeleton_draft(node, written["skeleton"])
            draft_path.write_text(placeholder, encoding="utf-8")
            results.append({"key": key, "mode": mode,
                            "artifacts": written["artifacts"] + [str(draft_path)],
                            "chars": 0, "source": None, "todo": True,
                            "agent_required": True,
                            "message": "仅生成取证任务包；必须由 Agent 读取全文证据并完成正文后方可装配"})
        counts[mode] = counts.get(mode, 0) + 1
        artifacts.extend(results[-1]["artifacts"])
    assemble_path = None
    deliverable_path = None
    pending = [item for item in results if item.get("todo") or item.get("agent_required")]
    if keys and not args.no_assemble and not pending:
        markdown, used = render_scope_markdown(ws, template_tree, scope["keys"])
        label = slug(scope["label"] or "all")
        assemble_path = ws / "chapters" / ("%s.md" % label)
        assemble_path.write_text(markdown, encoding="utf-8")
        dump_json(ws / "chapters" / ("%s.sidecar.json" % label),
                  {"scope": scope, "used_drafts": used, "targets": keys,
                   "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                   **_assembly_provenance(ws, assemble_path)})
        artifacts.append(str(assemble_path))
        if not getattr(args, "no_publish", False):
            outcome = publish_chapters(ws, template_tree, [label])
            artifacts.extend(outcome["published"])
            deliverable_path = outcome["published"][0] if outcome["published"] else None
    status = "ok" if counts.get("gap", 0) == 0 and not pending else "partial"
    if pending:
        pending_path = ws / "plan" / "AGENT待完成.md"
        pending_path.write_text(
            "# Agent 待完成节点\n\n" +
            "\n".join("- %s：读取任务单、全文证据和章节规范，完成正文后再运行 assemble/check。" %
                      item["key"] for item in pending) + "\n", encoding="utf-8")
        artifacts.append(str(pending_path))
    return {"command": "author", "status": status, "artifacts": artifacts,
            "summary": {"scope": scope["label"], "targets": len(keys), "modes": counts,
                        "chapters": str(assemble_path) if assemble_path else None,
                        "deliverable": deliverable_path},
            "results": results,
            "diagnostics": ["scope_unresolved: %s" % scope["unresolved"]] if scope["unresolved"] else []}


# ------------------------------------------------------------------ resumable pipeline
def cmd_run(args):
    """同一进程内执行 plan → author → check，复用缓存并保留断点续跑语义。"""
    planned = cmd_plan(args)
    refresh_requested = bool(getattr(args, "refresh_cache", False))
    if refresh_requested:
        args.refresh_cache = False
    try:
        authored = cmd_author(args)
    finally:
        if refresh_requested:
            args.refresh_cache = True
    checked = cmd_check(args)
    statuses = {planned.get("status"), authored.get("status"), checked.get("status")}
    if "error" in statuses:
        status = "error"
    elif "conflict" in statuses:
        status = "conflict"
    elif "partial" in statuses:
        status = "partial"
    else:
        status = "ok"
    artifacts, seen = [], set()
    for payload in (planned, authored, checked):
        for path in payload.get("artifacts", []):
            if path not in seen:
                seen.add(path)
                artifacts.append(path)
    diagnostics = []
    for payload in (planned, authored, checked):
        diagnostics.extend(payload.get("diagnostics", []))
    return {"command": "run", "status": status, "artifacts": artifacts,
            "summary": {"scope": args.scope,
                        "plan": planned.get("summary", {}),
                        "author": authored.get("summary", {}),
                        "check": checked.get("summary", {})},
            "stages": {"plan": planned.get("status"),
                       "author": authored.get("status"),
                       "check": checked.get("status")},
            "diagnostics": diagnostics}


# ------------------------------------------------------------------ 交付
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _deliverable_stem(node, label):
    """成品文件名：`<编号> <标题>`；拿不到标题时退回 scope 标签。"""
    number = str((node or {}).get("number") or label or "all").strip()
    title = str((node or {}).get("title") or "").strip()
    stem = ("%s %s" % (number, title)).strip() if title else number
    stem = re.sub(r"\s+", " ", _UNSAFE_NAME.sub("-", stem)).strip(" .")
    return stem or "all"


def _assembly_provenance(ws, chapter):
    meta = ws / "template" / "\u9879\u76ee\u76ee\u5f55\u5143\u6570\u636e.json"
    if not meta.exists():
        return {}
    return {"project_tree_sha256": sha256_file(ws / "template" / "\u9879\u76ee\u76ee\u5f55\u6811.json"),
            "source_sha256": sha256_file(ws / "source" / "blocks.json"),
            "chapter_sha256": sha256_file(chapter)}


def _validate_publication(ws, labels):
    if not (ws / "template" / "\u9879\u76ee\u76ee\u5f55\u5143\u6570\u636e.json").exists():
        return
    for label in labels:
        chapter = ws / "chapters" / ("%s.md" % label)
        if not chapter.exists():
            continue
        sidecar = load_json(ws / "chapters" / ("%s.sidecar.json" % label), default={}) or {}
        expected = _assembly_provenance(ws, chapter)
        if any(sidecar.get(key) != value for key, value in expected.items()):
            raise AppError("Stale assembly: rerun assemble --scope %s" % label, status="conflict")


_ASSET_REF = re.compile(r"!\[[^\]]*\]\(\s*assets/([^)\s]+)")


def publish_assets(ws, markdown_path, out_dir):
    """把成品 Markdown 引用的 assets/ 图片同步到交付目录，避免成品图裂。"""
    text = Path(markdown_path).read_text(encoding="utf-8")
    names, seen = [], set()
    for match in _ASSET_REF.finditer(text):
        name = match.group(1).strip().strip("<>")
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    if not names:
        return [], []
    folders = [item for item in sorted(Path(ws).glob("*/assets")) if item.is_dir()]
    asset_dir = Path(out_dir) / "assets"
    copied, missing = [], []
    for name in names:
        if "/" in name or "\\" in name or name in (".", ".."):
            missing.append(name)
            continue
        source = next((folder / name for folder in folders if (folder / name).is_file()), None)
        if source is None:
            missing.append(name)
            continue
        asset_dir.mkdir(parents=True, exist_ok=True)
        dest = asset_dir / name
        if not dest.exists() or sha256_file(dest) != sha256_file(source):
            shutil.copyfile(source, dest)
        copied.append(name)
    return copied, missing


def publish_chapters(ws, template_tree, labels):
    """把 <ws>/chapters/<label>.md 发布到 <项目根>/可研成果/<编号> <标题>.md，并同步引用的图片。"""
    _validate_publication(ws, labels)
    out_dir = deliverable_dir(ws)
    out_dir.mkdir(parents=True, exist_ok=True)
    published, missing, assets, missing_assets = [], [], [], []
    for label in labels:
        source = ws / "chapters" / ("%s.md" % label)
        if not source.exists():
            missing.append(str(label))
            continue
        dest = out_dir / ("%s.md" % _deliverable_stem(node_by_number(template_tree, label), label))
        if dest.resolve() != source.resolve():
            shutil.copyfile(source, dest)
        published.append(str(dest))
        copied, absent = publish_assets(ws, dest, out_dir)
        assets.extend(name for name in copied if name not in assets)
        missing_assets.extend(name for name in absent if name not in missing_assets)
    return {"published": published, "missing": missing,
            "assets": assets, "missing_assets": missing_assets}


# ------------------------------------------------------------------ assemble
def cmd_assemble(args):
    ws = _ws(args)
    template_tree = _load_tree(ws, "template")
    scope = parse_scope(args.scope, template_tree)
    markdown, used = render_scope_markdown(ws, template_tree, scope["keys"])
    label = slug(args.output or scope["label"] or "all")
    path = ws / "chapters" / ("%s.md" % label)
    path.write_text(markdown, encoding="utf-8")
    sidecar = ws / "chapters" / ("%s.sidecar.json" % label)
    dump_json(sidecar, {"scope": scope, "used_drafts": used,
                        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                        **_assembly_provenance(ws, path)})
    published, assets = [], []
    if not getattr(args, "no_publish", False):
        outcome = publish_chapters(ws, template_tree, [label])
        published, assets = outcome["published"], outcome["assets"]
    return {"command": "assemble", "status": "ok",
            "artifacts": [str(path), str(sidecar)] + published,
            "summary": {"scope": scope["label"], "chars": len(markdown), "drafts_used": len(used),
                        "targets": len(scope["keys"]), "deliverables": published,
                        "assets": len(assets)},
            "diagnostics": []}


# ------------------------------------------------------------------ check
def cmd_check(args):
    ws = _ws(args)
    specs = _specs(args)
    template_tree = _load_tree(ws, "template")
    scope = parse_scope(args.scope, template_tree)
    if not scope["keys"]:
        return {"command": "check", "status": "partial", "artifacts": [],
                "summary": {"scope": scope["label"], "targets": 0},
                "diagnostics": ["scope_unresolved: 未匹配到节点：%s" % (scope["unresolved"] or args.scope)],
                "measurements": [], "next_actions": ["用 tree 命令确认章节编号或节点 key"]}
    payload = check_scope(ws, template_tree, scope["keys"], specs)
    anchors = (load_json(ws / "template" / "\u9879\u76ee\u76ee\u5f55\u5143\u6570\u636e.json", default={}) or {}).get("anchors") or {}
    if anchors:
        source_hash = sha256_file(ws / "source" / "blocks.json")
        for item in payload.get("measurements", []):
            key = item["key"]
            if key not in anchors or not item.get("draft"):
                continue
            sidecar = load_json(ws / "drafts" / ("%s.sidecar.json" % key), default={}) or {}
            if (sidecar.get("source_sha256") != source_hash or
                    (sidecar.get("source") or {}).get("key") != anchors[key]["source"]):
                payload["diagnostics"].append({"key": key,
                    "diagnostic": "project_source_mismatch: rerun author --force"})
                payload["status"] = "conflict"
    payload["command"] = "check"
    payload["summary"]["scope"] = scope["label"]
    limit = max(1, int(getattr(args, "limit", 40) or 40))
    measurements = payload.get("measurements", [])
    diagnostics = payload.get("diagnostics", [])
    problem_keys = {item["key"] for item in diagnostics}
    kept = [item for item in measurements if item.get("key") in problem_keys]
    for item in measurements:
        if len(kept) >= limit:
            break
        if item not in kept:
            kept.append(item)
    payload["summary"]["measurements_total"] = len(measurements)
    payload["summary"]["diagnostics_total"] = len(diagnostics)
    payload["summary"]["truncated"] = (len(measurements) > len(kept)) or (len(diagnostics) > limit)
    payload["measurements"] = kept[:limit]
    payload["diagnostics"] = diagnostics[:limit]
    report_json = ws / "reports" / ("%s.校验.json" % slug(scope["label"] or "all"))
    dump_json(report_json, payload)
    payload["artifacts"] = list(payload.get("artifacts", [])) + [str(report_json)]
    return payload


# ------------------------------------------------------------------ report
def cmd_report(args):
    ws = _ws(args)
    template_tree = _load_tree(ws, "template")
    specs = _specs(args)
    rows, gaps = [], []
    for node in iter_nodes(template_tree["chapters"]):
        draft = ws / "drafts" / ("%s.md" % node["key"])
        skeleton = ws / "drafts" / ("%s.骨架.md" % node["key"])
        if not draft.exists() and not skeleton.exists():
            continue
        sidecar_path = ws / "drafts" / ("%s.sidecar.json" % node["key"])
        sidecar = load_json(sidecar_path, {}) if sidecar_path.exists() else {}
        text = (draft if draft.exists() else skeleton).read_text(encoding="utf-8")
        from .authoring import count_chars, content_chars
        rows.append({"key": node["key"], "number": node["number"], "title": node["title"],
                     "mode": sidecar.get("mode", "skeleton"), "chars": count_chars(text),
                     "content_chars": content_chars(text),
                     "source": (sidecar.get("source") or {}).get("title", ""),
                     "spec": (sidecar.get("spec") or {}).get("title", "")})
    for node in iter_nodes(template_tree["chapters"]):
        draft = ws / "drafts" / ("%s.md" % node["key"])
        if not draft.exists():
            continue
        text = draft.read_text(encoding="utf-8")
        for match in re.finditer(r"GAP[:：]\s*([^\n。]{0,60})", text):
            gaps.append({"key": node["key"], "gap": match.group(1).strip()})
    lines = ["# 可研编写进度", "", "已产出草稿 %d 个节点" % len(rows), "",
             "| 节点 | 编号 | 标题 | 模式 | 字数 | 有效字数 | 来源 |", "|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append("| %s | %s | %s | %s | %d | %d | %s |" % (
            row["key"], row["number"], row["title"].replace("|", "/"), row["mode"],
            row["chars"], row["content_chars"], row["source"].replace("|", "/")))
    if gaps:
        lines.extend(["", "## 缺口清单（GAP）", ""])
        for gap in gaps:
            lines.append("- %s：%s" % (gap["key"], gap["gap"]))
    report_md = ws / "reports" / "编写进度.md"
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    dump_json(ws / "reports" / "编写进度.json",
              {"rows": rows, "gaps": gaps, "generated_at": datetime.datetime.now().isoformat(timespec="seconds")})
    return {"command": "report", "status": "ok", "artifacts": [str(report_md)],
            "summary": {"drafted": len(rows), "gaps": len(gaps),
                        "chars": sum(row["chars"] for row in rows),
                        "content_chars": sum(row["content_chars"] for row in rows)},
            "diagnostics": []}


# ------------------------------------------------------------------ search / kb
def cmd_search(args):
    ws = _ws(args)
    root = Path(args.dir) if args.dir else (ws / "source")
    results = search_dir(root, args.query, top_k=args.top_k, exact_only=bool(args.exact_only),
                         cache_dir=ws / "cache",
                         refresh=bool(getattr(args, "refresh_cache", False)))
    return {"command": "search", "status": "ok", "artifacts": [],
            "summary": {"query": args.query, "dir": str(root), "hits": len(results)},
            "results": results, "diagnostics": []}


def cmd_kb(args):
    kb_root = find_kb_root(skill_root())
    if kb_root is None:
        return {"command": "kb", "status": "partial", "artifacts": [],
                "summary": {"kb_root": None}, "diagnostics": ["kb_root_missing"]}
    if args.list:
        names = list_libraries(kb_root)
        return {"command": "kb", "status": "ok", "artifacts": [],
                "summary": {"kb_root": str(kb_root), "libraries": names}, "diagnostics": []}
    ws = _ws(args)
    result = kb_search(kb_root, args.query, kb_names=args.kb.split(",") if args.kb else None,
                       top_k=args.top_k, cache_dir=ws / "cache",
                       refresh=bool(getattr(args, "refresh_cache", False)))
    hits = result.get("hits", [])
    if hits and args.save:
        target = ws / "normalized" / ("KB-%s.md" % slug(args.query, limit=30))
        lines = ["# KB 命中 · %s" % args.query, "", "来源：%s（backend=%s）" % (kb_root, result.get("backend")), ""]
        for hit in hits:
            lines.append("- **%s**%s（score=%s）" % (hit.get("source", ""),
                                                     (" p%s" % hit["page"]) if hit.get("page") else "",
                                                     hit.get("score")))
            lines.append("  %s" % (hit.get("content") or "").replace("\n", " ")[:400])
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        target = None
    status = "ok" if hits else "partial"
    return {"command": "kb", "status": status, "artifacts": [str(target)] if target else [],
            "summary": {"kb_root": str(kb_root), "backend": result.get("backend"), "hits": len(hits),
                        "saved": str(target) if target else None},
            "results": hits, "diagnostics": result.get("diagnostics", [])}


# ------------------------------------------------------------------ link
def cmd_link(args):
    """手工锚点：把模板节点钉到指定建设方案节点（最高优先级，覆盖归属仲裁）。"""
    ws = _ws(args)
    path = ws / "match" / "来源覆盖.json"
    overrides = _manual_overrides(ws)
    if args.remove or (args.node and not args.source and not args.list):
        targets = [item for item in (args.node or "").split(",") if item] or sorted(overrides)
        removed = [key for key in targets if overrides.pop(key, None) is not None]
        dump_json(path, overrides)
        return {"command": "link", "status": "ok", "artifacts": [str(path)],
                "summary": {"removed": removed, "remaining": len(overrides)}, "diagnostics": []}
    if args.list or not args.node:
        rows = [{"node": key, **value} for key, value in sorted(overrides.items())]
        auto = _auto_overrides(ws)
        diagnostics = []
        if auto:
            uncovered = [key for key in auto if key not in overrides]
            diagnostics.append("auto_anchors: 另有 %d 个自动锚点生效（match/自动锚点.json，"
                               "其中 %d 个未被人工锚点覆盖）；anchor --review 看待判读清单"
                               % (len(auto), len(uncovered)))
        return {"command": "link", "status": "ok", "artifacts": [str(path)],
                "summary": {"count": len(rows), "overrides_path": str(path),
                            "auto_count": len(auto)},
                "results": rows, "diagnostics": diagnostics}
    template_tree = _load_tree(ws, "template")
    node = node_by_key(template_tree, args.node) or node_by_number(template_tree, args.node)
    if node is None:
        matches = find_nodes(template_tree, args.node)
        node = matches[0] if matches else None
    if node is None:
        raise AppError("模板节点不存在：%s（用 tree --role template --grep 查 key）" % args.node,
                       status="partial")
    source_tree, blocks, _assets = load_source(ws)
    index = SourceIndex(source_tree, blocks)
    entry = index.by_key.get(args.source)
    if entry is None:
        found = node_by_number(source_tree, args.source or "")
        if found is None:
            matches = find_nodes(source_tree, args.source or "")
            found = matches[0] if matches else None
        if found is not None:
            entry = index.by_key.get(found["key"])
    if entry is None:
        raise AppError("建设方案节点不存在：%s（用 tree --role source --grep 查 key）" % args.source,
                       status="partial")
    diagnostics = []
    if args.mode:
        mode = args.mode
    elif entry["norm_title"] == node["norm_title"] and not node.get("children"):
        mode = "copy"                      # 同名叶子：整段直复
    elif not entry["children_count"]:
        mode = "migrate"                   # 叶子来源：整段迁移后按规范补足
    else:
        mode = "write"                     # 容器来源：只作素材范围，避免把子节点内容重复搬入
        diagnostics.append("container_source: %s 是容器节点（%d 个子节点），默认按素材范围撰写；"
                           "确需整段搬运用 --mode migrate"
                           % (entry["key"], entry["children_count"]))
    overrides[node["key"]] = {"source": entry["key"], "mode": mode, "note": args.note or "",
                              "source_title": entry["title"], "source_number": entry["number"],
                              "updated_at": datetime.datetime.now().isoformat(timespec="seconds")}
    dump_json(path, overrides)
    return {"command": "link", "status": "ok", "artifacts": [str(path)],
            "summary": {"node": node["key"], "node_title": node["title"], "mode": mode,
                        "source": entry["key"], "source_title": entry["title"],
                        "total": len(overrides)},
            "results": [{"node": node["key"], "source": entry["key"], "mode": mode}],
            "diagnostics": diagnostics}


# ------------------------------------------------------------------ anchor
def _anchor_decisions_path(ws, value):
    """判读文件路径：空值用默认 match/锚点判读.json，相对路径按工作区解析。"""
    if not value:
        return Path(ws) / "match" / "锚点判读.json"
    path = Path(value)
    return path if path.is_absolute() else Path(ws) / path


def _anchor_scope_node(tree, token, label):
    node = node_by_number(tree, token) or node_by_key(tree, token)
    if node is None:
        matches = find_nodes(tree, token)
        node = matches[0] if matches else None
    if node is None:
        raise AppError("%s节点不存在：%s" % (label, token), status="partial")
    return node


def _number_key(number):
    return tuple(int(piece) for piece in str(number or "").split(".") if piece.isdigit())


def cmd_anchor(args):
    """自动锚点（方案 A 保序 + B 最优分配）：低置信度交方案 D 判读，再 --apply 回填。"""
    ws = _ws(args)
    auto_path = ws / "match" / "自动锚点.json"
    review_path = ws / "reports" / "锚点复核.md"
    decisions_path = _anchor_decisions_path(ws, getattr(args, "apply", None))
    artifacts, diagnostics = [], []
    stored = load_json(auto_path, default={}) or {}      # 还没派生过时为空，不当错误

    if args.review and args.apply is None:      # 只读：回放已落盘结果，不重算
        if not stored:
            raise AppError("还没有自动锚点：先运行 anchor --scope <模板域> --from <建设方案域>",
                           status="partial")
        review, summary = stored.get("review") or [], stored.get("summary") or {}
        review_path.write_text(render_anchor_review(review, summary,
                                                    decisions_path=str(decisions_path),
                                                    apply_cmd="anchor --apply"),
                               encoding="utf-8")
        return {"command": "anchor", "status": "ok" if not review else "partial",
                "artifacts": [str(review_path), str(auto_path)],
                "summary": dict(summary, mode="review", dry_run=True),
                "results": review, "diagnostics": diagnostics}

    # --apply 不带 scope 时沿用上次派生记录的域，免得复核人再抄一遍参数
    if args.apply is not None and not args.scope:
        if not stored:
            raise AppError("还没有自动锚点：先运行 anchor --scope <模板域> --from <建设方案域>",
                           status="partial")
        args.scope = stored.get("scope")
        args.source_scope = args.source_scope or stored.get("from")
        if stored.get("depth"):
            args.depth = stored["depth"]
        diagnostics.append("reuse_stored: 沿用上次派生的 %s ↔ %s（depth=%s）"
                           % (stored.get("scope"), stored.get("from"), stored.get("depth")))
    if not args.scope:
        raise AppError("缺少 --scope：要派生的模板域，如 anchor --scope 5.6 --from 9", status="partial")
    template_tree = _load_tree(ws, "template")
    source_tree, _blocks, _assets = load_source(ws)
    scope = parse_scope(args.scope, template_tree)
    if not scope["keys"]:
        raise AppError("scope 未匹配到模板节点：%s" % args.scope, status="partial")
    if len(scope["keys"]) > 1:
        raise AppError("自动锚点一次只对一个域：%s 匹配到 %d 个节点，请写到单个小节"
                       % (args.scope, len(scope["keys"])), status="partial")
    template_root = node_by_key(template_tree, scope["keys"][0])

    if args.source_scope:
        source_root = _anchor_scope_node(source_tree, args.source_scope, "建设方案")
    else:
        ranked = autodetect_source_parent(template_root, source_tree)
        if not ranked:
            raise AppError("没找到与 %s 对得上的建设方案域：请用 --from 指定" % template_root["number"],
                           status="partial")
        best = ranked[0]
        source_root = node_by_number(source_tree, best["number"])
        diagnostics.append("auto_source: 未给 --from，自动选定建设方案域 %s %s（配对 %d 个、平均 %.3f）"
                           % (best["number"], best["title"], best["pairs"], best["mean"]))

    manual = _manual_overrides(ws)
    excludes = set(manual) | {item for item in (args.exclude or "").split(",") if item}
    origins = {key: value.get("source") for key, value in manual.items() if value.get("source")}
    if manual:
        diagnostics.append("manual_priority: %d 个人工锚点优先，不参与自动派生" % len(manual))

    decisions = {}
    if args.apply is not None:
        decisions = load_json(decisions_path, default={})
        if not decisions:
            raise AppError("判读文件不存在：%s（先按 reports/锚点复核.md 写出判读结论）" % decisions_path,
                           status="partial")
    if decisions:
        anchors, review, summary = apply_decisions(template_root, source_root, decisions,
                                                   depth=args.depth, excludes=excludes,
                                                   origins=origins)
        diagnostics.extend(summary.pop("decision_diagnostics", None) or [])
    else:
        anchors, review, summary = derive_anchors(template_root, source_root, depth=args.depth,
                                                  excludes=excludes, origins=origins)

    summary.update({"scope_title": template_root["title"], "from_title": source_root["title"],
                    "manual_anchors": len(manual)})
    payload = {"schema": 1,
               "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
               "scope": template_root["number"], "from": source_root["number"],
               "depth": args.depth, "anchors": anchors, "review": review, "summary": summary}
    if not args.dry_run:
        dump_json(auto_path, payload)
        review_path.write_text(render_anchor_review(review, summary,
                                                    decisions_path=str(decisions_path),
                                                    apply_cmd="anchor --apply"),
                               encoding="utf-8")
        artifacts.extend([str(auto_path), str(review_path)])
    rows = [{"node": key, **value} for key, value in
            sorted(anchors.items(), key=lambda item: _number_key(item[1].get("source_number")))]
    limit = max(int(getattr(args, "limit", 40) or 40), 0)
    return {"command": "anchor", "status": "ok" if not review else "partial",
            "artifacts": artifacts,
            "summary": dict(summary, mode="derive", dry_run=bool(args.dry_run),
                            auto_anchors=str(auto_path), review_report=str(review_path),
                            decisions=str(decisions_path) if decisions else None),
            "results": rows[:limit], "review": review[:limit], "diagnostics": diagnostics}


# ------------------------------------------------------------------ verify
def cmd_verify(args):
    """最小自检：确认 skill 依赖与核心模块可用（不写工作区）。"""
    checks = []
    checks.append({"name": "python", "ok": True, "detail": "ok"})
    try:
        import docx  # noqa: F401
        checks.append({"name": "python-docx", "ok": True, "detail": "ok"})
    except ImportError as exc:
        checks.append({"name": "python-docx", "ok": False, "detail": str(exc)})
    root = skill_root()
    checks.append({"name": "references", "ok": (root / "references" / "chapter-writing").is_dir(),
                   "detail": str(root / "references" / "chapter-writing")})
    outline = root / "references" / "template-outline" / "可研报告目录骨架.md"
    checks.append({"name": "builtin-template", "ok": outline.is_file(), "detail": str(outline)})
    specs = Specs(root)
    checks.append({"name": "specs", "ok": len(specs.chapters) >= 7,
                   "detail": "chapters=%s" % specs.chapter_numbers()})
    kb_root = find_kb_root(root)
    checks.append({"name": "kb", "ok": kb_root is not None,
                   "detail": str(kb_root) if kb_root else "未找到 consulting-kb-retrieval（可离线运行，KB 检索降级）"})
    ok = all(item["ok"] for item in checks if item["name"] in
             ("python", "python-docx", "references", "builtin-template"))
    ws = resolve_workspace(getattr(args, "workspace", None))
    return {"command": "verify", "status": "ok" if ok else "partial", "artifacts": [],
            "summary": {"skill_root": str(root), "checks": len(checks),
                        "failed": [c["name"] for c in checks if not c["ok"]],
                        "deliverable_dir": str(deliverable_dir(ws)),
                        "temp_script_dir": str(temp_script_dir(ws))},
            "results": checks, "diagnostics": []}


# ------------------------------------------------------------------ publish
def cmd_publish(args):
    """把装配稿发布到项目根的「可研成果/」，用 `<编号> <标题>` 命名，方便用户直接翻看。"""
    ws = _ws(args)
    template_tree = _load_tree(ws, "template")
    chapters_dir = ws / "chapters"
    if getattr(args, "scope", None):
        scope = parse_scope(args.scope, template_tree)
        labels = [slug(scope["label"])] if scope["label"] else []
    else:
        labels = sorted(path.stem for path in chapters_dir.glob("*.md"))
    outcome = publish_chapters(ws, template_tree, labels)
    published, missing = outcome["published"], outcome["missing"]
    diagnostics = []
    if not labels:
        diagnostics.append("no_chapters: %s 下还没有装配稿，先跑 assemble 或 author" % chapters_dir)
    diagnostics.extend("missing_chapter: %s" % label for label in missing)
    diagnostics.extend("missing_asset: %s" % name for name in outcome["missing_assets"])
    return {"command": "publish", "status": "ok" if published else "partial",
            "artifacts": published,
            "summary": {"deliverable_dir": str(deliverable_dir(ws)),
                        "published": len(published), "requested": len(labels),
                        "assets": len(outcome["assets"])},
            "diagnostics": diagnostics}


# ------------------------------------------------------------------ clean
def cmd_clean(args):
    """删除项目根的「临时脚本/」目录（收尾清理）；成品目录与工作区都不动。"""
    ws = _ws(args)
    target = temp_script_dir(ws)
    expected = project_root(ws) / TEMP_SCRIPT_DIRNAME
    if target.resolve() != expected.resolve() or target.resolve() == project_root(ws).resolve():
        raise AppError("拒绝删除非预期路径：%s" % target, status="conflict")
    existed = target.is_dir()
    removed_files = 0
    if existed:
        children = sorted(target.rglob("*"), key=lambda item: len(item.parts), reverse=True)
        for path in children:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()
                removed_files += 1
        target.rmdir()
    return {"command": "clean", "status": "ok", "artifacts": [],
            "summary": {"temp_script_dir": str(target), "existed": existed,
                        "removed_files": removed_files,
                        "deliverable_dir": str(deliverable_dir(ws))},
            "diagnostics": []}
