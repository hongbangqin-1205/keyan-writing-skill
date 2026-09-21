# 上下文检查矩阵

键是被检查章节，值是其依赖章节（chapter → dependencies）；不是生成顺序。
Level 1 检查结构和引用，Level 2 检查事实账本和大纲，Level 3 只比较已登记依赖。
新登记或更新依赖时反向检查已登记的依赖方；缺章不阻断单章，不代表全报告通过。
事实确认与大纲确认分别执行独立动作，不能互相代替。

```yaml
levels:
  1: {scope: single_chapter, checks: [structure, citations, facts]}
  2: {scope: single_chapter, checks: [fact_ledger, outline_alignment]}
  3: {scope: registered_dependencies, checks: [cross_chapter_consistency, numbers, terminology]}
direction: chapter_to_dependencies
dependencies:
  chapter_01: []
  chapter_02: []
  chapter_03: [chapter_05, chapter_09]
  chapter_04: [chapter_05, chapter_07, chapter_09]
  chapter_05: [chapter_03, chapter_06, chapter_07]
  chapter_06: [chapter_05, chapter_07]
  chapter_07: [chapter_05, chapter_10]
  chapter_08: [chapter_10]
  chapter_09: [chapter_05, chapter_10]
  chapter_10: [chapter_01, chapter_02, chapter_03, chapter_04, chapter_05, chapter_06, chapter_07, chapter_08, chapter_09]
reverse_trigger: {events: [registered, changed], targets: registered_dependents, level: 3}
missing_dependency: {code: dependency_chapter_missing, severity: info, block: false, claim: {full_report_consistency: false}}
confirmation:
  facts: {action: confirm_facts, field: fact_confirmed, requires: [fact_id, source_ids, confirmed_by], sets: {fact_confirmed: true}, does_not_set: [outline_confirmed]}
  outline: {action: confirm_outline, field: outline_confirmed, requires: [outline_id, scope, target_node_ids, confirmed_by], sets: {outline_confirmed: true}, does_not_set: [fact_confirmed]}
```
