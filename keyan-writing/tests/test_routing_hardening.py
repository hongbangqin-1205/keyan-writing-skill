# -*- coding: utf-8 -*-
"""路由正确性加固：同义词、前缀假阳、scope 绕回与语义候选通道准入。"""
import pytest

from keyan import routing
from keyan.headings import candidate_similarity, normalize_title, synonym_related
from keyan.matching import SourceIndex
from keyan.reuse import search_paragraphs
from keyan.routing import _semantic_candidates, route_node
from keyan.tree import tree_from_dict


SYNONYM_PAIRS = [
    ("网络拓扑", "网络架构"),
    ("总体架构", "总体框架"),
    ("投资估算", "投资预算"),
    ("安全系统设计方案", "安全设计"),
    ("运行维护系统设计方案", "运维方案"),
]

PREFIX_PAIRS = [
    ("项目建设单位", "项目建设依据"),
    ("项目建设单位", "项目建设内容"),
    ("建设目标", "建设内容"),
    ("建设任务", "建设目标"),
]


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
    node["subtree_chars"] = node["own_chars"] + sum(child["subtree_chars"]
                                                    for child in node["children"])
    node["tables"] = node["tables"] + sum(child["tables"] for child in node["children"])
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


def _close(index, title, *, arbitration=None, scope_key=None):
    return _semantic_candidates(index, _target(title), [], top_k=8, min_candidate_chars=120,
                                arbitration=arbitration, scope_key=scope_key)


def _titles(pool):
    return [item["entry"]["title"] for item in pool]


def _demoted(source, reason="exact_source_reserved"):
    return {"demoted": {"tpl": {"source": source, "reason": reason}}}


def _isolate_channel(monkeypatch, channel):
    """只留一条召回通道，验证它单独也要过同一准入层。"""
    originals = {name: getattr(routing, name) for name in (
        "_table_title_score", "_cross_title_score", "_title_variant_score",
        "_near_title_score")}
    original_similar = SourceIndex.similar_entries
    original_exact = SourceIndex.resolve_exact

    monkeypatch.setattr(routing, "_table_title_score", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(routing, "_cross_title_score", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(routing, "_title_variant_score", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(routing, "_near_title_score", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(SourceIndex, "similar_entries", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(SourceIndex, "resolve_exact", lambda *_args, **_kwargs: (None, []))

    if channel == "table":
        monkeypatch.setattr(routing, "_table_title_score", originals["_table_title_score"])
    elif channel == "similar":
        monkeypatch.setattr(SourceIndex, "similar_entries", original_similar)
    elif channel == "cross":
        monkeypatch.setattr(routing, "_cross_title_score", originals["_cross_title_score"])
    elif channel == "variant":
        monkeypatch.setattr(routing, "_title_variant_score",
                            originals["_title_variant_score"])
    elif channel == "near":
        monkeypatch.setattr(routing, "_near_title_score", originals["_near_title_score"])
    elif channel == "exact":
        monkeypatch.setattr(SourceIndex, "resolve_exact", original_exact)
    else:
        raise AssertionError("unknown channel: %s" % channel)


CHANNEL_CASES = [
    ("table", "投资估算表", ("投资估算清单", 900, [], 1)),
    ("similar", "网络安全设计", ("安全设计", 900, [], 0)),
    ("cross", "建设目标", ("项目建设目标与建设内容", 100,
                           [("建设目标", 900, [], 0)], 0)),
    ("variant", "建设方案编制", ("建设方案", 900, [], 0)),
    ("near", "项目建设期", ("项目建设周期", 900, [], 0)),
    ("exact", "建设目标", ("建设目标", 900, [], 0)),
]


@pytest.mark.parametrize("target,candidate", SYNONYM_PAIRS)
def test_synonym_positive_matrix(target, candidate):
    effective, _head_ok, synonym = candidate_similarity(target, candidate)
    assert synonym is True
    assert synonym_related(target, candidate)

    index = _index_of([(candidate, 900, [], 0)])
    pool = _close(index, target)
    assert candidate in _titles(pool), (target, candidate, effective, _titles(pool))
    item = next(item for item in pool if item["entry"]["title"] == candidate)
    assert item["synonym"] is True, "同义词进入候选池后又被前缀兼容性过滤"


@pytest.mark.parametrize("target,candidate", PREFIX_PAIRS)
def test_prefix_false_positive_matrix(target, candidate):
    _effective, _head_ok, synonym = candidate_similarity(target, candidate)
    assert synonym is False
    index = _index_of([(candidate, 900, [], 0)])
    assert candidate not in _titles(_close(index, target))


def test_exact_out_of_scope_subtree_cannot_reenter_semantic_migrate():
    """异章“建设目标”被 exact_out_of_scope 降级后，任何语义通道都不得绕回。"""
    index = _index_of([
        ("项目建设目标与建设内容", 100, [("建设目标", 900, [], 0)], 0),
        ("运行维护系统设计方案", 100, [("运行维护内容", 900, [], 0)], 0),
    ])
    arbitration = {
        "scope": {"tpl": "chapter_02"},
        "demoted": {"tpl": {"source": "chapter_01_01", "source_title": "建设目标",
                            "reason": "exact_out_of_scope", "scope": "chapter_02"}},
    }
    pool = _semantic_candidates(index, _target("建设目标"), [], top_k=8,
                                min_candidate_chars=120, arbitration=arbitration,
                                scope_key="chapter_02")
    titles = _titles(pool)
    assert "项目建设目标与建设内容" not in titles
    assert "建设目标" not in titles
    assert not any(item["entry"]["key"].startswith("chapter_01") for item in pool)

    decision = route_node(index, None, _target("建设目标"), arbitration=arbitration,
                          paragraphs=[], materials=[])
    assert decision["mode"] == "grounded_write"
    assert (decision.get("matched_source") or {}).get("key") not in {
        "chapter_01", "chapter_01_01"}


def test_paragraph_reuse_is_not_globally_blocked_by_node_level_scope():
    """节点级 exact_out_of_scope 禁止不得扩散成全局正文禁止。"""
    record = {
        "key": "chapter_01_01", "number": "1.1", "title": "建设目标",
        "path_titles": ["项目建设目标与建设内容", "建设目标"], "order": 5,
        "text": "建设目标：建成统一、协同、智能的业务体系。",
        "chars": 24, "sha256": "test",
    }
    picked = search_paragraphs([record], _target("建设目标"), ["建设目标"], top_k=8)
    assert [item["record"]["key"] for item in picked] == ["chapter_01_01"]


def test_candidate_allowed_enforces_source_scope_and_anchor_ownership():
    guard = getattr(routing, "candidate_allowed", None)
    assert callable(guard), "P1-1 需要统一的 candidate_allowed 准入层"
    entry = {"key": "chapter_01", "path_keys": ["chapter_01"]}
    assert guard(entry, reserved=set(), scope_key=None) is True
    assert guard(entry, reserved={"chapter_01"}, scope_key=None) is False
    assert guard(entry, reserved=set(), scope_key="chapter_02") is False
    assert guard(entry, reserved=set(), scope_key=None,
                 pinned_sources={"chapter_01"}) is False


def test_scope_material_candidate_is_a_special_channel_even_when_reserved():
    """素材范围节点是写作素材通道，不能被 reserved 或普通 in_scope 误杀。"""
    index = _index_of([("运行维护系统设计", 200, [], 0)])
    arbitration = _demoted("chapter_01", "exact_out_of_scope")
    pool = _semantic_candidates(index, _target("建设目标"), [], top_k=8,
                                min_candidate_chars=120, arbitration=arbitration,
                                scope_key="chapter_01")
    items = [item for item in pool if item.get("scope_candidate")]
    assert [item["entry"]["key"] for item in items] == ["chapter_01"]


@pytest.mark.parametrize("channel,target,candidate_spec", CHANNEL_CASES)
def test_every_semantic_channel_passes_admission_guard(monkeypatch, channel, target,
                                                       candidate_spec):
    candidate = candidate_spec[0]
    _isolate_channel(monkeypatch, channel)
    index = _index_of([candidate_spec, ("范围章", 900, [], 0)])
    titles = _titles(_close(index, target))
    assert candidate in titles, "隔离通道未召回控制候选: %s" % channel

    reserved_titles = _titles(_close(index, target, arbitration=_demoted("chapter_01")))
    assert candidate not in reserved_titles, "reserved/source ownership 未生效: %s" % channel

    scoped_titles = _titles(_close(index, target, scope_key="chapter_02"))
    assert candidate not in scoped_titles, "scope 准入未生效: %s" % channel
