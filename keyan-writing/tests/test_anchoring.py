"""自动锚点派生（保序最优分配 A＋B）与判读回填（方案 D）测试。"""
from conftest import run_cli
from keyan.anchoring import (align_children, apply_decisions, choose_mode, derive_anchors,
                             format_basis, order_preserved, pair_score, render_review)


def node(key, number, title, children=(), chars=100, tables=0, images=0, order=0):
    """构造锚点算法需要的节点（只带结构证据字段）。"""
    return {"key": key, "number": number, "title": title, "children": list(children),
            "children_count": len(children), "subtree_chars": chars, "tables": tables,
            "images": images, "doc_order": order, "path_titles": [title]}


def _pair_tree():
    """模板 5 系统设计方案 ↔ 建设方案 9 建设详细方案：含一对改名、一对同名子节点。"""
    template = node("t_root", "5", "系统设计方案", [
        node("t_01", "5.1", "重整合", [
            node("t_01_01", "5.1.1", "系统架构", chars=900, order=1),
            node("t_01_02", "5.1.2", "业务架构", chars=289, order=2)], chars=1900, order=1),
        node("t_02", "5.2", "强机构", [
            node("t_02_01", "5.2.1", "全市卫健系统科研平台", chars=1200, order=1)],
            chars=1200, order=2)])
    source = node("s_root", "9", "建设详细方案", [
        node("s_01", "9.1", "重整合", [
            node("s_01_01", "9.1.1", "功能架构", chars=138, order=1),
            node("s_01_02", "9.1.2", "业务架构", chars=294, order=2)], chars=2050, order=1),
        node("s_02", "9.2", "强机构", [
            node("s_02_01", "9.2.1", "全市卫健系统科研平台", chars=1200, order=1)],
            chars=1200, order=2)])
    return template, source


# ------------------------------------------------------------------ 打分与保序分配
def test_pair_score_gives_full_marks_to_identical_nodes():
    payload = pair_score(node("t", "1", "系统功能设计", chars=500, tables=2, images=1),
                         node("s", "1", "系统功能设计", chars=500, tables=2, images=1))
    assert payload["score"] >= 0.999
    assert format_basis(payload).startswith("标题 1.00 / 体量 1.00")


def test_align_children_is_order_preserving_and_leaves_gaps():
    template = [node("t_1", "1", "总体架构", chars=500, order=1),
                node("t_2", "2", "网络架构", chars=300, order=2),
                node("t_3", "3", "数据流程图", chars=400, order=3)]
    source = [node("s_1", "1", "总体架构", chars=500, order=1),
              node("s_2", "2", "数据流程", chars=400, order=2)]
    pairs, only_template, only_source = align_children(template, source)
    assert [(item["template"]["title"], item["source"]["title"]) for item in pairs] == [
        ("总体架构", "总体架构"), ("数据流程图", "数据流程")]
    assert [item["title"] for item in only_template] == ["网络架构"]
    assert only_source == []
    assert order_preserved(pairs)


def test_choose_mode_copies_parallel_subtrees_migrates_leaves_and_bails_on_mismatch():
    twin = [node("t_1", "1", "总体架构", chars=400, order=1),
            node("t_2", "2", "数据架构", chars=400, order=2)]
    mirror = [node("s_1", "1", "总体架构", chars=400, order=1),
              node("s_2", "2", "数据架构", chars=400, order=2)]
    pairs, _, _ = align_children(twin, mirror)
    assert choose_mode(node("t", "1", "系统功能设计", twin, chars=800), 
                       node("s", "1", "系统功能设计", mirror, chars=800), pairs) == "copy"
    assert choose_mode(node("t", "1", "系统架构", chars=900),
                       node("s", "1", "功能架构", chars=138), []) == "migrate"
    other = [node("s_1", "1", "甲", chars=100, order=1), node("s_2", "2", "乙", chars=100, order=2)]
    far = node("s", "2", "完全另类", other, chars=90000, order=2)
    pairs, _, _ = align_children([node("t_1", "1", "一", chars=100, order=1),
                                  node("t_2", "2", "二", chars=100, order=2)], other)
    assert choose_mode(node("t", "3", "数据流程图", chars=1000), far, pairs) == "write"


# ------------------------------------------------------------------ 派生
def test_derive_anchors_lands_high_mid_and_structural_gaps():
    template, source = _pair_tree()
    anchors, review, summary = derive_anchors(template, source, depth=2)
    assert anchors["t_01"]["source"] == "s_01"
    assert anchors["t_01"]["mode"] == "copy"                 # 两对子节点都对上 → 整棵直复
    assert anchors["t_01"]["tier"] == "high"
    assert anchors["t_02_01"]["source"] == "s_02_01"
    assert anchors["t_02_01"]["mode"] == "copy"
    assert len(anchors) == 5
    assert summary["order_preserved"] is True
    assert summary["anchors"] == len(anchors) == summary["high_count"] + summary["mid_count"]
    mid = [item for item in review if item["tier"] == "mid"]
    assert [item["template"]["number"] for item in mid] == ["5.1.1"]
    assert mid[0]["candidates"] and mid[0]["basis"]          # 备选与依据供判读


def test_derive_anchors_keeps_manual_anchors_intact_and_still_descends():
    template, source = _pair_tree()
    anchors, review, summary = derive_anchors(template, source, depth=2, excludes={"t_01"},
                                              origins={"t_01": "s_01"})
    assert "t_01" not in anchors                             # 人工钉住的节点不落自动锚
    assert [item["template"]["number"] for item in review
            if item["tier"] == "excluded"] == ["5.1"]
    assert anchors["t_01_02"]["source"] == "s_01_02"         # 沿人工锚点的来源继续往下派生
    assert summary["review_tiers"]["excluded"] == 1


def test_derive_anchors_reports_template_and_source_only_nodes():
    template = node("t_root", "5", "系统设计方案", [
        node("t_1", "5.1", "建设目标", chars=238, order=1),
        node("t_2", "5.2", "总体架构", chars=426, order=2)])
    source = node("s_root", "9", "建设详细方案", [
        node("s_1", "9.1", "总体架构", chars=426, order=1),
        node("s_2", "9.2", "其他系统设计", chars=5753, order=2)])
    anchors, review, summary = derive_anchors(template, source, depth=2)
    tiers = {item["tier"] for item in review}
    assert "unmatched_template" in tiers                     # 模板独有，不硬凑成一对
    assert "unmatched_source" in tiers                       # 来源独有，默认忽略
    assert anchors["t_2"]["source"] == "s_1"


# ------------------------------------------------------------------ 方案 D：判读回填
def test_apply_decisions_covers_accept_reject_new_ignore_and_diagnostics():
    template, source = _pair_tree()
    decisions = {
        "t_01_01": {"action": "accept", "source": "s_01_01", "mode": "migrate", "note": "改名"},
        "t_01_02": {"action": "reject", "note": "来源不含对应业务架构"},
        "t_02_01": {"action": "new"},
        "s_02": {"action": "ignore"},
        "t_99": {"action": "accept"},                        # 不在子树内
        "t_02": {"action": "oops"},                          # 非法 action
    }
    anchors, review, summary = apply_decisions(template, source, decisions, depth=2)
    assert anchors["t_01_01"]["tier"] == "decided"
    assert anchors["t_01_01"]["mode"] == "migrate"
    assert anchors["t_01_01"]["note"] == "改名"
    assert "t_01_02" not in anchors
    assert "t_02_01" not in anchors
    assert review == []                                      # 判读过的条目退出复核清单
    assert summary["decision_counts"] == {"accept": 1, "reject": 1, "new": 1, "ignore": 1}
    assert [item["key"] for item in summary["resolved"]] == ["s_02", "t_01_01", "t_01_02", "t_02_01"]
    diagnostics = " ".join(summary["decision_diagnostics"])
    assert "unknown_node" in diagnostics and "unknown_action" in diagnostics


def test_render_review_lists_gaps_and_candidate_slots():
    template, source = _pair_tree()
    anchors, review, summary = derive_anchors(template, source, depth=2)
    text = render_review(review, summary, decisions_path="match/锚点判读.json",
                         apply_cmd="anchor --apply")
    assert "5.1.1" in text and "备选" in text and "anchor --apply" in text
    assert "保序约束复检：通过" in text


# ------------------------------------------------------------------ 端到端：派生 → 路由 → 回放
def test_anchor_cli_derives_anchors_that_plan_consumes(workspace):
    code, payload = run_cli("anchor", "--scope", "5", "--from", "2", workspace=workspace)
    assert code in (0, 2), payload
    assert payload["summary"]["anchors"] >= 3
    assert payload["summary"]["review"] >= 1
    assert (workspace / "match" / "自动锚点.json").exists()
    assert (workspace / "reports" / "锚点复核.md").exists()
    code, plan = run_cli("plan", "--scope", "5.1", "--node", "--no-kb", workspace=workspace)
    decision = plan["decisions"][0]
    assert decision["mode"] == "exact_direct_copy"           # 总体架构 同名直复
    assert decision["anchor_auto"] is True
    assert decision["reasons"][0].startswith("自动锚点：")
    stamped = (workspace / "match" / "自动锚点.json").stat().st_mtime_ns
    code, replay = run_cli("anchor", "--review", workspace=workspace)
    assert replay["summary"]["mode"] == "review"
    assert replay["summary"]["dry_run"] is True              # 只读回放，不重算落盘
    assert replay["summary"]["anchors"] >= 3
    assert replay["results"]                                 # 复核清单原样回放
    assert (workspace / "match" / "自动锚点.json").stat().st_mtime_ns == stamped
