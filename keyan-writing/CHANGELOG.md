# Changelog

## 1.4.0 (2026-09-22)

- Added a single admission guard (`candidate_allowed`) shared by every semantic recall channel - table, similar, cross, variant, near and exact fallback - so reserved sources, material-scope limits and manual-anchor ownership are enforced identically on every channel (P1-1).
- Extended `exact_out_of_scope` demotion to reserve the rejected source's ancestor chain, so a subtree ruled out of scope can no longer re-enter the same target through another channel. Paragraph-level reuse inside the same source chapter stays available, and the material-scope node remains a privileged channel (P1-1).
- Let explicit synonym pairs bypass the prefix-conflict guard through `_semantic_title_ok`, so pairs such as 安全系统设计方案 ↔ 安全设计 are no longer filtered out, while prefix false positives (项目建设单位 vs 项目建设依据) stay blocked (P1-2).
- Added `tests/test_routing_hardening.py` (19 regression cases) and `tests/eval_routing_baseline.py` (45-case deterministic baseline reporting Recall@3, Top-1 route accuracy, wrong-migration rate and grounded-write fallback rate) as the baseline for a future LLM reranker A/B.
- No changes to scoring weights, thresholds, scope quorum, arbitration weights or `_accept_migration`; no LLM, embedding or reranker introduced.

## 1.3.0 (2026-09-20)

- Bundled a project-neutral Markdown outline so a new project only needs the construction-plan input.
- Made `init` and all template readers materialize the built-in outline when no external template is registered.
- Kept external template scanning as an optional override and rejected broken registered-template caches instead of silently falling back.
- Removed old-project children from dynamic sections such as policy evidence, current-state analysis, 5.6 systems, operations and appendices.

## 1.2.0 (2026-09-20)

- Added `project-tree` to derive project-specific 5.6 nodes from a confirmed source subtree without modifying the base template.
- Bound project trees, drafts and assembled chapters to source and tree fingerprints; stale output is rejected by check and publish.
- Made 5.6 depth evidence-driven instead of inheriting legacy project names, counts, or H7/H8 depth requirements.
- Standardized final Markdown and disposable-script directories as defined in `SKILL.md`.

## 1.1.0

- 新增 `anchor` 命令：保序最优分配（A＋B）自动派生模板域 ↔ 建设方案域锚点，低置信度进复核清单。
- 新增判读回填（方案 D）：按 `match/锚点判读.json` 的 accept / reject / new / ignore 回填，结果落 `match/自动锚点.json`。
- 自动锚点与人工锚点分文件存放，人工锚点永不被动；`plan` 结果分别标注 `自动锚点：` / `手工锚点：` 来路。
- 叶子节点与候选分不到线时降级为「只作素材」，不再整段迁移。
- 修复未派生自动锚点时 `plan` / `anchor` 误报 `missing json` 的问题。
- 命令清单补充 `tree`、`link`、`anchor`、`run`、`publish`、`clean`、`search`、`kb`、`verify`。

## 1.0.0

- 整理为可独立发布的可研报告编写 skill。
- 固化同名归属仲裁、近似标题、全文正文复用和补充材料检索顺序。
- 增加附表标题识别和完整表格迁移支持。
- 增加发布元信息、Agent 界面配置、示例、资源提示和评测场景。
