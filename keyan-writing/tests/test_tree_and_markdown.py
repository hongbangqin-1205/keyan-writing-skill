"""目录树与 Markdown 转换的单元测试。"""
from keyan.docx_blocks import read_document
from keyan.markdown import blocks_to_markdown
from keyan.tree import (build_tree, iter_nodes, node_by_key, node_by_number, render_leaf_index_markdown,
                        render_tree_markdown, subtree_text, tree_from_dict, tree_to_dict)


def test_read_document_extracts_headings_tables_and_stats(documents):
    doc = read_document(str(documents["plan"]))
    kinds = [block["kind"] for block in doc["blocks"]]
    assert kinds.count("heading") == 9
    assert kinds.count("table") == 1
    assert doc["stats"]["tables"] == 1
    assert doc["stats"]["headings"] == 9


def test_build_tree_numbers_and_leaf_stats(documents):
    doc = read_document(str(documents["plan"]))
    tree = build_tree(doc)
    assert [chapter["title"] for chapter in tree["chapters"]] == ["项目概况和项目单位", "项目建设方案",
                                                                 "投资估算和资金来源"]
    assert tree["chapters"][0]["number"] == "1"
    assert tree["chapters"][0]["children"][0]["number"] == "1.1"
    assert tree["node_count"] == 9
    assert tree["leaf_count"] == 6
    assert tree["max_depth"] == 2
    total = node_by_number(tree, "2.1")
    assert total["tables"] == 1
    assert total["subtree_chars"] > 100
    assert node_by_key(tree, "chapter_02_01")["title"] == "总体架构"
    assert node_by_key(tree, "chapter_02_03")["leaf"] is True


def test_tree_roundtrip_and_rendering(documents):
    doc = read_document(str(documents["plan"]))
    tree = build_tree(doc)
    payload = tree_to_dict(tree)
    restored = tree_from_dict(payload)
    assert [node["key"] for node in iter_nodes(restored["chapters"])] == \
           [node["key"] for node in iter_nodes(tree["chapters"])]
    markdown = render_tree_markdown(tree, title="建设方案")
    assert "目录树（到最小层级）" in markdown
    assert "chapter_02_01" in markdown
    assert "1.1 项目概况" in markdown
    leaves = render_leaf_index_markdown(tree)
    assert "叶子层清单" in leaves


def test_subtree_text_covers_children(documents):
    doc = read_document(str(documents["plan"]))
    tree = build_tree(doc)
    blocks = doc["blocks"]
    parent = node_by_key(tree, "chapter_02")
    text = subtree_text(blocks, parent)
    assert "本项目总体架构分为基础设施层" in text
    assert "安全体系按照等保三级要求" in text


def test_blocks_to_markdown_rebases_headings_and_renders_tables(documents):
    doc = read_document(str(documents["plan"]))
    blocks = doc["blocks"]
    markdown = blocks_to_markdown(blocks, target_level=2)
    assert markdown.splitlines()[0].startswith("## ")
    assert "| 层次 | 主要内容 | 建设性质 |" in markdown
    assert "|---|" in markdown


def test_blocks_to_markdown_image_placeholder(documents):
    blocks = [{"kind": "heading", "level": 2, "text": "网络拓扑", "style": "Heading 2", "index": 0},
              {"kind": "image", "rid": "rId9", "text": "", "style": "", "index": 1}]
    markdown = blocks_to_markdown(blocks, asset_map={"rId9": "network.png"})
    assert "![](assets/network.png)" in markdown