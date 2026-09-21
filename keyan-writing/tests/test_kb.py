"""知识库检索测试：Dify 调用失败时回退本地 wiki（不依赖网络）。"""
from keyan.kb import find_kb_root, list_libraries, offline_wiki_search, search


def _fake_kb(tmp_path):
    root = tmp_path / "consulting-kb-retrieval"
    (root / "wiki").mkdir(parents=True)
    (root / "wiki" / "01_政策法规与标准.md").write_text(
        "# 政策法规\n\n等保三级要求：信息系统安全等级保护应达到第三级。\n\n"
        "密码应用安全性评估（密评）按第三级要求执行。\n",
        encoding="utf-8")
    (root / "datasets.json").write_text('{"datasets": {"01_政策法规与标准": {"id": "x"}}}',
                                        encoding="utf-8")
    return root


def test_offline_wiki_search_returns_hits(tmp_path):
    root = _fake_kb(tmp_path)
    hits = offline_wiki_search(root, "等保三级", top_k=3)
    assert hits
    assert "等保三级" in hits[0]["content"]
    assert hits[0]["source"].endswith(".md")


def test_search_falls_back_to_wiki_without_retrieve_script(tmp_path):
    root = _fake_kb(tmp_path)
    result = search(root, "密码应用安全性评估", top_k=2)
    assert result["backend"] == "wiki-offline"
    assert result["hits"]


def test_search_without_kb_root_is_unavailable():
    result = search(None, "等保")
    assert result["status"] == "unavailable"
    assert result["hits"] == []


def test_list_libraries_reads_datasets(tmp_path):
    root = _fake_kb(tmp_path)
    assert list_libraries(root) == ["01_政策法规与标准"]


def test_find_kb_root_uses_env(tmp_path, monkeypatch):
    root = _fake_kb(tmp_path)
    (root / "scripts").mkdir()
    (root / "scripts" / "retrieve.py").write_text("print('{}')", encoding="utf-8")
    monkeypatch.setenv("KEYAN_KB_ROOT", str(root))
    assert find_kb_root() == root.resolve()