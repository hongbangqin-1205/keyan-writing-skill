# -*- coding: utf-8 -*-
"""领域锚点自动派生：模板域 ↔ 建设方案域的保序最优分配（方案 A＋B）。

人工锚点（``match/来源覆盖.json``）回答的是"这一节该从哪来"，但每换一份输入文件就得
重写一遍。本模块把这件事变成可复算的派生：

- **保序（A）**：同级配对沿文档顺序单调推进，不允许交叉。两棵科目树的同级次序本身
  就是证据，越过它去配"看起来更像"的节点，通常是把结构讲错了。
- **最优（B）**：在保序前提下用序列对齐（Needleman–Wunsch）求总得分最大的配对，两侧
  都允许留空，于是"模板新增""来源独有"这类结构差不会被硬凑成一对。
- **分档**：高分直接落锚；中分落锚但进复核清单；低分只进复核清单，由 agent（方案 D）
  判读后回填。

打分只用可核验的结构证据，不做语义猜测：标题相似度、子树体量比、表数/图数一致度、
子节点数一致度。分项写进锚点的 ``basis``，复核时能直接看出"为什么配到这里"。
"""
import datetime

from .headings import normalize_title, similarity

HIGH_TIER = 0.60           # ≥ 该分数：直接落锚
MID_TIER = 0.35            # ≥ 该分数：落锚但进复核清单；低于则只进复核清单
COPY_MIN_SCORE = 0.60      # 判"同构子树"的最低自身得分
COPY_MIN_COVERAGE = 0.60   # 同构子树：已配对子节点占较少一侧的比例下限
COPY_MIN_MEAN = 0.50       # 同构子树：已配对子节点的平均配对分下限
CANDIDATE_SLOTS = 3        # 复核清单里每个节点给出几个备选

WEIGHTS = {"title": 0.50, "volume": 0.28, "tables": 0.08, "images": 0.07, "children": 0.07}

PART_LABELS = {"title": "标题", "volume": "体量", "tables": "表", "images": "图", "children": "子"}

MODE_LABELS = {"copy": "整棵直复", "migrate": "整段迁移后按规范补足", "write": "只作素材范围"}


def _ratio(left, right):
    """0~1 一致度；两边都缺（0:0）视为完全一致。"""
    left, right = left or 0, right or 0
    if not left and not right:
        return 1.0
    return round(min(left, right) / max(left, right), 4)


def pair_score(template_node, source_node):
    """一对节点的结构证据得分（0~1）与分项。"""
    parts = {
        "title": round(similarity(template_node.get("title", ""), source_node.get("title", "")), 4),
        "volume": _ratio(template_node.get("subtree_chars"), source_node.get("subtree_chars")),
        "tables": _ratio((template_node.get("tables") or 0) + 1, (source_node.get("tables") or 0) + 1),
        "images": _ratio((template_node.get("images") or 0) + 1, (source_node.get("images") or 0) + 1),
        "children": _ratio((template_node.get("children_count") or 0) + 1,
                           (source_node.get("children_count") or 0) + 1),
    }
    score = sum(WEIGHTS[key] * value for key, value in parts.items())
    return {"score": round(score, 4), "parts": parts}


def format_basis(score_payload):
    """拼出「标题 0.88 / 体量 0.99 / 子 1.00」这样的一行依据。"""
    parts = score_payload.get("parts", {})
    return " / ".join("%s %.2f" % (PART_LABELS[key], parts[key]) for key in WEIGHTS if key in parts)


def align_children(template_children, source_children):
    """保序最优分配（Needleman–Wunsch）。

    返回 ``(pairs, only_template, only_source)``：``pairs`` 保序且总分最大，两侧留空者
    分别进 ``only_template`` / ``only_source``（模板新增 / 来源独有）。
    """
    template_children = list(template_children or [])
    source_children = list(source_children or [])
    rows, cols = len(template_children), len(source_children)
    table = [[pair_score(t, s) for s in source_children] for t in template_children]
    dp = [[0.0] * (cols + 1) for _ in range(rows + 1)]
    back = [[None] * (cols + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        dp[i][0], back[i][0] = dp[i - 1][0], "up"
    for j in range(1, cols + 1):
        dp[0][j], back[0][j] = dp[0][j - 1], "left"
    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            diag = dp[i - 1][j - 1] + table[i - 1][j - 1]["score"]
            up, left = dp[i - 1][j], dp[i][j - 1]
            if diag >= up and diag >= left:          # 平手时优先配对，让并列走结构
                dp[i][j], back[i][j] = diag, "diag"
            elif up >= left:
                dp[i][j], back[i][j] = up, "up"
            else:
                dp[i][j], back[i][j] = left, "left"
    pairs, only_template, only_source = [], [], []
    i, j = rows, cols
    while i > 0 or j > 0:
        step = back[i][j]
        if step == "diag":
            pairs.append({"template": template_children[i - 1], "source": source_children[j - 1],
                          **table[i - 1][j - 1]})
            i, j = i - 1, j - 1
        elif step == "up":
            only_template.append(template_children[i - 1])
            i -= 1
        else:
            only_source.append(source_children[j - 1])
            j -= 1
    pairs.reverse()
    only_template.reverse()
    only_source.reverse()
    return pairs, only_template, only_source


def order_preserved(pairs):
    """配对是否沿两侧文档顺序单调推进（保序约束的复检位）。"""
    template_orders = [item["template"].get("doc_order", 0) for item in pairs]
    source_orders = [item["source"].get("doc_order", 0) for item in pairs]
    return template_orders == sorted(template_orders) and source_orders == sorted(source_orders)


def structural_parallel(template_node, source_node, pairs):
    """子树是否同构：同构走整棵直复（copy），不同构只当素材范围（write）。"""
    score = pair_score(template_node, source_node)["score"]
    fewer = min(template_node.get("children_count") or 0, source_node.get("children_count") or 0)
    if fewer <= 1 and normalize_title(template_node.get("title", "")) == normalize_title(
            source_node.get("title", "")):
        return score >= MID_TIER                         # 同名且子级很浅：直接当同构
    if not pairs or fewer < 2:
        return False
    coverage = len(pairs) / float(fewer)
    mean = sum(item["score"] for item in pairs) / len(pairs)
    return score >= COPY_MIN_SCORE and coverage >= COPY_MIN_COVERAGE and mean >= COPY_MIN_MEAN


def choose_mode(template_node, source_node, pairs):
    """copy=整棵直复；migrate=整段迁移后按规范补足；write=只作素材范围。

    证据够（同构、叶子、或配对分达线）就尽量复用正文，只有对不上又不够像的容器才退到
    "只作素材范围"，免得把来源子树整段灌进来、和子节点重复。
    """
    if structural_parallel(template_node, source_node, pairs):
        return "copy"
    score = pair_score(template_node, source_node)["score"]
    if not (template_node.get("children_count") or 0):
        # 叶子没有下层可拆：够像才整段迁移，连 MID 线都不到说明是硬凑的一对，只当素材。
        return "migrate" if score >= MID_TIER else "write"
    return "migrate" if score >= COPY_MIN_SCORE else "write"


def _node_ref(node):
    return {"key": node.get("key"), "number": node.get("number"), "title": node.get("title"),
            "children_count": node.get("children_count") or 0,
            "subtree_chars": node.get("subtree_chars") or 0, "tables": node.get("tables") or 0,
            "images": node.get("images") or 0, "path_titles": list(node.get("path_titles") or [])}


def _stamp():
    return datetime.datetime.now().isoformat(timespec="seconds")


def derive_anchors(template_root, source_root, *, depth=2, high=HIGH_TIER, mid=MID_TIER,
                   excludes=frozenset(), origins=None, stamp=None):
    """递归派生锚点。返回 ``(anchors, review, summary)``。

    ``anchors`` 形状与 ``match/来源覆盖.json`` 一致（外加 ``auto``/``tier``/``score``/
    ``basis``/``auto_rule`` 供复核）；``review`` 是待判读清单，交给方案 D。

    ``excludes`` 里的模板节点不落锚；``origins``（模板 key → 建设方案 key）用于已有人工
    锚点的节点——同样不落锚，但**沿用该来源继续往下派生**，免得子树被对到别的域上。
    """
    stamp = stamp or _stamp()
    origins = origins or {}
    anchors, review = {}, []
    source_index = _index_subtree(source_root)

    def candidates_for(template_node, source_children):
        scored = sorted((dict(pair_score(template_node, s), source=s) for s in source_children),
                        key=lambda item: -item["score"])
        return [{"number": item["source"].get("number"), "title": item["source"].get("title"),
                 "key": item["source"].get("key"), "score": item["score"],
                 "basis": format_basis(item)} for item in scored[:CANDIDATE_SLOTS]]

    def visit(template_node, source_node, level, trail, aligned=None):
        parents = trail + [template_node.get("number")]
        if aligned is None:
            aligned = align_children(template_node.get("children"), source_node.get("children"))
        pairs, only_template, only_source = aligned
        for item in pairs:
            template_child, source_child = item["template"], item["source"]
            tier = "high" if item["score"] >= high else ("mid" if item["score"] >= mid else "low")
            basis = format_basis(item)
            pinned = origins.get(template_child.get("key"))
            child_pairs, child_only_template, child_only_source = align_children(
                template_child.get("children"), source_child.get("children"))
            if pinned or template_child.get("key") in excludes:
                review.append({"tier": "excluded", "action": "excluded",
                               "template": _node_ref(template_child), "source": _node_ref(source_child),
                               "score": item["score"], "basis": basis, "path": "/".join(parents),
                               "pinned": pinned})
            elif tier == "low":
                review.append({"tier": tier, "action": "confirm",
                               "template": _node_ref(template_child), "source": _node_ref(source_child),
                               "score": item["score"], "basis": basis, "path": "/".join(parents),
                               "candidates": candidates_for(template_child, source_node.get("children") or [])})
            else:
                mode = choose_mode(template_child, source_child, child_pairs)
                anchors[template_child["key"]] = {
                    "source": source_child["key"], "mode": mode, "auto": True, "tier": tier,
                    "score": item["score"], "basis": basis, "auto_rule": "保序最优分配（A+B）",
                    "note": "保序最优分配（A+B）",
                    "source_title": source_child.get("title"),
                    "source_number": source_child.get("number"), "updated_at": stamp,
                }
                if tier == "mid":
                    review.append({"tier": tier, "action": "confirm",
                                   "template": _node_ref(template_child), "source": _node_ref(source_child),
                                   "score": item["score"], "basis": basis, "path": "/".join(parents),
                                   "candidates": candidates_for(template_child, source_node.get("children") or [])})
            child_source = source_child
            if pinned:
                child_source = source_index.get(pinned) or source_child
                if child_source is not source_child:
                    child_pairs, child_only_template, child_only_source = align_children(
                        template_child.get("children"), child_source.get("children"))
            if level < depth and template_child.get("children") and child_source.get("children"):
                visit(template_child, child_source, level + 1, parents,
                      (child_pairs, child_only_template, child_only_source))
        for template_child in only_template:
            pinned = origins.get(template_child.get("key"))
            review.append({"tier": "excluded" if pinned else "unmatched_template",
                           "action": "excluded" if pinned else "new",
                           "template": _node_ref(template_child), "source": None, "score": None,
                           "basis": "已有人工锚点，沿用其来源派生" if pinned else "来源侧无对应节点",
                           "path": "/".join(parents), "pinned": pinned,
                           "candidates": candidates_for(template_child, source_node.get("children") or [])})
            origin_node = source_index.get(pinned) if pinned else None
            if origin_node is not None and level < depth and template_child.get("children"):
                visit(template_child, origin_node, level + 1, parents)
        for source_child in only_source:
            review.append({"tier": "unmatched_source", "action": "ignore",
                           "template": None, "source": _node_ref(source_child), "score": None,
                           "basis": "模板侧无对应节点", "path": "/".join(parents)})

    root_pairs = []
    if template_root.get("children") and source_root.get("children"):
        root_pairs, _, _ = align_children(template_root.get("children"), source_root.get("children"))
    visit(template_root, source_root, 1, [])
    tiers = sorted({item["tier"] for item in review})
    summary = {
        "scope": template_root.get("number"), "from": source_root.get("number"),
        "root_pairs": len(root_pairs), "depth": depth, "high": high, "mid": mid,
        "anchors": len(anchors),
        "high_count": sum(1 for item in anchors.values() if item["tier"] == "high"),
        "mid_count": sum(1 for item in anchors.values() if item["tier"] == "mid"),
        "copy_count": sum(1 for item in anchors.values() if item["mode"] == "copy"),
        "order_preserved": order_preserved(root_pairs), "review": len(review),
        "review_tiers": {tier: sum(1 for item in review if item["tier"] == tier) for tier in tiers},
    }
    return anchors, review, summary


def autodetect_source_parent(template_root, tree, *, max_level=2, min_children=2):
    """没给 --from 时，挑与模板域子表最合得来的来源父节点。返回排序后的候选。"""
    from .tree import iter_nodes

    ranked = []
    for node in iter_nodes(tree.get("chapters", [])):
        if node.get("key") == template_root.get("key") or (node.get("level") or 0) > max_level:
            continue
        if (node.get("children_count") or 0) < min_children:
            continue
        pairs, _, _ = align_children(template_root.get("children"), node.get("children"))
        if not pairs:
            continue
        total = sum(item["score"] for item in pairs)
        ranked.append({"key": node["key"], "number": node["number"], "title": node["title"],
                       "pairs": len(pairs), "mean": round(total / len(pairs), 4),
                       "total": round(total, 4)})
    ranked.sort(key=lambda item: (-item["mean"], -item["pairs"]))
    return ranked


TITLES = {"mid": "中分待确认（已落锚，确认后可保留或改判）",
          "low": "低分待判读（未落锚，需指定来源或判为模板新增）",
          "excluded": "已有人工锚点或已排除（不参与自动派生）",
          "unmatched_template": "模板独有（来源侧无对应）",
          "unmatched_source": "来源独有（模板侧无对应，默认忽略）"}


def render_review(review, summary, *, decisions_path, apply_cmd):
    """「待判读清单」Markdown：agent 按方案 D 判读后回填 JSON 再 --apply。"""
    lines = ["# 锚点复核清单 · %s %s ↔ %s %s"
             % (summary["scope"], summary.get("scope_title", ""), summary["from"],
                summary.get("from_title", "")), "",
             "自动派生：%d 个节点已落锚（高分 %d / 中分 %d），%d 条待判读。"
             % (summary["anchors"], summary["high_count"], summary["mid_count"], summary["review"]),
             "保序约束复检：%s。" % ("通过" if summary["order_preserved"] else "**不通过，需人工检查**"), "",
             "判读后把结论写进 `%s`，再执行：" % decisions_path, "",
             "```", apply_cmd, "```", "",
             "裁决格式（`mode` 省略时按标题是否同名自动定：同名 copy、叶子 migrate、容器 write）：", "",
             "```json",
             '{ "chapter_05_06_04_03": { "action": "accept", "source": "chapter_09_04_03" } }',
             "```", "",
             "`action` 取值：`accept`=采纳该来源；`reject`=不落锚并排除，交回归属仲裁；"
             "`new`=模板新增、来源侧确无对应；`ignore`=来源独有、可忽略。", ""]
    for tier in ("mid", "low", "excluded", "unmatched_template", "unmatched_source"):
        rows = [item for item in review if item["tier"] == tier]
        if not rows:
            continue
        lines.extend(["## %s（%d）" % (TITLES[tier], len(rows)), ""])
        for item in rows:
            template_ref, source_ref = item.get("template"), item.get("source")
            head = template_ref["number"] if template_ref else "—"
            title = template_ref["title"] if template_ref else (source_ref or {}).get("title", "")
            lines.append("- **%s %s**" % (head, title))
            if source_ref and item["score"] is not None:
                lines.append("  - 自动判为 → `%s %s`（得分 %.3f；%s）"
                             % (source_ref["number"], source_ref["title"], item["score"], item["basis"]))
            else:
                lines.append("  - 自动判为 → %s" % item["basis"])
            if template_ref:
                lines.append("  - 模板侧：子 %d / %d 字" % (template_ref["children_count"],
                                                          template_ref["subtree_chars"]))
            for candidate in item.get("candidates") or []:
                lines.append("  - 备选：`%s %s`（%.3f）" % (candidate["number"], candidate["title"],
                                                           candidate["score"]))
            lines.append("  - 所属：%s" % item.get("path", ""))
        lines.append("")
    resolved = summary.get("resolved") or []
    if resolved:
        lines.extend(["## 已判读（%d）" % len(resolved), ""])
        for item in resolved:
            lines.append("- `%s` %s → %s（%s）"
                         % (item["key"], item.get("title") or "", item.get("source_title")
                            or item.get("source") or "—", item["action"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ------------------------------------------------------------------ 方案 D：判读回填
DECISION_ACTIONS = ("accept", "reject", "new", "ignore")


def _index_subtree(root):
    """把子树摊平成 key → node（判读回填要按 key 找回节点）。"""
    found = {}

    def walk(node):
        found[node.get("key")] = node
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    return found


def apply_decisions(template_root, source_root, decisions, *, depth=2, high=HIGH_TIER,
                    mid=MID_TIER, excludes=frozenset(), origins=None, stamp=None):
    """A+B 派生后再用方案 D 的判读结论覆盖，返回 ``(anchors, review, summary)``。

    ``decisions`` 以被裁定的节点 key 为键：模板节点用 ``accept``（可带 ``source``/``mode``）、
    ``reject``、``new``；建设方案节点用 ``ignore``。判读过的条目不再进复核清单，改记进
    ``summary["resolved"]``。
    """
    anchors, review, summary = derive_anchors(template_root, source_root, depth=depth, high=high,
                                              mid=mid, excludes=excludes, origins=origins,
                                              stamp=stamp)
    template_nodes = _index_subtree(template_root)
    source_nodes = _index_subtree(source_root)
    resolved, diagnostics = [], []
    counts = {action: 0 for action in DECISION_ACTIONS}
    for key in sorted(decisions):
        decision = decisions[key] or {}
        action = (decision.get("action") or "").lower()
        if action not in DECISION_ACTIONS:
            diagnostics.append("unknown_action: %s 的 action=%r 不在 %s 内"
                               % (key, decision.get("action"), "/".join(DECISION_ACTIONS)))
            continue
        template_node = template_nodes.get(key)
        if template_node is not None:
            record = {"key": key, "action": action, "title": template_node.get("title")}
            if action == "accept":
                source_key = decision.get("source") or (anchors.get(key) or {}).get("source")
                source_node = source_nodes.get(source_key)
                if source_node is None:
                    diagnostics.append("decision_source_missing: %s 指定的来源 %s 不在 %s 子树内"
                                       % (key, source_key, source_root.get("number")))
                    continue
                child_pairs, _, _ = align_children(template_node.get("children"),
                                                   source_node.get("children"))
                score = pair_score(template_node, source_node)
                mode = decision.get("mode") or choose_mode(template_node, source_node, child_pairs)
                anchors[key] = {
                    "source": source_node["key"], "mode": mode, "auto": True, "tier": "decided",
                    "score": score["score"], "basis": format_basis(score),
                    "auto_rule": "方案 D 判读回填", "note": decision.get("note") or "判读确认",
                    "source_title": source_node.get("title"), "source_number": source_node.get("number"),
                    "decided": True, "updated_at": stamp or _stamp(),
                }
                record.update({"source": source_node["key"], "source_title": source_node.get("title"),
                               "mode": mode})
            else:                                   # reject / new：不落锚
                anchors.pop(key, None)
                record["source"] = (decision.get("source") or "").strip() or None
            counts[action] += 1
            resolved.append(record)
            continue
        if action == "ignore" and key in source_nodes:
            detached = [item for item, value in anchors.items() if value.get("source") == key]
            for item in detached:
                anchors.pop(item)
            counts["ignore"] += 1
            resolved.append({"key": key, "action": action, "title": source_nodes[key].get("title"),
                             "detached": detached})
            continue
        diagnostics.append("unknown_node: 判读项 %s 不在模板 %s 或建设方案 %s 子树内"
                           % (key, template_root.get("number"), source_root.get("number")))
    decided_keys = {item["key"] for item in resolved}
    review = [item for item in review
              if (item.get("template") or {}).get("key") not in decided_keys
              and (item.get("source") or {}).get("key") not in decided_keys]
    tiers = sorted({item["tier"] for item in review})
    summary.update({
        "anchors": len(anchors),
        "high_count": sum(1 for item in anchors.values() if item["tier"] == "high"),
        "mid_count": sum(1 for item in anchors.values() if item["tier"] == "mid"),
        "decided_count": sum(1 for item in anchors.values() if item["tier"] == "decided"),
        "copy_count": sum(1 for item in anchors.values() if item["mode"] == "copy"),
        "review": len(review),
        "review_tiers": {tier: sum(1 for item in review if item["tier"] == tier) for tier in tiers},
        "decision_counts": counts, "resolved": resolved, "decision_diagnostics": diagnostics,
    })
    return anchors, review, summary
