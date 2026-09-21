"""草稿校验：规范覆盖、篇幅、空标题、锚点/缺口、复制完整性、跨节重复。"""
import hashlib
import re
from pathlib import Path

from .authoring import strip_comments
from .jsonio import load_json
from .specs import coverage, node_requirements, spec_keywords
from .tree import node_by_key

_HEADING = re.compile(r"^(#{1,9})\s+(.*)$")
_DUP_MIN = 40


def _headings(text):
    result = []
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            result.append((len(match.group(1)), match.group(2).strip()))
    return result


def _empty_headings(text):
    lines = [line for line in strip_comments(text).splitlines()]
    empty = []
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if not match:
            continue
        level = len(match.group(1))
        has_content = False
        for next_line in lines[index + 1:]:
            next_heading = _HEADING.match(next_line)
            if next_heading:
                if len(next_heading.group(1)) <= level:
                    break
                has_content = True
                continue
            if next_line.strip():
                has_content = True
                break
        if not has_content:
            empty.append(match.group(2).strip())
    return empty


def _sha256(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _reuse_missing(body, paragraphs):
    """复用段落是否原文保留：正文里找不到该段（或 sha256 不符）即视为被改写。"""
    flat = re.sub(r"\s+", "", body or "")
    missing = []
    for item in paragraphs or []:
        normalized = re.sub(r"\s+", "", item.get("text") or "")
        if not normalized:
            continue
        if normalized not in flat or _sha256(normalized) != item.get("sha256"):
            missing.append(item)
    return missing


def check_draft(ws, node, spec, *, drafts_dir=None, sidecars=None):
    ws = Path(ws)
    drafts_dir = Path(drafts_dir or (ws / "drafts"))
    path = drafts_dir / ("%s.md" % node["key"])
    sidecar_path = drafts_dir / ("%s.sidecar.json" % node["key"])
    diagnostics = []
    measurements = {"key": node["key"], "title": node["title"], "number": node["number"]}
    if not path.exists():
        skeleton = drafts_dir / ("%s.骨架.md" % node["key"])
        return {"status": "partial", "measurements": {**measurements, "draft": False,
                                                      "skeleton": skeleton.exists()},
                "diagnostics": ["draft_missing: 尚无草稿（骨架%s）" % ("已生成" if skeleton.exists() else "未生成")]}
    text = path.read_text(encoding="utf-8")
    body = strip_comments(text)
    chars = len(re.sub(r"\s+", "", body))
    gap_count = len(re.findall(r"GAP[:：]", body))
    todo_count = len(re.findall(r"待写|TODO|待补", text))
    headings = _headings(body)
    empty_headings = _empty_headings(text)
    measurements.update({"draft": True, "chars": chars, "headings": len(headings),
                         "gap": gap_count, "todo": todo_count, "empty_headings": empty_headings[:10]})
    if sidecar_path.exists():
        sidecar = load_json(sidecar_path)
        measurements["mode"] = sidecar.get("mode")
        measurements["source"] = (sidecar.get("source") or {}).get("key")
        if (sidecar.get("mode") in ("exact_direct_copy", "semantic_migrate", "title_migrate")
                or sidecar.get("reuse_kind") == "migrate"):
            if _sha256(body.strip()) != sidecar.get("integrity_sha256"):
                diagnostics.append("copy_modified: 直复正文与来源子树哈希不一致（可能被改写）")
        if sidecar.get("mode") in ("paragraph_reuse", "material_reuse"):
            paragraphs = (sidecar.get("reuse") or {}).get("paragraphs") or []
            missing = _reuse_missing(body, paragraphs)
            measurements["reuse_paragraphs"] = len(paragraphs)
            measurements["reuse_missing"] = len(missing)
            if missing:
                diagnostics.append("reuse_modified: %d 段复用原文被改写或丢失（示例：%s）"
                                   % (len(missing),
                                      "；".join((item.get("text") or "")[:20] for item in missing[:3])))
    if empty_headings:
        diagnostics.append("empty_heading: %d 个标题下无正文（示例：%s）"
                           % (len(empty_headings), "；".join(empty_headings[:3])))
    if todo_count:
        diagnostics.append("todo_remaining: 仍有 %d 处待写标记" % todo_count)
    if gap_count:
        diagnostics.append("gap_present: %d 处 GAP 待确认（GAP 句不计入有效篇幅）" % gap_count)
    if spec:
        requirements = node_requirements(node, spec)
        policy_only = "cross-project override" in (spec.get("text") or "").lower()
        keywords = [] if policy_only else spec_keywords(spec)
        if keywords:
            fit = coverage(body, keywords, limit=40)
            measurements["spec_coverage"] = fit["score"]
            measurements["spec_miss"] = fit["miss"][:12]
            if fit["score"] < 0.5:
                diagnostics.append("spec_coverage_low: 规范要素覆盖 %.2f（缺：%s）"
                                   % (fit["score"], "、".join(fit["miss"][:6])))
        min_chars = requirements.get("min_chars") or 0
        if min_chars and chars < min_chars:
            diagnostics.append("below_floor: 正文 %d 字 < 规范提示 %d 字" % (chars, min_chars))
        for table in requirements.get("required_tables") or []:
            if table["name"] not in body:
                diagnostics.append("missing_table: 缺 %s（列：%s）" % (table["name"], "/".join(table["columns"])))
    status = "ok"
    if any(item.startswith(("draft_missing", "copy_modified", "reuse_modified", "empty_heading",
                             "below_floor", "todo_remaining")) for item in diagnostics):
        status = "partial"
    return {"status": status, "measurements": measurements, "diagnostics": diagnostics}


def check_scope(ws, tree, keys, specs, *, index=None):
    ws = Path(ws)
    reports = []
    drafts_dir = ws / "drafts"
    target_nodes = []
    for key in keys:
        node = node_by_key(tree, key)
        if node is None:
            continue
        _collect(node, target_nodes, drafts_dir)
    for node in target_nodes:
        spec = specs.spec_for_node(node) if specs else None
        reports.append(check_draft(ws, node, spec, drafts_dir=drafts_dir))

    duplicates = _cross_duplicates(drafts_dir, [node["key"] for node in target_nodes])
    summary = {
        "nodes": len(reports),
        "drafted": sum(1 for report in reports if report["measurements"].get("draft")),
        "missing": sum(1 for report in reports if not report["measurements"].get("draft")),
        "chars": sum(report["measurements"].get("chars", 0) for report in reports),
        "gaps": sum(report["measurements"].get("gap", 0) for report in reports),
        "todos": sum(report["measurements"].get("todo", 0) for report in reports),
        "mode_counts": {},
    }
    for report in reports:
        mode = report["measurements"].get("mode")
        if mode:
            summary["mode_counts"][mode] = summary["mode_counts"].get(mode, 0) + 1
    diagnostics = [{"key": report["measurements"]["key"], "diagnostic": item}
                   for report in reports for item in report["diagnostics"]]
    diagnostics.extend({"key": "duplication", "diagnostic": item} for item in duplicates)
    status = "ok"
    if any(item["diagnostic"].startswith(("draft_missing", "copy_modified", "reuse_modified",
                                          "empty_heading", "below_floor", "todo_remaining"))
           for item in diagnostics):
        status = "partial"
    if any(item["diagnostic"].startswith("verbatim_copy") for item in diagnostics):
        status = "conflict"
    next_actions = []
    if summary["missing"]:
        next_actions.append("author --scope %s：为缺失节点生成草稿" % ",".join(keys))
    if summary["todos"]:
        next_actions.append("按任务单补写 TODO 段（第一轮写全写足）")
    if summary["gaps"]:
        next_actions.append("GAP 项查知识库/网络补证据，或标注待确认")
    return {
        "status": status,
        "artifacts": [],
        "summary": summary,
        "measurements": [report["measurements"] for report in reports],
        "diagnostics": diagnostics,
        "next_actions": next_actions,
    }


def _collect(node, bucket, drafts_dir):
    """容器节点由子节点装配；只有叶子节点（或有草稿的容器）才参与校验。"""
    has_draft = (Path(drafts_dir) / ("%s.md" % node["key"])).exists()
    if not node["children"] or has_draft:
        bucket.append(node)
    if has_draft:
        return
    for child in node["children"]:
        _collect(child, bucket, drafts_dir)


def _cross_duplicates(drafts_dir, keys, *, min_chars=_DUP_MIN):
    seen = {}
    diagnostics = []
    for key in keys:
        path = Path(drafts_dir) / ("%s.md" % key)
        if not path.exists():
            continue
        body = strip_comments(path.read_text(encoding="utf-8"))
        for line in body.splitlines():
            stripped = re.sub(r"\s+", "", line)
            if len(stripped) < min_chars:
                continue
            if stripped in seen and seen[stripped] != key:
                diagnostics.append("verbatim_copy: %s 与 %s 存在 ≥%d 字逐字重复" % (key, seen[stripped], min_chars))
            else:
                seen.setdefault(stripped, key)
    return diagnostics
