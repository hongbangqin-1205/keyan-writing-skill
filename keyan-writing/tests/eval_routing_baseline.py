# -*- coding: utf-8 -*-
"""路由基线 Eval fixture（不参与 pytest 生产流程）。

引入 LLM Reranker 之前，先固化一条 deterministic baseline：同一批用例上
比较 reranker 前后的召回与误迁，避免“感觉变好了”式结论。

用法（不依赖 pytest / 网络 / LLM）：

    python -X utf8 tests/eval_routing_baseline.py            # 人读摘要
    python -X utf8 tests/eval_routing_baseline.py --json     # 机读 JSON

四组核心用例（HEADLINE，计入首屏四项指标）：

    synonym_positive          显式同义族，期望 semantic_migrate
    prefix_false_positive     仅共享前缀、语义不同，期望不迁移
    cross_scope_false_positive 异章/范围外来源，期望不迁移（P1-1 不变量）
    normal_semantic_positive  非词表的正常语义命中，期望 semantic_migrate

另有一组 long_tail_positive（长尾正例）不计入首屏指标：它们是语义上确实同指、
但当前 deterministic 路由器综合分不足以迁移、只能回落 grounded_write 的用例，
单独统计为 headroom，作为 LLM Reranker A/B 要吃掉的目标。

四项指标（K = RECALL_K）：

    recall@K                  正例中，期望来源出现在候选池前 K 的比例
    top1_route_accuracy       全部用例中，首位路由结论符合期望的比例
    wrong_migration_rate      反例中被误判为 semantic_migrate 的比例（越低越好）
    grounded_write_fallback   正例中未能迁移、回落 grounded_write 的比例（越低越好）

    headroom.deterministic_miss_rate  长尾正例中确定性路由漏迁的比例（reranker 待改进量）
"""
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from keyan.headings import normalize_title
from keyan.matching import SourceIndex
from keyan.routing import _semantic_candidates, route_node
from keyan.tree import tree_from_dict

RECALL_K = 3
HEADLINE_GROUPS = ("synonym_positive", "prefix_false_positive",
                   "cross_scope_false_positive", "normal_semantic_positive")
LONG_TAIL_GROUP = "long_tail_positive"


# ------------------------------------------------------------------ 夹具
def _mk(spec, key="chapter_01", number="1", path=()):
    title, chars, children, tables = spec
    node = {"key": key, "number": number, "level": len(path) + 1, "depth": len(path) + 1,
            "title": title, "norm_title": normalize_title(title), "style": "",
            "leaf": not children, "own_chars": chars, "subtree_chars": chars,
            "tables": tables, "images": 0, "children_count": len(children),
            "doc_order": 1, "own_start": 0, "own_end": 0,
            "path_titles": list(path) + [title], "children": []}
    for index, child in enumerate(children, 1):
        node["children"].append(_mk(child, "%s_%02d" % (key, index),
                                    "%s.%d" % (number, index), node["path_titles"]))
    node["subtree_chars"] = node["own_chars"] + sum(c["subtree_chars"] for c in node["children"])
    node["tables"] = node["tables"] + sum(c["tables"] for c in node["children"])
    return node


def _index_of(specs):
    chapters = [_mk(spec, "chapter_%02d" % index, str(index))
                for index, spec in enumerate(specs, 1)]
    tree = {"name": "", "path": "", "stats": {}, "max_depth": 3, "node_count": 0,
            "leaf_count": 0, "chapters": chapters}
    return SourceIndex(tree_from_dict(tree), [])


def _target(title, key="tpl"):
    return {"key": key, "number": "9.9", "title": title,
            "norm_title": normalize_title(title), "level": 1, "depth": 1,
            "path_titles": ["模板章", title], "own_chars": 0, "subtree_chars": 0,
            "tables": 0, "images": 0, "children_count": 0, "leaf": True, "doc_order": 1,
            "children": []}


def _single_case(group, target, candidate):
    """单个候选章：正例期望迁到 chapter_01，反例期望不迁。"""
    return {"group": group, "target": target,
            "specs": [(candidate, 900, [], 0)],
            "arbitration": None, "scope_key": None,
            "expect": "migrate", "gold": "chapter_01"}


# --- A. 显式同义族正例（10）
SYNONYM_POSITIVE = [
    ("网络拓扑", "网络架构"),
    ("总体架构", "总体框架"),
    ("投资估算", "投资预算"),
    ("安全系统设计方案", "安全设计"),
    ("运行维护系统设计方案", "运维方案"),
    ("信息资源共享", "数据共享"),
    ("建设内容和规模", "建设规模"),
    ("主要研究结论", "研究结论"),
    ("建设管理方案", "项目管理方案"),
    ("编制依据", "编制依据与范围"),
]

# --- B. 前缀假阳反例（10）：只共享前缀，不是同一写作对象
PREFIX_FALSE_POSITIVE = [
    ("项目建设单位", "项目建设依据"),
    ("项目建设单位", "项目建设内容"),
    ("建设目标", "建设内容"),
    ("建设任务", "建设目标"),
    ("项目建设目标", "项目建设内容"),
    ("建设规模", "建设目标"),
    ("资金来源", "资金使用计划"),
    ("项目概况", "项目单位概况"),
    ("风险识别", "风险管控"),
    ("建设背景", "建设目标"),
]

# --- D. 正常语义正例（10）：不在同义词表内，但标题确实同指（变体/近邻/后缀限定）
NORMAL_SEMANTIC_POSITIVE = [
    ("项目建设期", "项目建设周期"),
    ("数据备份策略", "数据备份策略设计"),
    ("建设目标", "项目建设目标"),
    ("建设标准", "项目建设标准"),
    ("培训计划", "项目培训计划"),
    ("验收标准", "项目验收标准"),
    ("监测指标", "项目监测指标"),
    ("配套工程", "项目配套工程"),
    ("分类目录", "项目分类目录"),
    ("运行环境", "项目运行环境"),
]

# --- C. 跨范围假阳反例（10）
_OPS_CHAPTER = ("运行维护系统设计方案", 100, [("运行维护内容", 900, [], 0)], 0)

# --- E. 长尾正例（5）：语义同指但当前确定性综合分不足，作为 reranker 改进空间
LONG_TAIL_POSITIVE = [
    ("机房环境建设", "机房环境"),
    ("数据备份与容灾恢复", "数据备份"),
    ("标准规范体系建设", "标准规范体系"),
    ("数据中台建设", "数据中台"),
    ("门户网站建设", "门户网站"),
]

# C1（5）范围不匹配：同义候选落在 scope 章之外，必须被 in_scope 挡住
CROSS_SCOPE_SCOPE_MISMATCH = [
    "网络架构", "安全设计", "运维方案", "数据架构", "部署架构",
]

# C2（5）异章同名子树被 exact_out_of_scope 降级后，祖先标题不得换通道绕回
CROSS_SCOPE_DEMOTED_ANCESTOR = [
    ("建设目标", "项目建设目标与建设内容", "建设目标"),
    ("建设内容", "项目建设目标与建设内容", "建设内容"),
    ("建设规模", "项目建设内容与规模", "建设规模"),
    ("总体架构", "项目总体架构与总体框架", "总体框架"),
    ("安全设计", "安全系统设计方案与安全体系", "安全体系"),
]


def build_cases():
    cases = []
    for target, candidate in SYNONYM_POSITIVE:
        cases.append(_single_case("synonym_positive", target, candidate))
    for target, candidate in PREFIX_FALSE_POSITIVE:
        case = _single_case("prefix_false_positive", target, candidate)
        case["expect"] = "block"
        case["gold"] = None
        cases.append(case)
    for target, candidate in NORMAL_SEMANTIC_POSITIVE:
        cases.append(_single_case("normal_semantic_positive", target, candidate))
    for candidate in CROSS_SCOPE_SCOPE_MISMATCH:
        cases.append({
            "group": "cross_scope_false_positive", "target": "网络拓扑",
            "specs": [(candidate, 900, [], 0), _OPS_CHAPTER],
            "arbitration": {"scope": {"tpl": "chapter_02"}},
            "scope_key": "chapter_02", "expect": "block", "gold": None,
        })
    for target, ancestor, child in CROSS_SCOPE_DEMOTED_ANCESTOR:
        cases.append({
            "group": "cross_scope_false_positive", "target": target,
            "specs": [(ancestor, 100, [(child, 900, [], 0)], 0), _OPS_CHAPTER],
            "arbitration": {"scope": {"tpl": "chapter_02"},
                            "demoted": {"tpl": {"source": "chapter_01_01",
                                                "source_title": child,
                                                "reason": "exact_out_of_scope",
                                                "scope": "chapter_02"}}},
            "scope_key": "chapter_02", "expect": "block", "gold": None,
        })
    for target, candidate in LONG_TAIL_POSITIVE:
        cases.append(_single_case(LONG_TAIL_GROUP, target, candidate))
    return cases


# ------------------------------------------------------------------ 运行
def evaluate():
    cases = build_cases()
    rows = []
    for case in cases:
        index = _index_of(case["specs"])
        target = _target(case["target"])
        pool = _semantic_candidates(index, target, [], top_k=8, min_candidate_chars=120,
                                    arbitration=case["arbitration"],
                                    scope_key=case["scope_key"])
        decision = route_node(index, None, target, arbitration=case["arbitration"],
                              paragraphs=[], materials=[])
        mode = decision.get("mode")
        matched = (decision.get("matched_source") or {}).get("key")
        cand_keys = [item["key"] for item in decision.get("candidates") or []]
        recall_hit = bool(case["gold"]) and case["gold"] in cand_keys[:RECALL_K]
        migrated = mode == "semantic_migrate"
        if case["expect"] == "migrate":
            correct = migrated and matched == case["gold"]
        else:
            correct = not migrated
        rows.append({"group": case["group"], "target": case["target"], "expect": case["expect"],
                     "mode": mode, "matched": matched, "recall_hit": recall_hit,
                     "correct": correct, "pool": cand_keys})

    headline = [row for row in rows if row["group"] in HEADLINE_GROUPS]
    positives = [row for row in headline if row["expect"] == "migrate"]
    negatives = [row for row in headline if row["expect"] == "block"]
    metrics = {
        "cases": len(headline),
        "recall_at_%d" % RECALL_K: round(
            sum(row["recall_hit"] for row in positives) / max(1, len(positives)), 4),
        "top1_route_accuracy": round(
            sum(row["correct"] for row in headline) / max(1, len(headline)), 4),
        "wrong_migration_rate": round(
            sum(row["mode"] == "semantic_migrate" for row in negatives) / max(1, len(negatives)), 4),
        "grounded_write_fallback_rate": round(
            sum(row["mode"] == "grounded_write" for row in positives) / max(1, len(positives)), 4),
    }
    long_tail = [row for row in rows if row["group"] == LONG_TAIL_GROUP]
    headroom = {
        "cases": len(long_tail),
        "migrated": sum(row["mode"] == "semantic_migrate" for row in long_tail),
        "deterministic_miss_rate": round(
            sum(row["mode"] != "semantic_migrate" for row in long_tail) / max(1, len(long_tail)), 4),
    }
    by_group = {}
    for row in rows:
        bucket = by_group.setdefault(row["group"], {"cases": 0, "correct": 0,
                                                    "grounded_write": 0, "migrate": 0})
        bucket["cases"] += 1
        bucket["correct"] += int(row["correct"])
        bucket["grounded_write"] += int(row["mode"] == "grounded_write")
        bucket["migrate"] += int(row["mode"] == "semantic_migrate")
    return {"metrics": metrics, "headroom": headroom, "by_group": by_group, "rows": rows}


def main():
    result = evaluate()
    if "--json" in sys.argv[1:]:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print("# ROUTING BASELINE (deterministic, no LLM)")
    print("  [headline: 4 core groups]")
    for name, value in result["metrics"].items():
        print("  %-30s %s" % (name, value))
    print("\n  [headroom: long-tail positives, reranker A/B target]")
    for name, value in result["headroom"].items():
        print("  %-30s %s" % (name, value))
    print("\n  by_group:")
    for name in sorted(result["by_group"]):
        print("    %-28s %s" % (name, result["by_group"][name]))
    misses = [row for row in result["rows"] if not row["correct"] and row["group"] in HEADLINE_GROUPS]
    print("\n  mismatches: %d" % len(misses))
    for row in misses:
        print("    [%s] %s -> %s (matched=%s)" % (row["group"], row["target"], row["mode"],
                                                  row["matched"]))


if __name__ == "__main__":
    main()
