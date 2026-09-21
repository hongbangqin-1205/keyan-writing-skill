# 章节方法

通用 profile 固定十章及附录标题。章节按独立 Markdown 交付，章节内部按稳定小节写作；可按任一章单独生成，不将行业标题写入通用方法。行业扩展只由 profile 显式启用。

写作前先读 `source-priority.md`（来源优先级与事实基线）与 `quality-bar.md`（体量与深度契约）；
第五章等核心章必须达到 `resources/profile/feasibility.json` 中 `depth_contract` 规定的最低
深度，并由 `check-depth` 确定性校验，未达标的章节不得登记为 current。

每章保留全部稳定小节及顺序，只写指定章节；缺资料标注待核，不补造数值。
依赖是交叉核对关系，缺依赖输出矩阵规定的信息级结果，不等待其他章完成。
完整章节生成后登记路径和哈希，再依次执行 level 1、2、3；人工修改后重新登记检查。
单章只输出未编号 H1 与其下小节，不宣称全报告一致；未完成章节不得发布。
以下 YAML 将每章标题、重点、稳定小节、依赖、边界及单章规则固定为可检查结构。

```yaml
single_chapter_rule: &single
  allowed: true
  require_all_chapters: false
  complete_sections: true
  register_then_check: true
  full_report_consistency: false
chapters:
  chapter_01:
    title: 概述
    focus: [范围, 目标, 结论]
    stable_sections: [项目概况, 编制依据, 主要结论]
    dependencies: []
    boundary: 汇总项目主体、规模、目标和已有结论；未形成的结论标待核，不替代后续论证。
    single_chapter: *single
  chapter_02:
    title: 项目建设背景和必要性
    focus: [政策, 问题, 必要性]
    stable_sections: [建设背景, 建设必要性]
    dependencies: []
    boundary: 从有效政策和现状问题推导必要性；不将政策支持等同审批通过，不展开技术设计。
    single_chapter: *single
  chapter_03:
    title: 项目需求分析与产出方案
    focus: [需求, 产出, 指标]
    stable_sections: [需求分析, 产出方案]
    dependencies: [chapter_05, chapter_09]
    boundary: 明确需求依据、服务对象与可验收产出指标；不以拟建功能倒推已证实需求。
    single_chapter: *single
  chapter_04:
    title: 项目选址与要素保障
    focus: [选址, 土地, 资源]
    stable_sections: [项目选址, 要素保障]
    dependencies: [chapter_05, chapter_07, chapter_09]
    boundary: 核对选址方案及土地资源保障条件；未取得的手续列为条件，不虚构批复。
    single_chapter: *single
  chapter_05:
    title: 项目建设方案
    focus: [目标, 内容, 技术]
    stable_sections: [建设目标, 建设内容, 技术方案]
    dependencies: [chapter_03, chapter_06, chapter_07]
    boundary: 将需求映射到建设内容与技术路径；运营和预算仅引用对应章节口径，不重复替代其测算。
    depth_contract: {required: true, gate: check-depth, note: 系统设计方案必须写到功能点级（H6~H9），详见 quality-bar.md}
    single_chapter: *single
  chapter_06:
    title: 项目运营方案
    focus: [模式, 组织, 运维]
    stable_sections: [运营模式, 运维保障]
    dependencies: [chapter_05, chapter_07]
    boundary: 明确运营主体、职责、资源和维护机制；区分建设期与运营期费用，不凭空承诺服务能力。
    single_chapter: *single
  chapter_07:
    title: 项目投融资与财务方案
    focus: [投资, 融资, 财务]
    stable_sections: [投资估算, 融资方案, 财务分析]
    dependencies: [chapter_05, chapter_10]
    boundary: 给出投资边界、资金来源、计算依据及假设；不将融资意向写成资金已落实。
    single_chapter: *single
  chapter_08:
    title: 项目影响效果分析
    focus: [效益, 指标]
    stable_sections: [经济社会效益, 效果指标]
    dependencies: [chapter_10]
    boundary: 区分定性影响和有基线可计算效益，明确评价口径；不得将社会效益直接计入财务收入。
    single_chapter: *single
  chapter_09:
    title: 项目风险管控方案
    focus: [风险, 措施, 责任]
    stable_sections: [风险识别, 风险应对]
    dependencies: [chapter_05, chapter_10]
    boundary: 建立风险、触发条件、措施及责任映射；披露剩余风险，不因已有措施声称风险消失。
    single_chapter: *single
  chapter_10:
    title: 研究结论及建议
    focus: [结论, 建议, 条件]
    stable_sections: [研究结论, 实施建议]
    dependencies: [chapter_01, chapter_02, chapter_03, chapter_04, chapter_05, chapter_06, chapter_07, chapter_08, chapter_09]
    boundary: 仅依据已登记章节给出带条件结论和实施建议；列明缺章及未决事项，不引入新事实或宣称全报告通过。
    single_chapter: *single
  appendix:
    title: 附表、附图和附件
    focus: [证据附件]
    stable_sections: [附表, 附图, 附件]
    dependencies: []
    boundary: 仅收录可追溯来源的表图与附件，标注正文关联；不编造证明文件或在附件新增实质结论。
    single_chapter: *single
```
