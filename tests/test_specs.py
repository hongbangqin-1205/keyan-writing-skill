"""章节规范解析测试：references/chapter-writing 的规范能被结构化。"""
import pytest
from keyan.specs import Specs, analyze_spec, coverage, spec_payload

SKILL_ROOT = __import__("conftest").SKILL_ROOT


def test_specs_index_all_chapters():
    specs = Specs(SKILL_ROOT)
    assert specs.chapter_numbers() == list(range(1, 12))
    assert len(specs.chapter(5)["sections"]) == 13
    assert specs.chapter(5)["sections"][5]["title"] == "系统设计方案"


def test_spec_for_section_node_matches_file():
    specs = Specs(SKILL_ROOT)
    node = {"number": "5.13", "title": "运行维护系统设计方案",
            "norm_title": "运行维护系统设计方案", "path_titles": ["项目建设方案", "运行维护系统设计方案"]}
    spec = specs.spec_for_node(node)
    assert spec["kind"] == "section"
    assert spec["title"] == "运行维护系统设计方案"
    assert spec["path"].name == "13-运行维护系统设计方案.md"
    items = [item["text"] for item in spec["requirements"]["required_items"]]
    assert any("运维费用估算" in item for item in items)


def test_spec_for_chapter_root_returns_overview():
    specs = Specs(SKILL_ROOT)
    node = {"number": "5", "title": "项目建设方案", "norm_title": "项目建设方案",
            "path_titles": ["项目建设方案"]}
    spec = specs.spec_for_node(node)
    assert spec["kind"] == "chapter"
    assert spec["requirements"]["keywords"]


def test_analyze_spec_produces_clean_requirements():
    specs = Specs(SKILL_ROOT)
    text = (SKILL_ROOT / "references" / "chapter-writing" / "sections" / "chapter-01"
            / "01-项目概况.md").read_text(encoding="utf-8")
    requirements = analyze_spec(text)
    assert requirements["min_chars"] >= 600
    assert requirements["required_items"]
    names = [table["name"] for table in requirements["required_tables"]]
    assert any("绩效" in name or "建设模式" in name or "建设内容" in name for name in names)
    assert requirements["item_depth"]["建设目标"] == 500
    assert requirements["item_depth"]["建设内容"] == 800
    for keyword in requirements["keywords"]:
        assert "**" not in keyword and "\n" not in keyword
        assert 3 <= len(keyword) <= 24


def test_coverage_counts_hits_and_misses():
    result = coverage("本项目包含建设目标与建设内容", ["建设目标", "建设内容", "绩效目标"])
    assert result["score"] == pytest.approx(2 / 3, abs=1e-3)
    assert "绩效目标" in result["miss"]


def test_spec_payload_is_json_serializable():
    import json
    specs = Specs(SKILL_ROOT)
    spec = specs.spec_for_node({"number": "5.6", "title": "系统设计方案",
                                "norm_title": "系统设计方案", "path_titles": ["项目建设方案"]})
    payload = spec_payload(spec)
    json.dumps(payload, ensure_ascii=False)
    assert payload["required_items"] and payload["keywords"]