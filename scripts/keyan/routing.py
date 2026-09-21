"""来源路由：同名直复 > 语义迁移 > 标题相关迁移 > 正文段落复用 > 材料复用 > 撰写 > 缺口。

映射不出来的标题不再只给"推荐小标题"骨架，而是沿阶梯继续找料：
标题相关（词面明显相关、正文贴合规范）→ 整段迁移；正文相关（建设方案里的相关段落）
→ 原文复用，多段由 agent 排版补过渡；用户另传材料 → 材料里检索标题/正文；
都没有 → 查知识库 / 联网后按规范撰写，最后才是显式缺口。

同名直复不是"标题相同就复制"：归属仲裁（arbitration）会先判断该同名候选是否属于
本节的素材范围（scope，由兄弟节点共同命中的来源父节点推断）。范围外的同名候选降级，
转语义候选迁移或按范围素材撰写——避免把"建设目标与建设内容 > 建设目标"复制到
"运行维护系统设计方案 > 建设目标"。
"""
import re

from .headings import (bigrams, candidate_accepted, candidate_similarity, normalize_title,
                       similarity, synonym_related)
from .matching import in_scope
from .reuse import REUSE_MIN_TOTAL_CHARS, REUSE_TOP_K, build_reuse, subtree_keys
from .specs import coverage, node_requirements, outline_keywords, spec_keywords, spec_payload
from .tree import node_by_key

MODE_PRIORITY = ["exact_direct_copy", "semantic_migrate", "title_migrate", "paragraph_reuse",
                 "material_reuse", "grounded_write", "gap"]

MODE_LABELS = {
    "exact_direct_copy": "同名直复（与建设方案同名，原文整棵子树复制，不改写）",
    "semantic_migrate": "语义候选迁移（无同名，取语义+规范最贴合的候选整段迁移后按规范补足）",
    "title_migrate": "标题相关迁移（词面明显相关的候选，整棵子树迁入后按规范补足）",
    "paragraph_reuse": "正文段落复用（建设方案正文里的相关段落原文搬运，agent 排版补过渡）",
    "material_reuse": "材料复用（用户另传材料里的相关标题/正文迁移复用）",
    "grounded_write": "证据撰写（建设方案无可用候选，查知识库/网络后按规范撰写）",
    "gap": "缺口（素材不足，输出缺口清单）",
}

SCOPE_BONUS = 0.15          # 候选落在本节素材范围内时的加分
THIN_SCOPE_OWN_CHARS = 400  # 素材范围节点自身正文少于该值时只作写作素材，不整段迁移
SEMANTIC_MIN_CANDIDATE_CHARS = 120  # 语义候选正文下限（index 与 plan 必须用同一口径）


def _edit_distance(left, right):
    """计算短标题的编辑距离，用于召回仅有少量字面差异的标题。"""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + (left_char != right_char),
            ))
        previous = current
    return previous[-1]


def _near_title_score(target, candidate):
    """识别标题仅有少量增删改字的情况，不依赖具体业务词。"""
    target_norm = normalize_title(target)
    candidate_norm = normalize_title(candidate)
    if not target_norm or not candidate_norm or target_norm == candidate_norm:
        return 0.0
    shorter, longer = sorted((target_norm, candidate_norm), key=len)
    distance = _edit_distance(shorter, longer)
    common_prefix = 0
    for left, right in zip(shorter, longer):
        if left != right:
            break
        common_prefix += 1
    prefix_floor = max(3, int(len(shorter) * 0.5))
    if distance > 1 or common_prefix < prefix_floor:
        return 0.0
    return round(0.86 + 0.08 * (common_prefix / max(1, len(shorter))), 4)


def _semantic_title_compatible(target, candidate):
    """过滤只共享前缀、末尾语义相反的标题候选。

    “项目建设单位”与“项目建设依据”都包含“项目建设”，但不是同一写作对象；
    这种候选应让正文检索继续寻找“项目建设单位：……”等原文，而不是整段迁移依据章节。
    """
    target = (target or "").strip()
    candidate = (candidate or "").strip()
    if not target or not candidate or target in candidate or candidate in target:
        return True
    common = 0
    for left, right in zip(target, candidate):
        if left != right:
            break
        common += 1
    return common < max(2, min(len(target), len(candidate)) // 2)


def _title_variant_score(target, candidate):
    """召回主体相同、目标标题增加限定词的标题变体。

    不绑定具体业务词：例如“建设内容和规模”→“建设内容”、
    “项目建设单位概况”→“项目建设单位”都可进入候选；仅共享短前缀的
    “项目建设单位”→“项目建设依据”不会命中。
    """
    target = normalize_title(target)
    candidate = normalize_title(candidate)
    if not target or not candidate:
        return 0.0
    if len(candidate) < 3 or candidate == target or candidate not in target:
        return 0.0
    ratio = len(candidate) / len(target)
    if ratio < 0.5:
        return 0.0
    extra = target.replace(candidate, "", 1)
    if len(extra) > max(6, len(candidate) // 2):
        return 0.0
    return round(0.65 + 0.35 * ratio, 4)


_GENERIC_TITLE_GRAMS = {"项目", "建设", "系统", "方案", "情况", "管理", "平台", "设计"}
_TABLE_TITLE_WORDS = ("附表", "表格", "预算", "清单", "估算", "测算")


def _table_title_score(target, candidate):
    """表格标题的通用匹配：项目主题优先，弱化附表编号和表格类别后缀。"""
    target_norm = normalize_title(target)
    candidate_norm = normalize_title(candidate)
    if not target_norm or not candidate_norm:
        return 0.0
    candidate_norm = re.sub(r"^附表\d*", "", candidate_norm)
    target_core = re.sub(r"(?:建设)?(?:估算|预算)?表$", "", target_norm)
    candidate_core = re.sub(r"(?:软件开发)?(?:预算)?清单$", "", candidate_norm)
    target_core = re.sub(r"(?:建设)?(?:估算|预算)$", "", target_core)
    candidate_core = re.sub(r"(?:软件开发)?(?:预算)$", "", candidate_core)
    if len(target_core) < 2 or len(candidate_core) < 2:
        return 0.0
    shared = {gram for gram in bigrams(target_core) & bigrams(candidate_core)
              if gram not in _GENERIC_TITLE_GRAMS}
    common_prefix = 0
    for left, right in zip(target_core, candidate_core):
        if left != right:
            break
        common_prefix += 1
    if len(shared) < 2 and common_prefix < 2:
        return 0.0
    overlap = len(shared) / max(1, min(len(bigrams(target_core)), len(bigrams(candidate_core))))
    prefix_ratio = common_prefix / max(1, min(len(target_core), len(candidate_core)))
    return round(min(0.92, 0.52 + 0.25 * overlap + 0.20 * prefix_ratio), 4)


def _cross_title_score(target, candidate):
    """召回跨章节的共同主题标题，再交给正文规范贴合度筛选。"""
    target_norm = normalize_title(target)
    candidate_norm = normalize_title(candidate)
    if not target_norm or not candidate_norm or target_norm == candidate_norm:
        return 0.0
    shared = {gram for gram in bigrams(target_norm) & bigrams(candidate_norm)
              if gram not in _GENERIC_TITLE_GRAMS}
    if len(shared) < 2:
        return 0.0
    denominator = max(1, min(len(bigrams(target_norm)), len(bigrams(candidate_norm))))
    overlap = len(shared) / denominator
    if overlap < 0.25:
        return 0.0
    return round(min(0.78, 0.48 + 0.55 * overlap), 4)


def _title_suffix_bonus(target, candidate):
    """目标标题末尾的区分性词组在候选中出现时提高排序。"""
    target_norm = normalize_title(target)
    candidate_norm = normalize_title(candidate)
    suffix = target_norm[-2:] if len(target_norm) >= 2 else ""
    if not suffix or suffix in _GENERIC_TITLE_GRAMS or suffix not in candidate_norm:
        return 0.0
    return 0.18


def route_node(index, specs, node, *, allow_web=False, kb_hits=None, top_k=8,
               migrate_threshold=0.45, min_candidate_chars=SEMANTIC_MIN_CANDIDATE_CHARS,
               arbitration=None, override=None, paragraphs=None, materials=None,
               exclude_orders=()):
    spec = specs.spec_for_node(node) if specs else None
    keywords = spec_keywords(spec, extra=node.get("path_titles", [])) if spec else []
    requirements = node_requirements(node, spec)
    if requirements.get("matched_item"):
        details = " ".join("%s %s" % (item.get("text", ""), item.get("detail", ""))
                           for item in requirements.get("required_items", []))
        keywords = outline_keywords(details) + [node["title"]]
    paragraph_keywords = keywords if requirements.get("matched_item") else [node["title"]]
    diagnostics = []
    decision = {
        "key": node["key"], "number": node["number"], "title": node["title"],
        "level": node["level"], "spec": spec_payload(spec),
        "candidates": [], "matched_source": None,
        "reasons": [], "next_actions": [], "allow_web": bool(allow_web),
    }
    if spec is None:
        diagnostics.append("spec_missing: 未找到对应章节规范，按通用要求撰写")

    scope_key = (arbitration or {}).get("scope", {}).get(node["key"]) if arbitration else None
    scope_node = node_by_key(index.tree, scope_key) if scope_key else None
    if scope_node:
        decision["scope"] = {"key": scope_node["key"], "number": scope_node["number"],
                             "title": scope_node["title"], "subtree_chars": scope_node["subtree_chars"]}
        decision["evidence_scope"] = _scope_ref(index, scope_node)

    # 0) 手工锚点（用户显式指定，最高优先级）
    if override:
        entry = index.by_key.get(override.get("source"))
        if entry is None:
            diagnostics.append("override_missing: 手工锚点 %s 指向的来源节点 %s 不存在"
                               % (node["key"], override.get("source")))
        else:
            _apply_override(decision, node, entry, override, spec, keywords, index)
            if decision["mode"] == "grounded_write":
                pinned = node_by_key(index.tree, entry["key"])
                if pinned:
                    _reuse_decision(decision, node, paragraph_keywords, paragraphs, [],
                                    exclude_orders=exclude_orders, top_k=top_k,
                                    scope_keys=subtree_keys(pinned))
            decision["diagnostics"] = diagnostics
            return decision

    # 1) 同名直复（受归属仲裁约束）
    exact = _exact_decision(index, node, decision, spec, keywords, diagnostics,
                            arbitration=arbitration)
    if exact is not None:
        return exact

    # 2) 语义候选迁移（含同名候选与素材范围节点）
    scored = _semantic_candidates(index, node, keywords, top_k=top_k,
                                 min_candidate_chars=min_candidate_chars,
                                 arbitration=arbitration, scope_key=scope_key)
    decision["candidates"] = [_candidate_ref(item) for item in scored]
    if scored:
        best = scored[0]
        accept = _accept_migration(best, migrate_threshold)
        if accept and best.get("scope_material"):
            decision["reasons"].append(
                "素材范围节点《%s》自身正文仅 %d 字，作为写作素材而非整段迁移"
                % (best["entry"]["title"], best["entry"]["own_chars"]))
            accept = False
        decision["reasons"].append(
            "语义候选最优：%s（标题相似 %.2f，规范贴合 %.2f，综合 %.2f，同义族 %s%s）"
            % (best["entry"]["title"], best["title_score"], best["spec_score"], best["combined"],
               "是" if best["synonym"] else "否",
               "，命中素材范围" if best.get("scope_match") else ""))
        if accept:
            entry = best["entry"]
            decision.update({
                "mode": "semantic_migrate",
                "matched_source": _entry_ref(entry),
                "migrate_from": {
                    "title": entry["title"], "number": entry["number"], "key": entry["key"],
                    "title_score": best["title_score"], "spec_score": best["spec_score"],
                    "synonym": best["synonym"], "miss": best["miss"],
                },
                "reasons": decision["reasons"] + [
                    "依据章节规范比对正文后选用（规范要素命中 %d 项，缺 %d 项）"
                    % (len(best["hit"]), len(best["miss"])),
                ],
                "next_actions": [
                    "author：整段迁移候选子树并按目标层级重挂标题（不做同义改写）",
                    "对照规范补齐缺失要素：" + ("、".join(best["miss"][:6]) if best["miss"] else "无"),
                ],
            })
            if best["spec_score"] < 0.2:
                diagnostics.append("migrate_weak_spec_fit: 迁移候选对规范要素覆盖 %.2f，迁移后需按规范补写"
                                   % best["spec_score"])
            decision["diagnostics"] = diagnostics
            return decision
        if best.get("scope_material"):
            diagnostics.append("scope_material_only: 素材范围节点《%s》自身正文偏薄（%d 字），"
                               "作为写作素材而非整段迁移" % (best["entry"]["title"],
                                                          best["entry"]["own_chars"]))
            decision["reasons"].append("转按素材范围撰写本节，而不是迁移该节点正文")
        else:
            decision["reasons"].append("候选综合分低于阈值 %.2f，且标题相似度不足，转证据撰写"
                                       % migrate_threshold)
            diagnostics.append("candidate_below_threshold: 语义候选接近但不达标，需撰写")

    # 3) 标题相关：词面明显相关、正文贴合本节规范 → 整棵子树迁过来
    title_decision = _title_migrate_decision(decision, node, scored)
    if title_decision is not None:
        return title_decision

    # 4) 正文相关：建设方案 / 用户材料里的相关段落原文复用
    # 正文证据可以来自已被其他节点认领的来源章节；真正重复的段落由
    # exclude_orders 按段落序号控制。整棵节点排除会漏掉“相关法律法规”
    # 这类标题不一致、但正文确实存在的证据。
    eligible = list(paragraphs or [])
    decision["diagnostics"] = diagnostics
    reuse_decision = _reuse_decision(decision, node, paragraph_keywords, eligible, materials,
                                    exclude_orders=exclude_orders, top_k=top_k,
                                    scope_keys=subtree_keys(scope_node) if scope_node else None)
    if reuse_decision is not None:
        return reuse_decision

    # 5) 证据撰写
    hits = kb_hits or []
    reasons = list(decision["reasons"])
    reasons.append("建设方案无同名/可迁移候选，正文与用户材料里也无相关段落")
    if scope_node:
        reasons.append("素材范围：%s %s（子树 %d 字）" % (scope_node["number"], scope_node["title"],
                                                        scope_node["subtree_chars"]))
    reasons.append("知识库命中 %d 条（政策文号/标准版本/法规日期必查知识库）" % len(hits))
    reasons.append("网络检索：%s" % ("已授权" if allow_web else "默认关闭，需 --allow-web 或用户明示"))
    actions = []
    if scope_node:
        actions.append("以《%s %s》子树（%d 字）为素材范围撰写本节：%s"
                       % (scope_node["number"], scope_node["title"], scope_node["subtree_chars"],
                          " ".join(child["title"] for child in (scope_node.get("children") or [])[:6]) or "无子节点"))
    actions.extend([
        "查知识库：政策文号、标准版本、法规施行日期（KB 卡须落盘）",
        "必要时（--allow-web）检索最新政策/标准/公开技术资料并落盘 WEB 卡",
        "按规范必写要素撰写；缺证据处标 GAP，技术推导标 〔推导：依据〕",
    ])
    decision.update({
        "mode": "grounded_write",
        "reasons": reasons,
        "kb_hits": hits,
        "gaps": ["本地素材与知识库均无证据的要素需标 GAP 或作标记推导"],
        "next_actions": actions,
    })
    if scope_node:
        decision["evidence_scope"] = _scope_ref(index, scope_node)
    if keywords:
        decision["spec_coverage"] = coverage("", keywords)
    decision["diagnostics"] = diagnostics
    return decision


# ------------------------------------------------------------------ 标题相关 / 正文相关
TITLE_MIGRATE_SPEC_FLOOR = 0.12   # 候选正文至少与本节规范有这点贴合
TITLE_MIGRATE_STRONG = 0.50       # 或者综合分已很高（只是没到迁移阈值）


def _related_candidates(index, node, keywords, *, top_k):
    """任一来源文件里的标题候选（与语义候选同口径，不含素材范围节点）。"""
    pool = []
    candidates = index.similar_entries(node["title"], k=top_k,
                                       min_chars=SEMANTIC_MIN_CANDIDATE_CHARS, min_score=0.34)
    _best, exact = index.resolve_exact(node)
    candidates = [(1.0, item["entry"]) for item in exact if item["copyable"]] + [
        (min(1.0, score + _title_suffix_bonus(node["title"], entry["title"])), entry)
        for score, entry in candidates]
    seen_keys = {entry["key"] for _, entry in candidates}
    for entry in index.entries:
        near_score = _near_title_score(node["title"], entry["title"])
        if (near_score and entry["key"] not in seen_keys
                and entry["subtree_chars"] >= REUSE_MIN_TOTAL_CHARS):
            candidates.append((near_score, entry))
            seen_keys.add(entry["key"])
    for entry in index.entries:
        cross_score = _cross_title_score(node["title"], entry["title"])
        if (cross_score and entry["key"] not in seen_keys
                and (entry["subtree_chars"] >= SEMANTIC_MIN_CANDIDATE_CHARS
                     or entry["children_count"])):
            candidates.append((min(1.0, cross_score +
                                  _title_suffix_bonus(node["title"], entry["title"])), entry))
            seen_keys.add(entry["key"])
    for title_score, entry in candidates:
        fit = index.spec_fit(entry, keywords) if keywords else {"score": 0.0, "hit": [], "miss": []}
        pool.append({
            "entry": entry, "title_score": round(title_score, 4), "spec_score": fit["score"],
            "combined": min(round(0.55 * title_score + 0.45 * fit["score"], 4), 1.0),
            "hit": fit["hit"], "miss": fit["miss"][:12],
            "synonym": synonym_related(node["title"], entry["title"]),
            "scope_match": False, "scope_candidate": False, "scope_material": False,
        })
    pool.sort(key=lambda item: (-item["combined"], -item["title_score"], item["entry"]["doc_order"]))
    return pool[:max(top_k, 6)]


def _accept_title_candidate(scored, node):
    """标题相关候选是否可用：词面明显相关 且 正文贴合本节规范。

    只用标题像不算（"项目建设单位" ↔ "项目建设内容"这种同前缀误配），
    必须再有规范贴合做守门员；或者综合分本身已经很高（例如只剩归属范围问题）。
    """
    for item in scored or ():
        entry = item["entry"]
        effective, head_ok, synonym = candidate_similarity(node["title"], entry["title"])
        if not candidate_accepted(effective, head_ok, synonym):
            continue
        if item.get("scope_material"):
            continue
        if item["spec_score"] < TITLE_MIGRATE_SPEC_FLOOR and item["combined"] < TITLE_MIGRATE_STRONG:
            continue
        return item, effective, head_ok, synonym
    return None


def _title_migrate_decision(decision, node, scored):
    """标题相关：词面明显相关、正文贴合本节规范 → 整棵子树迁过来。"""
    accepted = _accept_title_candidate(scored, node)
    if accepted is None:
        return None
    item, effective, head_ok, synonym = accepted
    entry = item["entry"]
    decision.update({
        "mode": "title_migrate",
        "reuse_role": "source",
        "matched_source": _entry_ref(entry),
        "migrate_from": {"title": entry["title"], "number": entry["number"], "key": entry["key"],
                         "title_score": round(effective, 4), "spec_score": item["spec_score"],
                         "synonym": bool(synonym), "miss": item["miss"]},
        "reasons": decision["reasons"] + [
            "标题相关候选《%s》：词面相似 %.2f（%s），规范贴合 %.2f，综合 %.2f"
            % (entry["title"], effective, "词头可辨" if head_ok else "仅类别词相同",
               item["spec_score"], item["combined"]),
            "语义迁移阈值未达标但正文贴合本节规范，整棵子树迁入后按规范补足",
        ],
        "next_actions": [
            "author：整段迁移该候选子树并按目标层级重挂标题（不做同义改写）",
            "对照规范补齐缺失要素：" + ("、".join(item["miss"][:6]) if item["miss"] else "无"),
        ],
    })
    return decision


def _try_reuse(node, keywords, records, *, source, top_k, exclude_orders, scope_keys):
    """先查素材范围，再查全文正文；全文回退排除范围外同名标题。"""
    exclude_orders = [order for role, order in exclude_orders if role == source]
    if scope_keys:
        inner = [record for record in records if record["key"] in scope_keys]
        scoped_built = build_reuse(node, keywords, inner, source=source, top_k=top_k,
                                   exclude_orders=exclude_orders, scoped=True)
        legal_target = "法律法规" in (node.get("title") or "")
        named_law = legal_target and any(
            "中华人民共和国" in ref.get("text", "")
            for ref in (scoped_built or {}).get("refs", []))
        target_norm = normalize_title(node.get("title", ""))
        global_records = [record for record in records
                          if target_norm not in [normalize_title(title)
                                                 for title in record.get("path_titles") or []]]
        if legal_target and not named_law:
            global_records = [record for record in global_records
                              if "中华人民共和国" in record.get("text", "")
                              or "GB/T" in record.get("text", "")]
        global_built = build_reuse(node, keywords, global_records, source=source, top_k=top_k,
                                   exclude_orders=exclude_orders, scoped=False)
        if legal_target:
            return global_built if global_built is not None else scoped_built
        if scoped_built is None:
            return global_built
        if global_built is None:
            return scoped_built
        scoped_score = scoped_built.get("top_score", 0.0)
        global_score = global_built.get("top_score", 0.0)
        global_near_title = global_built.get("basis") == "正文命中近似标题核心词"
        scoped_exact_title = scoped_built.get("basis") == "小节同名"
        if ((global_near_title and not scoped_exact_title)
                or global_score >= scoped_score + 0.08):
            global_built["selection_basis"] = "全文候选相关度高于素材范围内弱命中"
            return global_built
        return scoped_built
    return build_reuse(node, keywords, records, source=source, top_k=top_k,
                       exclude_orders=exclude_orders)


def _reuse_decision(decision, node, keywords, paragraphs, materials, *, exclude_orders=(),
                    top_k=REUSE_TOP_K, scope_keys=None):
    """正文相关：先建设方案正文，再用户另传材料（先标题后正文）；命中即复用。"""
    ladder = [("source", "建设方案", paragraphs, "paragraph_reuse")]
    for material in materials or ():
        role = material.get("role") or "material"
        ladder.append((role, material.get("title") or role, material.get("paragraphs"),
                       "material_reuse"))
    for role, label, records, mode in ladder:
        material_meta = next((item for item in (materials or ()) if item.get("role") == role), None)
        if material_meta is not None and material_meta.get("index") is not None:
            accepted = _accept_title_candidate(
                _related_candidates(material_meta["index"], node, keywords, top_k=top_k), node)
            if accepted is not None:
                item, effective, head_ok, synonym = accepted
                entry = item["entry"]
                decision.update({
                    "mode": mode,
                    "reuse_role": role,
                    "reuse_kind": "migrate",
                    "matched_source": _entry_ref(entry),
                    "migrate_from": {"title": entry["title"], "number": entry["number"],
                                     "key": entry["key"], "title_score": round(effective, 4),
                                     "spec_score": item["spec_score"], "synonym": bool(synonym),
                                     "miss": item["miss"]},
                    "reasons": decision["reasons"] + [
                        "建设方案里没有可用标题/段落，在用户材料《%s》里命中标题《%s》"
                        "（词面相似 %.2f，规范贴合 %.2f）" % (label, entry["title"], effective,
                                                              item["spec_score"]),
                        "整段迁移该候选并按目标层级重挂标题，再按规范补足",
                    ],
                    "next_actions": [
                        "author：从用户材料迁移该候选子树，标题重挂后按规范补足",
                    ],
                })
                return decision
        built = _try_reuse(node, keywords, records or [], source=role, top_k=top_k,
                           exclude_orders=exclude_orders,
                           scope_keys=scope_keys if role == "source" else None)
        if built is None:
            continue
        fit = coverage(built["body"], keywords) if keywords else {"score": 0.0, "hit": [], "miss": []}
        first = built["refs"][0]
        decision.update({
            "mode": mode,
            "reuse_role": role,
            "reuse_kind": "paragraphs",
            "matched_source": {"key": first["key"], "number": first["number"],
                               "title": first["title"]},
            "reuse": {"source": role, "source_label": label, "chars": built["chars"],
                      "top_score": built["top_score"], "hits": built["hits"][:10],
                      "refs": built["refs"], "body": built["body"],
                      "scoped": bool(built.get("scoped")), "basis": built.get("basis")},
            "reasons": decision["reasons"] + [
                "标题相关候选不成立，转正文检索：在%s%s里命中 %d 段相关原文"
                "（合计 %d 字，最高相关度 %.2f，依据：%s）"
                % (label, "本节素材范围内" if built.get("scoped") else "全篇",
                   len(built["refs"]), built["chars"], built["top_score"],
                   built.get("basis") or "小节标题相关"),
                "复用段落保留原文（不润色、不同义改写），由 agent 组织顺序与过渡后按规范补足",
            ],
            "spec_coverage": fit,
            "next_actions": [
                "author：搬运命中段落原文，按本节逻辑排序并补过渡句（不改事实、数字、口径）",
                "对照规范补齐缺失要素：" + ("、".join(fit["miss"][:6]) if fit["miss"] else "无"),
            ],
        })
        return decision
    return None


# ------------------------------------------------------------------ 同名直复
def _exact_decision(index, node, decision, spec, keywords, diagnostics, *, arbitration):
    """按归属仲裁决定是否同名直复；返回 decision 或 None（表示不作直复）。"""
    claim = (arbitration or {}).get("claims", {}).get(node["key"]) if arbitration else None
    dropped = (arbitration or {}).get("demoted", {}).get(node["key"]) if arbitration else None
    context = None
    basis = []
    entry = None
    if claim:
        entry = index.by_key.get(claim["source"])
        context = claim.get("context")
        basis = claim.get("basis") or []
    elif dropped:
        decision["claim_dropped"] = dropped
        decision["reasons"].append("同名候选《%s》(%s) %s，不作直复"
                                   % (dropped.get("source_title", ""),
                                      dropped.get("source_number", ""), dropped.get("label", "")))
        diagnostics.append("%s: 同名候选《%s》(%s) %s"
                           % (dropped["reason"], dropped.get("source_title", ""),
                              dropped.get("source_number", ""), dropped.get("label", "")))
        if dropped.get("scope_title"):
            diagnostics.append("scope_hint: 本节素材范围应为 %s" % dropped["scope_title"])
        return None
    elif arbitration is None:
        best, exact_scored = index.resolve_exact(node)
        if len(exact_scored) > 1:
            diagnostics.append("ambiguous_exact: 同名候选 %d 个，按上下文/章节归属择优" % len(exact_scored))
        if best is not None:
            entry = best["entry"]
            context = best["context_score"]
    if entry is None:
        return None
    decision.update({
        "mode": "exact_direct_copy",
        "matched_source": _entry_ref(entry),
        "reasons": [
            "标题归一化后同名：%s" % entry["title"],
            "上下文兼容度 %s，同章 %s" % ("%.2f" % context if context is not None else "-",
                                          entry["number"].split(".")[0] == node["number"].split(".")[0]),
            "可复制子树：%d 字 / %d 表 / %d 图" % (entry["subtree_chars"], entry["tables"], entry["images"]),
        ] + (["归属依据：" + "；".join(basis)] if basis else []),
        "next_actions": ["author：整棵子树直接复制，不润色、不总结、不同义改写（LLM_REWRITE_COUNT=0）"],
    })
    if entry["subtree_chars"] < 400 and entry["children_count"] == 0:
        diagnostics.append("thin_match: 同名子树偏薄（%d 字），复制后需按规范补足" % entry["subtree_chars"])
    if spec:
        fit = index.spec_fit(entry, keywords)
        decision["spec_coverage"] = fit
        if fit["score"] < 0.35:
            diagnostics.append("spec_gap_after_copy: 同名直复内容对规范要素覆盖 %.2f，需按规范补足"
                               % fit["score"])
    decision["diagnostics"] = diagnostics
    return decision


# ------------------------------------------------------------------ 语义候选
def _excluded_source_keys(index, node, arbitration):
    reserved = {record["source"] for key, record in (arbitration or {}).get("claims", {}).items()
                if key != node["key"] and not node["key"].startswith(key + "_")}
    dropped = (arbitration or {}).get("demoted", {}).get(node["key"], {})
    if dropped.get("source"):
        reserved.add(dropped["source"])
    excluded = set()
    for key in reserved:
        source_node = node_by_key(index.tree, key)
        if source_node:
            excluded.update(subtree_keys(source_node))
    return excluded


def _semantic_candidates(index, node, keywords, *, top_k, min_candidate_chars,
                         arbitration=None, scope_key=None):
    """候选池 = 近义标题 + 同名候选（含被降级时自己的同名）+ 素材范围节点。"""
    reserved = _excluded_source_keys(index, node, arbitration)
    parent_title = (node.get("path_titles") or [""])[-2] if len(node.get("path_titles") or []) > 1 else ""
    pool = []

    def add(entry, title_score, *, synonym=False, scope_candidate=False, table_match=False,
            miss=None, hit=None):
        fit = index.spec_fit(entry, keywords) if keywords else {"score": 0.0, "hit": [], "miss": []}
        match = in_scope(entry, scope_key)
        combined = round(0.55 * title_score + 0.45 * fit["score"]
                         + (SCOPE_BONUS if match else 0.0), 4)
        pool.append({"entry": entry, "title_score": round(title_score, 4), "spec_score": fit["score"],
                     "combined": min(combined, 1.0), "hit": fit["hit"], "miss": fit["miss"][:12],
                     "synonym": synonym, "scope_match": match, "scope_candidate": scope_candidate,
                     "scope_material": bool(scope_candidate and entry["own_chars"] < THIN_SCOPE_OWN_CHARS),
                     "table_match": bool(table_match and entry.get("tables", 0))})

    seen_keys = set()
    target_has_table_intent = any(word in normalize_title(node["title"])
                                  for word in _TABLE_TITLE_WORDS)
    if target_has_table_intent:
        for entry in index.entries:
            if entry.get("tables", 0) <= 0 or entry["key"] in reserved:
                continue
            table_score = _table_title_score(node["title"], entry["title"])
            if not table_score:
                continue
            add(entry, min(1.0, table_score + 0.15), synonym=True, table_match=True)
            seen_keys.add(entry["key"])
    for title_score, entry in index.similar_entries(node["title"], k=top_k,
                                                   min_chars=min_candidate_chars, min_score=0.34):
        if not _semantic_title_compatible(node["title"], entry["title"]):
            continue
        if (entry["key"] in reserved or entry["key"] in seen_keys
                or (scope_key and not in_scope(entry, scope_key))):
            continue
        add(entry, min(1.0, title_score +
                       _title_suffix_bonus(node["title"], entry["title"])),
            synonym=synonym_related(node["title"], entry["title"]))

    seen_keys.update(item["entry"]["key"] for item in pool)
    for entry in index.entries:
        cross_score = _cross_title_score(node["title"], entry["title"])
        if (not cross_score or entry["key"] in seen_keys or entry["key"] in reserved
                or (entry["subtree_chars"] < min_candidate_chars and not entry["children_count"])):
            continue
        add(entry, min(1.0, cross_score +
                       _title_suffix_bonus(node["title"], entry["title"])))
        seen_keys.add(entry["key"])
    for entry in index.entries:
        variant_score = _title_variant_score(node["title"], entry["title"])
        if (not variant_score or entry["key"] in seen_keys
                or (entry["subtree_chars"] < min_candidate_chars and not entry["children_count"])):
            continue
        add(entry, variant_score, synonym=True)

    for entry in index.entries:
        near_score = _near_title_score(node["title"], entry["title"])
        if (not near_score or entry["key"] in seen_keys or entry["key"] in reserved
                or entry["subtree_chars"] < REUSE_MIN_TOTAL_CHARS):
            continue
        add(entry, near_score, synonym=True)
        seen_keys.add(entry["key"])

    _best, scored = index.resolve_exact(node)
    for item in scored:
        entry = item["entry"]
        if (not item["copyable"] or entry["key"] in reserved
                or (scope_key and not in_scope(entry, scope_key))):
            continue
        if entry["norm_title"] == node.get("norm_title"):
            add(entry, 1.0)
        else:
            add(entry, item["context_score"])
    if scope_key:
        scope_entry = index.by_key.get(scope_key)
        if scope_entry and scope_entry["key"] not in reserved:
            add(scope_entry, similarity(parent_title, scope_entry["title"]), scope_candidate=True)
    pool.sort(key=lambda item: (item.get("scope_material", False), -item["combined"],
                               -item["title_score"], item["entry"]["doc_order"]))
    return pool[:max(top_k, 6)]


def _accept_migration(best, threshold):
    """是否接受语义候选迁移。

    候选池按"标题相似/同义族/素材范围"召回；是否真的迁移必须过章节规范这一关：
    combined = 0.55×标题相似 + 0.45×规范贴合（+素材范围加分）。只靠标题像、正文与本节
    规范完全不搭的候选不迁移，转证据撰写——否则会出现"建设地点"迁"建设目标"、
    "项目建设单位"迁"项目建设依据"这类同前缀误迁。

    同义标题族（含"运行维护系统设计方案 ← 运维方案"这类）不受阈值约束。
    """
    if best["synonym"] or (best.get("table_match") and best["title_score"] >= 0.5):
        return True
    return best["combined"] >= threshold


# ------------------------------------------------------------------ 锚点（人工 / 自动派生）
def _apply_override(decision, node, entry, override, spec, keywords, index):
    mode = override.get("mode") or ("copy" if entry["norm_title"] == node.get("norm_title") else "migrate")
    note = override.get("note") or ""
    provenance = {}
    if override.get("auto"):                       # anchor 命令派生的锚点：标清来路与得分
        detail = note or ("判读回填" if override.get("decided") else "保序最优分配")
        if override.get("score") is not None:
            detail = "%s，序位对齐得分 %.3f" % (detail, override["score"])
        reasons = ["自动锚点：%s → %s（%s）" % (node["title"], entry["title"], detail)]
        provenance = {"anchor_auto": True, "anchor_tier": override.get("tier"),
                      "anchor_score": override.get("score"),
                      "anchor_rule": override.get("auto_rule")}
    else:
        reasons = ["手工锚点：%s → %s（%s）" % (node["title"], entry["title"], note or "用户指定")]
    if mode == "copy":
        decision.update({
            "mode": "exact_direct_copy",
            "matched_source": _entry_ref(entry),
            "reasons": reasons + ["按锚点整棵子树直复，不改写"],
            "next_actions": ["author：整棵子树直接复制（LLM_REWRITE_COUNT=0）"],
            "manual_override": True,
            **provenance,
        })
    elif mode == "migrate":
        decision.update({
            "mode": "semantic_migrate",
            "matched_source": _entry_ref(entry),
            "migrate_from": {"title": entry["title"], "number": entry["number"], "key": entry["key"],
                             "title_score": 1.0, "spec_score": None, "synonym": False, "miss": []},
            "reasons": reasons + ["整段迁移后按规范补足"],
            "next_actions": ["author：整段迁移并按目标层级重挂标题，再按规范补足缺失要素"],
            "manual_override": True,
            **provenance,
        })
    else:
        decision.update({
            "mode": "grounded_write",
            "matched_source": _entry_ref(entry),
            "evidence_scope": _scope_ref(index, node_by_key(index.tree, entry["key"]) or entry),
            "reasons": reasons + ["以该节点为素材范围按规范撰写"],
            "next_actions": ["以《%s》为素材范围撰写本节" % entry["title"]],
            "manual_override": True,
            **provenance,
        })
    fit = index.spec_fit(entry, keywords) if keywords else {"score": 0.0, "hit": [], "miss": []}
    decision["spec_coverage"] = fit


def _scope_ref(index, node):
    text = index.text_of_key(node["key"], limit=600) or ""
    return {"key": node["key"], "number": node["number"], "title": node["title"],
            "subtree_chars": node["subtree_chars"], "own_chars": node.get("own_chars", 0),
            "children": [child["title"] for child in (node.get("children") or [])[:8]],
            "excerpt": " ".join(text.split())[:300]}


def route_scope(index, specs, nodes, **options):
    decisions = [route_node(index, specs, node, **options) for node in nodes]
    summary = {mode: 0 for mode in MODE_PRIORITY}
    for decision in decisions:
        summary[decision["mode"]] = summary.get(decision["mode"], 0) + 1
    return decisions, summary


def _entry_ref(entry, *, score=None):
    ref = {"key": entry["key"], "number": entry["number"], "title": entry["title"],
           "subtree_chars": entry["subtree_chars"], "tables": entry["tables"], "images": entry["images"],
           "children_count": entry["children_count"], "path_titles": entry["path_titles"]}
    if score is not None:
        ref["score"] = score
    return ref


def _candidate_ref(item):
    ref = _entry_ref(item["entry"])
    ref.update({"title_score": item["title_score"], "spec_score": item["spec_score"],
                "combined": item["combined"], "synonym": item["synonym"],
                "table_match": item.get("table_match", False),
                "scope_match": item.get("scope_match", False),
                "scope_candidate": item.get("scope_candidate", False),
                "hit": item["hit"][:10], "miss": item["miss"][:10]})
    return ref
