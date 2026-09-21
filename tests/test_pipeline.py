"""CLI 端到端测试：扫描 → 索引 → 计划 → 撰写 → 校验 → 报告。"""
import json
import subprocess
import sys
from pathlib import Path

from conftest import SKILL_ROOT, run_cli
from keyan.authoring import strip_comments
from keyan.checking import _sha256


def test_scan_outputs(workspace):
    for role, name in (("source", "建设方案"), ("template", "可研模板")):
        role_dir = workspace / role
        assert (role_dir / "目录树.md").exists()
        assert (role_dir / "目录树.json").exists()
        assert (role_dir / "blocks.json").exists()
        assert (role_dir / "assets.json").exists()
        markdown = next(role_dir.glob("*.md"))
        assert markdown.exists()
    tree = json.loads((workspace / "source" / "目录树.json").read_text(encoding="utf-8"))
    assert tree["node_count"] == 9
    assert tree["chapters"][1]["title"] == "项目建设方案"


def test_index_maps_template_to_source(workspace):
    code, payload = run_cli("index", workspace=workspace)
    assert code == 0
    assert payload["summary"]["exact"] >= 3
    assert payload["summary"]["semantic"] >= 1
    mapping = (workspace / "match" / "同名映射.md").read_text(encoding="utf-8")
    assert "chapter_05_01" in mapping
    assert "同名直复" in mapping


def test_plan_routes_each_mode(workspace):
    code, payload = run_cli("plan", "--scope", "5", "--no-kb", workspace=workspace)
    assert code == 0
    modes = {decision["key"]: decision["mode"] for decision in payload["decisions"]}
    assert modes["chapter_05_01"] == "exact_direct_copy"
    assert modes["chapter_05_02"] == "semantic_migrate"
    assert modes["chapter_05_03"] == "exact_direct_copy"
    assert modes["chapter_05_04"] == "grounded_write"
    overview = (workspace / "plan" / "5.计划总览.md").read_text(encoding="utf-8")
    assert "exact_direct_copy" in overview
    task = (workspace / "plan" / "chapter_05_04.任务单.md").read_text(encoding="utf-8")
    assert "写作任务单" in task
    assert "运维费用估算" in task          # 来自 references 的章节规范
    assert "运维费用估算" in (workspace / "plan" / "chapter_05_04.骨架.md").read_text(encoding="utf-8")


def test_author_exact_copy_is_verbatim_and_unmodified(workspace):
    code, payload = run_cli("author", "--scope", "5", "--no-kb", workspace=workspace)
    assert code == 0
    draft = (workspace / "drafts" / "chapter_05_01.md").read_text(encoding="utf-8")
    assert "## 总体架构" in draft
    assert "本项目总体架构分为基础设施层" in draft
    assert "数据中台与专题库" in draft          # 表格随子树一起复制
    sidecar = json.loads((workspace / "drafts" / "chapter_05_01.sidecar.json").read_text(encoding="utf-8"))
    assert sidecar["mode"] == "exact_direct_copy"
    assert sidecar["llm_rewrite"] is False
    assert sidecar["source"]["title"] == "总体架构"
    # 直复完整性：正文哈希与 sidecar 记录一致（可检出任何改写）
    assert _sha256(strip_comments(draft).strip()) == sidecar["integrity_sha256"]


def test_author_semantic_migration_picks_and_reports(workspace):
    run_cli("author", "--scope", "5", "--no-kb", workspace=workspace)
    draft = (workspace / "drafts" / "chapter_05_02.md").read_text(encoding="utf-8")
    assert "## 网络拓扑" in draft                    # 标题重挂为目标标题
    assert "网络架构分为政务外网区" in draft          # 正文来自语义候选
    sidecar = json.loads((workspace / "drafts" / "chapter_05_02.sidecar.json").read_text(encoding="utf-8"))
    assert sidecar["mode"] == "semantic_migrate"
    assert sidecar["source"]["title"] == "网络架构"
    report = (workspace / "drafts" / "chapter_05_02.对照.md").read_text(encoding="utf-8")
    assert "语义迁移对照报告" in report
    assert "必写要素逐项核对" in report


def test_author_grounded_write_writes_skeleton_draft(workspace):
    run_cli("author", "--scope", "5", "--no-kb", workspace=workspace)
    draft = (workspace / "drafts" / "chapter_05_04.md").read_text(encoding="utf-8")
    assert "mode=grounded_write" in draft or "grounded_write" in draft
    assert "待写" in draft
    assert (workspace / "plan" / "chapter_05_04.任务单.json").exists()


def test_author_skips_existing_draft(workspace):
    run_cli("author", "--scope", "5", "--no-kb", workspace=workspace)
    code, payload = run_cli("author", "--scope", "5", "--no-kb", workspace=workspace)
    assert code == 0
    assert {result["mode"] for result in payload["results"]} == {"skipped_existing"}


def test_assemble_produces_single_heading_per_section(workspace):
    run_cli("author", "--scope", "5", "--no-kb", workspace=workspace)
    chapter = (workspace / "chapters" / "5.md").read_text(encoding="utf-8")
    assert chapter.startswith("# 项目建设方案")
    assert chapter.count("## 总体架构") == 1
    assert chapter.count("## 网络拓扑") == 1
    assert "本项目总体架构分为基础设施层" in chapter


def test_check_reports_todo_and_spec_gaps(workspace):
    run_cli("author", "--scope", "5", "--no-kb", workspace=workspace)
    code, payload = run_cli("check", "--scope", "5", workspace=workspace)
    assert code == 2
    kinds = {item["diagnostic"].split(":")[0] for item in payload["diagnostics"]}
    assert "todo_remaining" in kinds
    assert payload["summary"]["drafted"] >= 4
    assert payload["summary"]["measurements_total"] >= 4
    assert (workspace / "reports" / "5.校验.json").exists()


def test_report_lists_progress_and_gaps(workspace):
    run_cli("author", "--scope", "5", "--no-kb", workspace=workspace)
    code, payload = run_cli("report", workspace=workspace)
    assert code == 0
    assert payload["summary"]["drafted"] >= 4
    progress = (workspace / "reports" / "编写进度.md").read_text(encoding="utf-8")
    assert "可研编写进度" in progress
    assert "chapter_05_01" in progress


def test_check_unknown_scope_is_partial(workspace):
    code, payload = run_cli("check", "--scope", "99", workspace=workspace)
    assert code == 2
    assert payload["summary"]["scope"] == "99"
    assert payload["summary"]["targets"] == 0


def test_search_local_source(workspace):
    code, payload = run_cli("search", "--query", "等保三级", workspace=workspace)
    assert code == 0
    assert payload["summary"]["hits"] >= 1
    assert any("建设方案" in hit["file"] for hit in payload["results"])


def test_verify_reports_environment():
    code, payload = run_cli("verify", workspace=Path("."))
    assert code == 0
    names = {item["name"]: item["ok"] for item in payload["results"]}
    assert names["python-docx"] and names["references"] and names["specs"]


def test_cli_subprocess_single_line_json(tmp_path):
    cli = SKILL_ROOT / "scripts" / "cli.py"
    completed = subprocess.run([sys.executable, str(cli), "verify"], capture_output=True, text=True,
                               encoding="utf-8", cwd=str(tmp_path))
    assert completed.returncode == 0
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["command"] == "verify"
    assert payload["status"] == "ok"