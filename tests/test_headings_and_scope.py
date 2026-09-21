"""标题归一化、候选相似度、scope 解析的单元测试。"""
from keyan.headings import (candidate_accepted, candidate_similarity, cn_to_int, is_generic_head,
                            looks_like_heading, normalize_title, similarity,
                            strip_category_suffix, synonym_related)
from keyan.scope import parse_scope


def test_normalize_title_strips_numbering_and_punctuation():
    assert normalize_title("第五章 项目建设方案") == "项目建设方案"
    assert normalize_title("5.6 系统设计方案（H2）108") == "系统设计方案"
    assert normalize_title("（三）存在问题及分析") == "存在问题及分析"
    assert normalize_title("1.2.3 建设内容与规模") == "建设内容与规模"
    assert normalize_title("**总体架构**") == "总体架构"


def test_cn_to_int():
    assert cn_to_int("十五") == 15
    assert cn_to_int("二十三") == 23
    assert cn_to_int("7") == 7


def test_looks_like_heading():
    assert looks_like_heading("1.2.3 建设内容")
    assert looks_like_heading("第三节 建设方案")
    assert not looks_like_heading("本项目主要建设内容如下。")
    assert not looks_like_heading("")


def test_same_title_scores_one():
    assert similarity("总体架构", "总体架构") == 1.0
    assert similarity("系统设计方案", "安全系统设计方案") >= 0.6


def test_synonym_related_pairs():
    assert synonym_related("网络拓扑", "网络架构")
    assert synonym_related("总体架构", "总体设计")
    assert not synonym_related("总体架构", "数据架构")


def test_category_suffix_stripping():
    assert strip_category_suffix("运行维护系统设计方案") == "运行维护"
    assert strip_category_suffix("安全系统设计方案") == "安全"
    assert strip_category_suffix("总体架构") == "总体"


def test_candidate_similarity_accepts_synonym_and_head_match():
    score, head_ok, synonym = candidate_similarity("网络拓扑", "网络架构")
    assert synonym and candidate_accepted(score, head_ok, synonym)
    score, head_ok, synonym = candidate_similarity("安全体系设计", "安全系统设计方案")
    assert head_ok and candidate_accepted(score, head_ok, synonym)


def test_candidate_similarity_rejects_suffix_only_match():
    """两个不同系统都以"系统设计方案"结尾时不得互相迁移。"""
    score, head_ok, synonym = candidate_similarity("运行维护系统设计方案", "安全系统设计方案")
    assert not candidate_accepted(score, head_ok, synonym)
    score, head_ok, synonym = candidate_similarity("系统设计方案", "安全系统设计方案")
    assert not candidate_accepted(score, head_ok, synonym)


def test_candidate_similarity_rejects_generic_head_collapse():
    """"建设任务/建设目标/建设地点"剥掉后缀后都只剩通用词头"建设"，不得互相迁移。"""
    for title in ("建设任务", "建设地点", "建设规模", "建设工期", "建设模式"):
        score, head_ok, synonym = candidate_similarity(title, "建设目标")
        assert not candidate_accepted(score, head_ok, synonym), title
    score, head_ok, synonym = candidate_similarity("项目概况", "项目管理")
    assert not candidate_accepted(score, head_ok, synonym)


def test_candidate_similarity_rejects_short_head_contained_in_long_title():
    """短词头被长标题整段包含不算匹配："安全" ⊂ "潍坊市网络安全现状"。"""
    score, head_ok, synonym = candidate_similarity("安全系统设计方案", "潍坊市网络安全现状")
    assert not candidate_accepted(score, head_ok, synonym)


def test_candidate_similarity_still_accepts_domain_head_match():
    """词头长度相当、且非通用词时仍按词头匹配（"安全体系设计" ≈ "安全系统设计方案"）。"""
    score, head_ok, synonym = candidate_similarity("安全体系设计", "安全系统设计方案")
    assert head_ok and candidate_accepted(score, head_ok, synonym)
    score, head_ok, synonym = candidate_similarity("备份系统设计方案", "备份系统设计")
    assert head_ok and candidate_accepted(score, head_ok, synonym)


def test_generic_head_detection():
    assert is_generic_head("建设") and is_generic_head("项目") and is_generic_head("系统")
    assert not is_generic_head("安全") and not is_generic_head("运行维护")


def test_parse_scope_forms(template_tree):
    assert parse_scope("5", template_tree)["keys"] == ["chapter_05"]
    assert parse_scope("5.2", template_tree)["keys"] == ["chapter_05_02"]
    assert parse_scope("第五章第二节", template_tree)["keys"] == ["chapter_05_02"]
    assert parse_scope("chapter_05_02", template_tree)["keys"] == ["chapter_05_02"]
    assert parse_scope("all", template_tree)["keys"][0] == "chapter_01"
    assert parse_scope("99", template_tree)["unresolved"] == ["99"]
    # 小节不存在时退让到所属章，便于用户用漂移的编号下指令
    assert parse_scope("5.9", template_tree)["keys"] == ["chapter_05"]


def test_parse_scope_chinese_chapter(template_tree):
    scope = parse_scope("第五章", template_tree)
    assert scope["keys"] == ["chapter_05"]
    assert scope["label"] == "5"