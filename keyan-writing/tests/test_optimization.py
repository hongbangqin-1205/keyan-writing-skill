"""优化回归：缓存不得改变路由、检索结果或断点续跑语义。"""
import json

from conftest import run_cli
from keyan import commands, kb
from keyan.localsearch import search_dir


def test_routing_cache_reuses_identical_result(workspace, monkeypatch):
    code, first = run_cli("plan", "--scope", "5", "--no-kb", workspace=workspace)
    assert code == 0
    cache = workspace / "cache" / "routing" / "arbitration.json"
    assert cache.exists()
    first_modes = [(item["key"], item["mode"]) for item in first["decisions"]]

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("valid routing cache should have been used")

    monkeypatch.setattr(commands, "build_arbitration", should_not_run)
    code, second = run_cli("plan", "--scope", "5", "--no-kb", workspace=workspace)
    assert code == 0
    assert [(item["key"], item["mode"]) for item in second["decisions"]] == first_modes


def test_persistent_kb_cache_survives_memory_reset(tmp_path, monkeypatch):
    root = tmp_path / "consulting-kb-retrieval"
    (root / "wiki").mkdir(parents=True)
    (root / "wiki" / "法规.md").write_text("等保三级要求应完整落实。", encoding="utf-8")
    (root / "datasets.json").write_text('{"datasets": {}}', encoding="utf-8")
    cache_dir = tmp_path / "cache"
    first = kb.search(root, "等保三级", cache_dir=cache_dir)
    assert first["hits"]
    kb._QUERY_CACHE.clear()

    monkeypatch.setattr(kb, "offline_wiki_search",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            AssertionError("disk cache should have been used")))
    second = kb.search(root, "等保三级", cache_dir=cache_dir)
    assert second["hits"] == first["hits"]
    assert second["cache"] == "disk"


def test_sqlite_search_index_matches_legacy_and_invalidates(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    document = source / "建设方案.md"
    document.write_text("# 安全设计\n\n系统按照等保三级要求建设。\n\n网络边界部署安全设备。\n",
                        encoding="utf-8")
    legacy = search_dir(source, "等保三级", top_k=5)
    indexed = search_dir(source, "等保三级", top_k=5, cache_dir=tmp_path / "cache")
    assert [{k: row[k] for k in ("file", "line", "text", "score", "match")} for row in indexed] == [
        {k: row[k] for k in ("file", "line", "text", "score", "match")} for row in legacy]

    document.write_text(document.read_text(encoding="utf-8") + "新增密码应用安全性评估。\n",
                        encoding="utf-8")
    refreshed = search_dir(source, "密码应用安全性评估", top_k=5,
                           cache_dir=tmp_path / "cache")
    assert refreshed and refreshed[0]["match"] == "exact"


def test_run_command_is_resumable(workspace):
    code, payload = run_cli("run", "--scope", "5", "--no-kb", workspace=workspace)
    assert code == 2
    assert payload["stages"]["plan"] == "ok"
    assert payload["stages"]["author"] == "partial"
    assert payload["stages"]["check"] == "partial"
    assert (workspace / "cache" / "routing" / "arbitration.json").exists()

    completed = workspace / "drafts" / "chapter_05_01.md"
    before = completed.read_text(encoding="utf-8")
    code, _payload = run_cli("run", "--scope", "5", "--no-kb", workspace=workspace)
    assert code == 2
    assert completed.read_text(encoding="utf-8") == before
