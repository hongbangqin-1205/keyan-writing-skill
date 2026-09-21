"""同名直复的归属仲裁：结构上下文 + 规范贴合 + 兄弟组素材范围（scope）。

要解决的问题
------------
泛化标题（建设目标 / 总体架构 / 系统功能设计）在模板里出现多次，在建设方案里却只有一处。
朴素"同名即直复"会把同一段内容搬到多个互不相关的小节——例如把建设方案
"建设目标与建设内容 > 建设目标"整段复制到模板"运行维护系统设计方案 > 建设目标"。

三步做法
--------
1. 兄弟组锚定：某模板父节点的子节点若多数命中同一个建设方案节点的子级，则该父节点的
   素材范围（scope）就是这个建设方案节点；其子节点优先在范围内取同名。
2. 综合分 = 0.45 结构上下文 + 0.25 规范贴合 + 0.30 范围归属。
3. 认领仲裁：同一建设方案节点被多个模板节点同名认领时，分高者直复；分低且结构上下文
   弱（< weak_context）者降级为语义迁移/证据撰写，并在计划里留下诊断。

范围内的同名子节点不存在时（如建设方案 9.9.2 下没有"建设目标"），不做直复，
转语义迁移/证据撰写，并把 scope 节点的子树作为素材范围交给写作。
"""
import datetime
from collections import Counter, defaultdict

from .matching import in_scope
from .specs import spec_keywords
from .tree import iter_nodes

UNKNOWN = "-"

REASON_LABELS = {
    "exact_out_of_scope": "同名候选不在本节素材范围内",
    "exact_claimed_by_better_owner": "同名候选已归属更贴合的小节",
    "exact_source_reserved": "同名候选已被手工锚点占用",
}


def build_arbitration(template_tree, index, specs, *, overrides=None, demote_gap=0.15,
                      weak_context=0.5, scope_quorum=0.5, weight_context=0.45,
                      weight_spec=0.25, weight_scope=0.30):
    """产出模板节点 → 同名直复来源的归属表（含降级与素材范围）。"""
    overrides = overrides or {}
    nodes = list(iter_nodes(template_tree.get("chapters", [])))
    by_key = {node["key"]: node for node in nodes}
    pinned_sources = {item.get("source") for item in overrides.values() if item.get("source")}

    candidates = {}
    for node in nodes:
        if node["key"] in overrides:
            continue                      # 手工锚点优先，不参与仲裁
        items = _candidates_for(node, index, specs)
        if items:
            candidates[node["key"]] = items

    scope, scope_source = _infer_scopes(nodes, candidates, quorum=scope_quorum)
    for node_key, items in candidates.items():
        node_scope = scope.get(node_key)
        for item in items:
            item["scope_match"] = 1.0 if in_scope(item["entry"], node_scope) else 0.0
            item["score"] = round(weight_context * item["context"]
                                  + weight_spec * item["spec_score"]
                                  + weight_scope * item["scope_match"], 4)
            item["basis"] = _basis(item, node_scope, by_key)

    claims, demoted, reused = {}, {}, defaultdict(list)
    users = defaultdict(list)
    for node_key, items in candidates.items():
        ranked = sorted(items, key=lambda item: (-item["score"], -item["context"],
                                                 item["entry"]["doc_order"]))
        users[ranked[0]["entry"]["key"]].append({"node": by_key[node_key], "pick": ranked[0]})

    for source_key, entries in users.items():
        entries.sort(key=lambda item: (-item["pick"]["score"], -item["pick"]["context"],
                                       item["node"]["doc_order"]))
        winner = entries[0]
        for item in entries:
            node, pick = item["node"], item["pick"]
            node_scope = scope.get(node["key"])
            record = {"source": source_key, "source_title": pick["entry"]["title"],
                      "source_number": pick["entry"]["number"], "score": pick["score"],
                      "context": pick["context"], "spec_score": pick["spec_score"],
                      "scope": node_scope, "scope_match": pick["scope_match"],
                      "basis": pick["basis"]}
            if node_scope and not pick["scope_match"]:
                demoted[node["key"]] = _demoted(record, "exact_out_of_scope", by_key,
                                                scope_title=_title_of(by_key, node_scope))
            elif source_key in pinned_sources and item is not winner:
                demoted[node["key"]] = _demoted(record, "exact_source_reserved", by_key)
            elif item is not winner and _demotable(pick, winner["pick"], demote_gap, weak_context):
                record["claimed_by"] = winner["node"]["key"]
                record["claimed_by_title"] = winner["node"]["title"]
                record["claimed_score"] = winner["pick"]["score"]
                demoted[node["key"]] = _demoted(record, "exact_claimed_by_better_owner", by_key)
            else:
                claims[node["key"]] = record
                reused[source_key].append(node["key"])

    for node_key, items in candidates.items():
        if node_key in claims or node_key in demoted:
            continue
        record = {"source": items[0]["entry"]["key"] if items else None,
                  "source_title": items[0]["entry"]["title"] if items else "",
                  "score": items[0]["score"] if items else 0.0,
                  "context": items[0]["context"] if items else 0.0,
                  "spec_score": items[0]["spec_score"] if items else 0.0,
                  "scope": scope.get(node_key),
                  "scope_match": items[0]["scope_match"] if items else 0.0,
                  "basis": items[0]["basis"] if items else []}
        demoted[node_key] = _demoted(record, "exact_claimed_by_better_owner", by_key)

    return {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "params": {"demote_gap": demote_gap, "weak_context": weak_context,
                   "scope_quorum": scope_quorum, "weight_context": weight_context,
                   "weight_spec": weight_spec, "weight_scope": weight_scope},
        "summary": {
            "template_nodes": len(nodes),
            "claims": len(claims),
            "demoted": len(demoted),
            "demoted_reasons": dict(Counter(record["reason"] for record in demoted.values())),
            "scoped_nodes": len(scope),
            "reused_sources": sum(1 for keys in reused.values() if len(keys) > 1),
            "overrides": len(overrides),
        },
        "claims": claims,
        "demoted": demoted,
        "scope": scope,
        "scope_source": scope_source,
        "reused": {key: value for key, value in reused.items() if len(value) > 1},
    }


# ------------------------------------------------------------------ 报告
def render_report(template_tree, index, arbitration):
    """人读版归属报告：降级清单 + 一源多处复用 + 素材范围。"""
    nodes = {node["key"]: node for node in iter_nodes(template_tree.get("chapters", []))}
    summary = arbitration["summary"]

    def label(key):
        node = nodes.get(key)
        return "%s %s" % (node.get("number"), node.get("title")) if node else key

    lines = ["# 同名直复归属仲裁", "",
             "模板节点 %d：可直复 **%d**｜降级 **%d**｜有素材范围 %d｜被复用来源 %d"
             % (summary["template_nodes"], summary["claims"], summary["demoted"],
                summary["scoped_nodes"], summary["reused_sources"]), "",
             "判定 = 0.45 结构上下文 + 0.25 规范贴合 + 0.30 素材范围归属。",
             "降级 = 标题虽同名，但候选不在本节素材范围内，或已被更贴合的小节占用；",
             "这些节点转语义候选迁移或按素材范围撰写，不再直接复制。", ""]

    demoted = arbitration["demoted"]
    lines += ["## 降级清单（%d）" % len(demoted), "",
              "| 模板节点 | 标题 | 原同名候选 | 综合分 | 原因 | 素材范围 |", "|---|---|---|---|---|---|"]
    for key in sorted(demoted, key=lambda item: label(item)):
        record = demoted[key]
        lines.append("| %s | %s | %s %s | %.2f | %s | %s |" % (
            key, label(key).split(" ", 1)[-1].replace("|", "/"),
            record.get("source_number", ""), record.get("source_title", "").replace("|", "/"),
            record.get("score", 0.0), record.get("label", record.get("reason", "")),
            record.get("scope_title") or (label(record["scope"]) if record.get("scope") else "-")))
    lines.append("")

    reused = arbitration.get("reused") or {}
    lines += ["## 一源多处复用（%d，上下文强，属正常）" % len(reused), "",
              "| 建设方案节点 | 复用模板节点 |", "|---|---|"]
    for source_key, keys in list(reused.items())[:60]:
        entry = index.by_key.get(source_key)
        lines.append("| %s %s | %s |" % (
            entry["number"] if entry else source_key, (entry["title"] if entry else "").replace("|", "/"),
            "、".join(label(key) for key in keys)))
    lines.append("")

    scoped = arbitration.get("scope_source") or {}
    lines += ["## 素材范围锚定（%d 个模板父节点）" % len(scoped), "",
              "| 模板父节点 | 素材范围（建设方案） |", "|---|---|"]
    for key, source_key in list(scoped.items())[:80]:
        entry = index.by_key.get(source_key)
        lines.append("| %s | %s %s（子树 %d 字） |" % (
            label(key), entry["number"] if entry else source_key,
            (entry["title"] if entry else "").replace("|", "/"),
            entry["subtree_chars"] if entry else 0))
    if len(scoped) > 80:
        lines.append("| … | 其余 %d 个见 同名归属.json |" % (len(scoped) - 80))
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ 内部
def _candidates_for(node, index, specs, *, min_chars=40):
    _best, scored = index.resolve_exact(node, min_chars=min_chars)
    items = [item for item in scored if item["copyable"]]
    if not items:
        return []
    spec = specs.spec_for_node(node) if specs else None
    keywords = spec_keywords(spec, extra=node.get("path_titles", [])) if spec else []
    result = []
    for item in items:
        entry = item["entry"]
        fit = index.spec_fit(entry, keywords) if keywords else {"score": 0.0, "hit": [], "miss": []}
        result.append({"entry": entry, "context": item["context_score"],
                       "same_chapter": item["same_chapter"], "spec_score": fit["score"],
                       "spec_hit": fit["hit"][:8], "spec_miss": fit["miss"][:8],
                       "scope_match": 0.0, "score": 0.0, "basis": []})
    return result


def _infer_scopes(nodes, candidates, *, quorum):
    """兄弟组锚定：多数兄弟命中同一来源节点时，该来源节点就是它们的素材范围。"""
    scope, scope_source = {}, {}
    for parent in nodes:
        kids = parent.get("children") or []
        if not kids:
            continue
        counts = Counter()
        for kid in kids:
            items = candidates.get(kid["key"])
            if not items:
                continue
            top = max(items, key=lambda item: (item["context"], item["spec_score"],
                                               -item["entry"]["doc_order"]))
            if top["entry"]["parent_key"]:
                counts[top["entry"]["parent_key"]] += 1
        if not counts:
            continue
        best, hits = counts.most_common(1)[0]
        if hits < max(2, int(len(kids) * quorum + 0.999)):
            continue
        for kid in kids:
            scope.setdefault(kid["key"], best)
        scope[parent["key"]] = best
        scope_source[parent["key"]] = best
    for parent in nodes:                      # 向深层传播：孙子节点继承父节点的素材范围
        parent_scope = scope.get(parent["key"])
        if parent_scope:
            for kid in parent.get("children") or []:
                scope.setdefault(kid["key"], parent_scope)
    return scope, scope_source


def _demotable(pick, winner, gap, weak_context):
    """是否把落选者降级：结构上下文弱且分数明显低于赢家。

    上下文强的复用是合理的（同一系统在概述章与第五章各出现一次），不降级。
    """
    if pick["context"] >= weak_context:
        return False
    return pick["score"] <= winner["score"] - gap


def _basis(item, node_scope, by_key):
    parts = ["上下文 %.2f" % item["context"], "规范贴合 %.2f" % item["spec_score"]]
    if node_scope:
        parts.append("范围命中 %s" % _title_of(by_key, node_scope) if item["scope_match"]
                     else "范围外 %s" % _title_of(by_key, node_scope))
    return parts


def _title_of(by_key, key):
    node = by_key.get(key)
    if not node:
        return key or UNKNOWN
    return "%s %s" % (node.get("number") or "", node.get("title") or "")


def _demoted(record, reason, by_key, *, scope_title=None):
    payload = dict(record)
    payload["reason"] = reason
    payload["label"] = REASON_LABELS.get(reason, reason)
    if scope_title:
        payload["scope_title"] = scope_title
    return payload