# -*- coding: utf-8 -*-
"""路由闸门与目标展开的单元测试（防止"标题像就迁移"和"停在纯目录容器"两类回归）。"""
import pytest

from keyan.commands import _expand_targets
from keyan.routing import _accept_migration


def _candidate(title_score, spec_score, *, synonym=False, scope_match=False):
    from keyan.routing import SCOPE_BONUS
    combined = round(0.55 * title_score + 0.45 * spec_score + (SCOPE_BONUS if scope_match else 0.0), 4)
    return {"title_score": title_score, "spec_score": spec_score, "combined": combined,
            "synonym": synonym, "scope_match": scope_match}


def test_accept_migration_requires_spec_fit():
    """标题像但正文与本节规范完全不搭 → 不迁移，转证据撰写。"""
    assert not _accept_migration(_candidate(0.75, 0.0), 0.45)      # 项目建设单位 ← 项目建设依据
    assert not _accept_migration(_candidate(0.43, 0.0), 0.45)
    # 标题相似 + 规范贴合达标 → 迁移
    assert _accept_migration(_candidate(0.75, 0.3), 0.45)
    # 素材范围命中的加分可以救回边缘候选
    assert _accept_migration(_candidate(0.6, 0.1, scope_match=True), 0.45)


def test_accept_migration_exempts_synonym_family():
    """"运行维护系统设计方案 ← 运维方案"这类同义族不受阈值约束。"""
    assert _accept_migration(_candidate(0.25, 0.0, synonym=True), 0.45)


def _tree(payload):
    from keyan.tree import tree_from_dict
    return tree_from_dict(payload)


def _node(key, number, title, own_chars, children=None):
    return {"key": key, "number": number, "title": title, "level": number.count(".") + 1,
            "own_chars": own_chars, "subtree_chars": own_chars, "children": children or [],
            "tables": 0, "images": 0, "path_titles": [title], "path_keys": [key], "parent_key": None}


def test_expand_targets_skips_pure_directory_containers_deep():
    """整章下钻：只有标题的目录节点（1 / 1.1）不生成写作目标。"""
    tree = _tree({"chapters": [_node("chapter_01", "1", "概述", 0, [
        _node("chapter_01_01", "1.1", "项目概况", 0, [
            _node("chapter_01_01_01", "1.1.1", "项目全称及简称", 52),
            _node("chapter_01_01_02", "1.1.2", "建设目标", 526),
        ]),
        _node("chapter_01_02", "1.2", "编制依据", 0, [
            _node("chapter_01_02_01", "1.2.1", "相关法律法规", 104),
        ]),
    ])]})
    assert _expand_targets(tree, ["chapter_01"], deep=True) == \
        ["chapter_01_01_01", "chapter_01_01_02", "chapter_01_02_01"]


def test_expand_targets_drills_when_all_children_are_containers():
    """auto 模式下，直接子级全是纯目录容器时继续下钻（plan --scope 1 不再停在 1.1~1.4）。"""
    tree = _tree({"chapters": [_node("chapter_01", "1", "概述", 0, [
        _node("chapter_01_01", "1.1", "项目概况", 0, [
            _node("chapter_01_01_01", "1.1.1", "项目全称及简称", 52),
        ]),
    ])]})
    assert _expand_targets(tree, ["chapter_01"]) == ["chapter_01_01_01"]


def test_expand_targets_keeps_direct_children_when_they_have_text():
    """直接子级有正文时保持"逐层推进"语义不变（如 5.13 → 5.13.1~5.13.6 的上一层）。"""
    tree = _tree({"chapters": [_node("chapter_05", "5", "项目建设方案", 0, [
        _node("chapter_05_01", "5.1", "总体架构", 242),
        _node("chapter_05_06", "5.6", "系统设计方案", 0, [
            _node("chapter_05_06_01", "5.6.1", "数智潍坊健康大脑", 0, [
                _node("chapter_05_06_01_01", "5.6.1.1", "总体架构", 334),
            ]),
        ]),
    ])]})
    assert _expand_targets(tree, ["chapter_05"]) == ["chapter_05_01", "chapter_05_06"]
    assert _expand_targets(tree, ["chapter_05_06"]) == ["chapter_05_06_01_01"]


def test_expand_targets_explicit_node_mode_is_untouched():
    tree = _tree({"chapters": [_node("chapter_01", "1", "概述", 0, [
        _node("chapter_01_01", "1.1", "项目概况", 0, [
            _node("chapter_01_01_01", "1.1.1", "项目全称及简称", 52),
        ]),
    ])]})
    assert _expand_targets(tree, ["chapter_01"], mode="node") == ["chapter_01"]
    assert _expand_targets(tree, ["chapter_01_01"], mode="node") == ["chapter_01_01"]
