"""正文生成：同名直复 / 语义迁移 / 证据撰写任务包 / 章节装配。"""
import datetime
import hashlib
import re
from .cache import sha256_file
from .jsonio import AppError, dump_json, load_json
from .markdown import blocks_to_markdown
from .matching import SourceIndex
from .headings import normalize_title
from .specs import coverage, node_requirements, spec_keywords, spec_payload, spec_requirements
from .template_outline import ensure_builtin_template
from .tree import node_by_key, subtree_blocks, tree_from_dict
from .workspace import ensure

COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
ANCHOR_RE = re.compile(r"〔(?:SRC|KB|WEB)-[A-Za-z0-9][A-Za-z0-9\-]*〕")
GAP_RE = re.compile(r"GAP[:：]")
TODO_RE = re.compile(r"(待写|TODO|待补|待补写)")


def strip_comments(text):
    return COMMENT_RE.sub("", text or "")


def count_chars(text):
    return len(re.sub(r"\s+", "", strip_comments(text or "")))


def content_chars(text):
    """扣除 GAP/TODO 行后的有效正文字数。"""
    lines = []
    for line in strip_comments(text or "").splitlines():
        stripped = line.strip()
        if not stripped or GAP_RE.search(stripped) or stripped.startswith(("<!--", "TODO", "待写")):
            continue
        lines.append(stripped)
    return len(re.sub(r"\s+", "", "".join(lines)))


def load_source(ws):
    ws = ensure(ws)
    tree_path = ws / "source" / "目录树.json"
    blocks_path = ws / "source" / "blocks.json"
    if not tree_path.exists() or not blocks_path.exists():
        raise AppError("建设方案尚未扫描：先运行 scan --role source --input <建设方案.docx>", status="partial")
    tree = tree_from_dict(load_json(tree_path))
    blocks = load_json(blocks_path)["blocks"]
    assets = load_json(ws / "source" / "assets.json", {})
    return tree, blocks, assets


def load_template(ws):
    ws = ensure(ws)
    tree_path = ws / "template" / "目录树.json"
    if not tree_path.exists():
        ensure_builtin_template(ws)
    return tree_from_dict(load_json(tree_path))


def source_index(ws):
    tree, blocks, assets = load_source(ws)
    return SourceIndex(tree, blocks), assets


def _sha256(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _replace_first_heading(markdown, title):
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            lines[index] = "#" * level + " " + title
            break
    return "\n".join(lines)


def _header_comment(fields):
    payload = " ".join("%s=%s" % (key, value) for key, value in fields.items() if value not in (None, ""))
    return "<!-- keyan %s -->" % payload


def copy_draft(ws, index, assets, node, decision):
    """同名直复 / 语义迁移：整棵子树复制，标题重挂，不改写。"""
    matched = decision["matched_source"]
    source_node = node_by_key(index.tree, matched["key"])
    if source_node is None:
        raise AppError("来源节点不存在：%s" % matched["key"], status="partial")
    slice_blocks = subtree_blocks(index.blocks, source_node)
    markdown = blocks_to_markdown(slice_blocks, target_level=node["level"], asset_map=assets)
    markdown = _replace_first_heading(markdown, node["title"])
    header = _header_comment({
        "mode": decision["mode"], "source": matched["key"], "source-title": matched["title"],
        "target": node["key"], "spec": (decision.get("spec") or {}).get("path", ""),
    })
    body = header + "\n\n" + markdown
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"
    alternatives = [item for item in (decision.get("candidates") or [])
                    if item.get("key") != matched["key"]][:5]
    sidecar = {
        "key": node["key"], "number": node["number"], "title": node["title"],
        "mode": decision["mode"], "source": dict(matched, role=decision.get("reuse_role", "source")),
        "reuse_kind": decision.get("reuse_kind"),
        "source_alternatives": alternatives,
        "diagnostics": decision.get("diagnostics", []),
        "spec": spec_payload(decision.get("spec")), "reasons": decision.get("reasons", []),
        "spec_coverage": decision.get("spec_coverage"),
        "chars": count_chars(body), "content_chars": content_chars(body),
        "integrity_sha256": _sha256(strip_comments(body).strip()),
        "source_sha256": sha256_file(ws / "source" / "blocks.json"),
        "llm_rewrite": False,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    drafts_dir = ensure(ws) / "drafts"
    md_path = drafts_dir / ("%s.md" % node["key"])
    md_path.write_text(body, encoding="utf-8")
    dump_json(drafts_dir / ("%s.sidecar.json" % node["key"]), sidecar)
    artifacts = [str(md_path), str(drafts_dir / ("%s.sidecar.json" % node["key"]))]
    if decision["mode"] in ("semantic_migrate", "title_migrate", "material_reuse"):
        report_path = drafts_dir / ("%s.对照.md" % node["key"])
        report_path.write_text(migration_report(node, decision, body), encoding="utf-8")
        artifacts.append(str(report_path))
    return {"artifacts": artifacts, "sidecar": sidecar, "markdown": body}


def migration_report(node, decision, body):
    spec = decision.get("spec") or {}
    requirements = node_requirements(node, spec)
    keywords = spec_keywords(spec)
    fit = coverage(strip_comments(body), keywords, limit=40)
    lines = ["# 语义迁移对照报告 · %s %s" % (node["number"], node["title"]), ""]
    migrate = decision.get("migrate_from") or {}
    lines.append("迁移来源：%s %s（标题相似 %.2f，规范贴合 %.2f）" % (
        migrate.get("number", ""), migrate.get("title", ""),
        migrate.get("title_score", 0.0), migrate.get("spec_score", 0.0)))
    lines.append("规范文件：%s" % (spec.get("path") or "未匹配"))
    lines.append("")
    lines.append("## 规范要素命中（%d/%d）" % (len(fit["hit"]), len(fit["hit"]) + len(fit["miss"])))
    lines.append("")
    lines.append("- 已覆盖：" + ("、".join(fit["hit"]) if fit["hit"] else "无"))
    lines.append("- 待补足：" + ("、".join(fit["miss"]) if fit["miss"] else "无"))
    lines.append("")
    lines.extend(_requirements_block(node, spec, body))
    lines.append("## 纪律")
    lines.append("")
    lines.append("- 迁移只做标题重挂与格式适配；不得同义改写、不得润色、不得扩写。")
    lines.append("- 缺失要素按规范补写；无证据处标 GAP，技术推导标 〔推导：依据〕。")
    return "\n".join(lines) + "\n"


def _requirements_block(node, spec, body):
    """规范必写要素 / 必需表格的逐项核对（迁移报告与复用报告共用）。"""
    requirements = node_requirements(node, spec)
    text = strip_comments(body)
    lines = []
    items = requirements.get("required_items") or []
    if items:
        lines.append("## 必写要素逐项核对")
        lines.append("")
        for item in items:
            label = item["text"]
            key = re.split(r"[（(，,、]", label)[0][:20]
            mark = "x" if key and key in text else " "
            lines.append("- [%s] %s" % (mark, label))
        lines.append("")
    tables = requirements.get("required_tables") or []
    if tables:
        lines.append("## 必需表格")
        lines.append("")
        for table in tables:
            present = table["name"] in body
            lines.append("- [%s] %s（列：%s）" % ("x" if present else " ", table["name"],
                                                  "/".join(table["columns"])))
        lines.append("")
    return lines


def reuse_draft(ws, node, decision, spec=None):
    """正文复用：命中段落原文搬运（零改写），多段由 agent 组织顺序与过渡。

    只允许排版：排序、合并、补过渡句。事实、数字、口径不得改写；
    sidecar 逐段记录原文与 sha256，``check`` 按段复核（reuse_modified）。
    """
    reuse = decision.get("reuse") or {}
    refs = reuse.get("refs") or []
    if not refs:
        raise AppError("复用决策缺少命中段落：%s" % node["key"], status="partial")
    spec = spec or decision.get("spec") or {}
    body_text = reuse.get("body") or "\n\n".join(ref.get("text", "") for ref in refs)
    heading = node_heading(node)
    header = _header_comment({
        "mode": decision["mode"], "reuse-source": reuse.get("source", ""),
        "target": node["key"], "spec": spec_payload(spec).get("path", ""),
        "reused-paragraphs": len(refs),
    })
    body = header + "\n\n" + heading + "\n\n" + body_text.strip() + "\n"
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"
    paragraphs = [{"order": ref.get("order"), "key": ref.get("key"), "number": ref.get("number"),
                   "title": ref.get("title"), "chars": ref.get("chars"),
                   "score": ref.get("score"), "sha256": ref.get("sha256"),
                   "text": ref.get("text")} for ref in refs]
    keywords = spec_keywords(spec, extra=node.get("path_titles", []))
    fit = coverage(strip_comments(body), keywords, limit=40) if keywords else {"score": 0.0,
                                                                              "hit": [], "miss": []}
    sidecar = {
        "key": node["key"], "number": node["number"], "title": node["title"],
        "mode": decision["mode"],
        "source": {"key": refs[0].get("key"), "number": refs[0].get("number"),
                   "title": refs[0].get("title"), "chars": sum(ref.get("chars") or 0 for ref in refs),
                   "paragraphs": len(refs), "role": reuse.get("source")},
        "reuse": {"source": reuse.get("source"), "source_label": reuse.get("source_label"),
                  "top_score": reuse.get("top_score"), "hits": reuse.get("hits") or [],
                  "paragraphs": paragraphs},
        "diagnostics": decision.get("diagnostics", []),
        "spec": spec_payload(spec), "reasons": decision.get("reasons", []),
        "spec_coverage": fit,
        "chars": count_chars(body), "content_chars": content_chars(body),
        "integrity_sha256": _sha256(strip_comments(body).strip()),
        "llm_rewrite": False,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    drafts_dir = ensure(ws) / "drafts"
    md_path = drafts_dir / ("%s.md" % node["key"])
    md_path.write_text(body, encoding="utf-8")
    dump_json(drafts_dir / ("%s.sidecar.json" % node["key"]), sidecar)
    artifacts = [str(md_path), str(drafts_dir / ("%s.sidecar.json" % node["key"]))]
    report_path = drafts_dir / ("%s.复用对照.md" % node["key"])
    report_path.write_text(reuse_report(node, decision, sidecar, spec, body), encoding="utf-8")
    artifacts.append(str(report_path))
    return {"artifacts": artifacts, "sidecar": sidecar, "markdown": body}


def reuse_report(node, decision, sidecar, spec=None, body=""):
    """复用对照报告：命中段落清单 + 规范要素核对 + 排版纪律。"""
    spec = spec or decision.get("spec") or {}
    reuse = sidecar.get("reuse") or {}
    paragraphs = reuse.get("paragraphs") or []
    fit = sidecar.get("spec_coverage") or {}
    lines = ["# 正文复用对照报告 · %s %s" % (node["number"], node["title"]), ""]
    lines.append("复用来源：%s（命中 %d 段，合计 %d 字，最高相关度 %.2f）" % (
        reuse.get("source_label") or reuse.get("source") or "建设方案",
        len(paragraphs), (sidecar.get("source") or {}).get("chars", 0),
        reuse.get("top_score") or 0.0))
    lines.append("检索命中词：%s" % ("、".join(reuse.get("hits") or []) or "无"))
    lines.append("规范文件：%s" % (spec_payload(spec).get("path") or "未匹配"))
    lines.append("")
    lines.append("## 复用段落（原文，不得改写）")
    lines.append("")
    lines.append("| # | 来源小节 | 段落序号 | 字数 | 相关度 |")
    lines.append("|---|---|---|---|---|")
    for index, item in enumerate(paragraphs, start=1):
        lines.append("| %d | %s %s | %s | %s | %.2f |" % (
            index, item.get("number", ""), item.get("title", ""), item.get("order", ""),
            item.get("chars", 0), item.get("score") or 0.0))
    lines.append("")
    lines.append("段落顺序按来源原文顺序给出；与本节逻辑不符时可调整顺序、补过渡句，"
                 "但不得改写段落原文（check 会按 sha256 逐段复核）。")
    lines.append("")
    lines.append("## 规范要素命中（%d/%d）" % (
        len(fit.get("hit") or []), len(fit.get("hit") or []) + len(fit.get("miss") or [])))
    lines.append("")
    lines.append("- 已覆盖：" + ("、".join(fit.get("hit") or []) if fit.get("hit") else "无"))
    lines.append("- 待补足：" + ("、".join(fit.get("miss") or []) if fit.get("miss") else "无"))
    lines.append("")
    lines.extend(_requirements_block(node, spec, body))
    lines.append("## 纪律")
    lines.append("")
    lines.append("- 复用段落原文照搬：不得同义改写、不得润色、不得改数字与口径。")
    lines.append("- 允许的排版：调整段落顺序、合并同类表述、补过渡句与承接语。")
    lines.append("- 缺失要素按规范补写；无证据处标 GAP，技术推导标 〔推导：依据〕。")
    return "\n".join(lines) + "\n"


def skeleton_markdown(node, spec):
    requirements = node_requirements(node, spec)
    level = min(max(int(node.get("level", 1)) + 1, 2), 9)
    lines = ["#" * int(node.get("level", 1)) + " " + node["title"], ""]
    items = requirements.get("required_items") or []
    own = requirements.get("matched_item") or ""
    own_norm = normalize_title(own) if own else ""
    seen = set()
    for item in items:
        label = re.split(r"[（(，,：:、]", item["text"])[0].strip()[:20]
        if not label or label in seen:
            continue
        seen.add(label)
        if own_norm and normalize_title(label) == own_norm:
            continue
        lines.append("#" * level + " " + label)
        lines.append("")
        lines.append("<!-- 待写：依据 %s 撰写，达到规范篇幅下限 -->" % (item.get("section") or "规范要求"))
        lines.append("")
    for table in requirements.get("required_tables") or []:
        name = table["name"]
        if name in seen:
            continue
        seen.add(name)
        lines.append("#" * level + " " + name)
        lines.append("")
        lines.append("<!-- 待写：表格列 = %s -->" % "/".join(table["columns"]))
        lines.append("")
    if len(lines) <= 2:
        detail = (items[0].get("detail") if items else "") or ""
        floor = requirements.get("min_chars") or 0
        if own_norm:
            lines.append("<!-- 待写：本节点对应规范要素「%s」%s%s -->" % (
                own, ("，必写内容：" + detail) if detail else "",
                ("，篇幅下限 %d 字" % floor) if floor else ""))
        else:
            lines.append("<!-- 待写：规范未给出要素清单，按章节总纲与通用要求撰写 -->")
        lines.append("")
    return "\n".join(lines)


def task_pack(ws, node, decision, *, kb_result=None, spec=None, sources=None):
    spec = spec or decision.get("spec") or {}
    requirements = node_requirements(node, spec)
    lines = ["# 写作任务单 · %s %s" % (node["number"], node["title"]), ""]
    lines.append("## 路由结论")
    lines.append("")
    lines.append("- 模式：%s" % decision["mode"])
    for reason in decision.get("reasons", []):
        lines.append("- 依据：%s" % reason)
    lines.append("- 规范文件：%s" % (spec.get("path") or "未匹配到章节规范"))
    if spec.get("match_score") is not None:
        lines.append("- 规范匹配度：%.2f" % spec["match_score"])
    scope = decision.get("evidence_scope") or decision.get("scope")
    if scope:
        lines.append("- 素材范围：%s %s（子树 %d 字%s）" % (
            scope.get("number", ""), scope.get("title", ""), scope.get("subtree_chars", 0),
            ("，含：" + "、".join(scope.get("children") or [])) if scope.get("children") else ""))
    lines.append("")
    lines.append("## 规范要求")
    lines.append("")
    if requirements.get("min_chars"):
        lines.append("- 篇幅下限参考：≥%d 字（规范内出现的最大字数提示）" % requirements["min_chars"])
    if requirements.get("char_hints"):
        lines.append("- 逐项字数提示：" + "、".join("%d字" % value for value in requirements["char_hints"][:8]))
    items = requirements.get("required_items") or []
    if items:
        lines.append("- 必写要素：")
        for item in items:
            lines.append("  - %s" % item["text"])
    tables = requirements.get("required_tables") or []
    if tables:
        lines.append("- 必需表格：")
        for table in tables:
            lines.append("  - %s（列：%s）" % (table["name"], "/".join(table["columns"])))
    checklist = requirements.get("checklist") or []
    if checklist:
        lines.append("- 完成标准：")
        for item in checklist:
            lines.append("  - [ ] %s" % item)
    lines.append("")
    candidates = decision.get("candidates") or []
    if candidates:
        lines.append("## 建设方案候选（未达迁移阈值，供参考）")
        lines.append("")
        for candidate in candidates[:5]:
            lines.append("- %s %s（综合 %.2f｜标题 %.2f｜规范 %.2f）" % (
                candidate.get("number", ""), candidate.get("title", ""),
                candidate.get("combined", candidate.get("score", 0.0)),
                candidate.get("title_score", 0.0), candidate.get("spec_score", 0.0)))
        lines.append("")
    if scope and scope.get("excerpt"):
        lines.append("## 素材范围摘录（%s %s）" % (scope.get("number", ""), scope.get("title", "")))
        lines.append("")
        lines.append("> " + scope["excerpt"])
        lines.append("")
        lines.append("（完整素材见建设方案对应节点；本节目的是按规范归纳/撰写，不是整段迁移。）")
        lines.append("")
    if sources:
        lines.append("## 本地原文检索")
        lines.append("")
        for hit in sources:
            lines.append("- %s#%s：%s" % (hit.get("file", ""), hit.get("line", ""), (hit.get("text") or "")[:160]))
        lines.append("")
    hits = (kb_result or {}).get("hits") or decision.get("kb_hits") or []
    lines.append("## 知识库命中（%d 条）" % len(hits))
    lines.append("")
    if hits:
        for hit in hits[:6]:
            lines.append("- %s%s：%s" % (hit.get("source", ""),
                                         (" p%s" % hit["page"]) if hit.get("page") else "",
                                         (hit.get("content") or "")[:200]))
    else:
        lines.append("- 无命中；政策文号、标准版本、法规施行日期必须查知识库后落盘 KB 卡。")
    lines.append("")
    lines.append("## 检索与撰写纪律")
    lines.append("")
    lines.append("1. 先本地原文（已转换 Markdown）→ 知识库（政策/标准必查）→ 网络（%s）→ 技术推导。"
                 % ("已授权" if decision.get("allow_web") else "默认关闭，需 --allow-web 或用户明示"))
    lines.append("2. 不照抄（连续重合 ≥40 字即违规）、不编造（事实句须有锚点）、不填空（无证据写 GAP）。")
    lines.append("3. 设计推导标 〔推导：依据〕；政策/标准引用须为落盘的 KB 卡内容。")
    lines.append("4. 来源记 sidecar，正文不写引用标记；不写手工章节编号。")
    lines.append("")
    lines.append("## 骨架（可覆盖，仅作提示）")
    lines.append("")
    lines.append("```markdown")
    lines.append(skeleton_markdown(node, spec).strip())
    lines.append("```")
    return "\n".join(lines) + "\n"


def write_task_pack(ws, node, decision, *, kb_result=None, spec=None, sources=None):
    ws = ensure(ws)
    pack = task_pack(ws, node, decision, kb_result=kb_result, spec=spec, sources=sources)
    plan_dir = ws / "plan"
    md_path = plan_dir / ("%s.任务单.md" % node["key"])
    md_path.write_text(pack, encoding="utf-8")
    json_path = plan_dir / ("%s.任务单.json" % node["key"])
    skeleton = skeleton_markdown(node, spec or decision.get("spec") or {})
    dump_json(json_path, {"node": {"key": node["key"], "number": node["number"], "title": node["title"]},
                          "decision": decision, "spec": spec_payload(spec or decision.get("spec")),
                          "kb": kb_result, "skeleton": skeleton})
    draft_path = ws / "plan" / ("%s.骨架.md" % node["key"])
    draft_path.write_text(skeleton, encoding="utf-8")
    return {"artifacts": [str(md_path), str(json_path), str(draft_path)], "skeleton": skeleton}


def node_heading(node):
    return "#" * max(1, min(int(node.get("level", 1)), 9)) + " " + node["title"]


def render_scope_markdown(ws, tree, keys, *, include_todo=True):
    """按模板树顺序装配指定 scope：有草稿用草稿，缺草稿留 TODO 占位。"""
    ws = ensure(ws)
    drafts = ws / "drafts"
    wanted = set(keys)
    used = []
    parts = []
    project_meta = load_json(ws / "template" / "项目目录元数据.json", default={}) or {}
    project_anchors = project_meta.get("anchors") or {}
    source_hash = project_meta.get("source_sha256")

    def render(node, inside=False):
        if not (inside or node["key"] in wanted):
            return
        heading = node_heading(node)
        draft_path = drafts / ("%s.md" % node["key"])
        if draft_path.exists():
            if node["key"] in project_anchors:
                sidecar = load_json(drafts / ("%s.sidecar.json" % node["key"]), default={}) or {}
                if (sidecar.get("source_sha256") != source_hash or
                        (sidecar.get("source") or {}).get("key") !=
                        project_anchors[node["key"]]["source"]):
                    raise AppError("草稿与本项目目录来源不一致：请重新 author --scope %s --force" %
                                   node["number"], status="conflict")
            text = draft_path.read_text(encoding="utf-8")
            body = strip_comments(text).lstrip("\n")
            lines = body.splitlines()
            if lines and lines[0].startswith("#"):
                lines = lines[1:]
            body = "\n".join(lines).strip()
            parts.append(heading)
            parts.append("")
            parts.append(body)
            parts.append("")
            used.append(node["key"])
            return
        parts.append(heading)
        parts.append("")
        if node["children"]:
            for child in node["children"]:
                render(child, True)
            return
        if include_todo:
            parts.append("<!-- keyan-todo: 本节尚无草稿，运行 author --scope %s 生成 -->" % node["key"])
            parts.append("")
        else:
            parts.append("")

    for key in keys:
        node = node_by_key(tree, key)
        if node is not None:
            render(node)
    markdown = "\n".join(parts)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
    return markdown, used
