# 质量基准与深度契约

本文件给出可研报告的"体量与深度"验收基准，供写作前定目标、写作后自查。基准来自
正式可研模板与项目示例逐章实测（`【可研】word模板+项目示例.docx`，11 章、约 83 万字
正文 + 约 63 万字符表格、3600 个标题，其中第五章占正文 92.6%）。

## 一、章节体量分布（实测参考）

| 章节 | 正文占比 | 标题数级 | 深度 |
|---|---|---|---|
| 第五章 项目建设方案 | ~92.6% | 3315（第五章） | H9 |
| 概述（项目概况等） | ~2.3% | ~49 | H5 |
| 项目需求分析与产出方案 | ~1.9% | ~26 | H4 |
| 其余各章 | 各 <1.5% | 5~41 | H5 |

结论：**报告质量几乎完全取决于第五章是否写到功能点级**。只补齐其他章节、第五章仍是
概括段落，达标率约 25%；第五章做到功能点级（800~1200+ 功能点叶子），达标率可到 80%。

## 二、深度契约（profile `depth_contract`）

`resources/profile/feasibility.json` 的 `depth_contract` 定义每章最低值，字段含义：

| 字段 | 含义 |
|---|---|
| `min_chars` | 正文字符数下限（含表格文本） |
| `min_headings` | 标题数下限 |
| `min_function_points` | 功能点叶子数下限（默认 H6 及更深） |
| `min_table_rows` | 表格数据行数下限 |
| `min_domains` | H3 领域数下限（`domain_parent` 下的 H3） |
| `domains` | 必含领域名称清单（项目级覆盖） |
| `min_systems_per_domain` | 每个领域最少系统（H4）数 |
| `min_function_points_per_domain` | 每个领域最少功能点数 |
| `min_leaf_chars` | 功能点正文的最短长度（低于即空壳叶子） |
| `max_thin_leaves` | 允许的空壳叶子数，默认 0 |
| `min_section_chars` | 必需小节/子项正文的最短长度（低于即空标题，默认 10） |
| `function_point_level` | 计为功能点的最小标题级别，默认 6 |
| `domain_parent` | 领域父标题（H2），默认"系统设计方案" |

**门禁默认常开**：`assemble` 与 `check-depth` 始终以 profile 基线为准，不需要项目自己声明
`depth_contract`。`outline.depth_contract` 只应上调、不应下调（下调会被 `self-check` 报为
`depth_contract_below_floor`）。确需使用不同标准时，必须在 outline 显式写
`depth_enforcement: false`，`self-check` 会把 `enforcement` 记为 `disabled` 以示可见，
不允许静默绕过。低于契约返回 `partial`（退出码 2），不得登记为 current。

## 二之二、空标题检查

总量达标不代表写完整：一份报告可以字数和标题数都超标，却在 `### 项目总投资估算` 这类
必需小节下留空。`check-depth` 与 `assemble` 因此同时做**逐标题**检查：

| 代码 | 含义 |
|---|---|
| `missing_section` | 必需小节缺失（outline 的 `chapters[].sections`） |
| `empty_section` | 必需小节存在但正文短于 `min_section_chars` |
| `missing_item` | 模板子项缺失（profile `recommended_items` 或 `chapters[].required_items`） |
| `empty_item` | 模板子项存在但正文过短 |
| `empty_heading` | 任意 H3 及更深的标题完全没有正文 |

匹配按标题文本、跨层级进行，因此子项写成 H3/H4 也能被检查到；节内子标题的正文按
"子树范围"计算，不会因为第一个子标题而误判为空。

## 三、写作达标自查清单

- [ ] 第五章按"领域 → 系统 → 模块 → 子模块 → 功能点"分层，功能点逐条列出
- [ ] 每个系统都有功能架构、业务流程、数据架构、系统功能设计（可加总体架构）
- [ ] 每个领域至少 1 个系统，领域清单与客户模板/权威可研一致
- [ ] 功能点数量与证据（预算清单、功能清单）对应，未合并省略
- [ ] 各章标题数、字数、表格数达到 `depth_contract`
- [ ] 附表按领域出表，与第七章投资口径一致
- [ ] 附图、附件已登记，缺失项标 GAP
- [ ] 全文金额、数量、政策文号可追溯到证据，冲突口径单列并标 GAP

## 四、check-depth 用法

```bash
python "<SKILL_ROOT>\scripts\cli.py" check-depth \
  --project-root "<PROJECT_ROOT>" --outline-path outline.json \
  chapters/chapter_05/chapter_05.md
```

输出单行 JSON，含 `status`、每章 `measurements`（字数/标题/功能点/表格/领域/空壳叶子）与
`diagnostics`。不传章节路径时读取 `chapters/**/*.md`。

## 四之二、self-check（写完后的自检，推荐）

```bash
python "<SKILL_ROOT>\scripts\cli.py" self-check \
  --project-root "<PROJECT_ROOT>" --outline-path outline.json \
  --features-path work/features.json
```

一次汇总五类缺口，输出按优先级排序的 `next_actions`：

| 优先级 | kind | 含义 |
|---|---|---|
| P0 | `contract_below_floor` / `fact_baseline_conflict` | 契约被下调、与事实基线数字冲突 |
| P1 | `expand_body` / `more_function_points` / `feature_coverage` / `missing_section` / `empty_section` | 正文功能点不足、必需小节缺失或为空 |
| P2 | `more_sections` / `missing_domain` / `more_systems` / `domain_function_points` / `thin_leaves` / `empty_item` | 结构、空壳叶子、模板子项为空 |
| P3 | `more_tables` / `gaps` / `missing_item` / `empty_heading` | 表格不足、GAP 待确认、模板子项缺失 |

`summary` 含 `chapters_with_deficits`、`actions`、`empty_sections`、`empty_items`、
`baseline_conflicts`、`feature_coverage`、`gaps`；`enforcement` 显示门禁状态
（`profile_baseline` 或 `disabled`）。这是"写完自检"的确定性依据，不依赖模型判断。

## 四之三、事实基线（`fact_baseline`）

同一项目常有多个资料口径，写初稿时先定基线、全文按同一口径落地。在 `outline.json`
里登记 `fact_baseline`，`check-baseline`（或 `self-check`）会点出与基线冲突的表述：

```json
"fact_baseline": [
  {"name": "科研平台总存储量", "match": ["科研数智实验室", "科研平台"],
   "value": "38TB", "allowed": ["3TB", "20TB"], "source": "SRC-224"},
  {"name": "项目总投资", "value": "13821.975万元", "source": "第七章"}
]
```

字段说明：

| 字段 | 含义 |
|---|---|
| `name` | 基线项名称，用于诊断信息与默认匹配 |
| `value` | 权威值（含单位，如 `38TB`、`13821.975万元`） |
| `match` | 用于定位"讲的是这件事"的标题/段落关键词；省略时用 `name` 与 `aliases` |
| `aliases` | 允许在正文中出现的同义名称 |
| `allowed` | 同一主题下允许并列的其他数值（如年增量、原始数据量） |
| `source` | 该口径的证据来源 |

匹配规则：先找标题中含 `match` 关键词的小节，检查其子树正文；没有匹配标题时只检查
真正提到该主题的段落。只比较**与基线同单位**的数字，`T/G/P/M` 会自动归一为 `TB/GB/PB/MB`。
同一小节内只要出现基线值即视为一致；全部不符才报 `fact_baseline_conflict`。

该检查是**读取与提示**，不修改正文；确属口径差异的（如"原始数据 60T × 5 倍冗余 = 320T"）
写进 `allowed`，不写就说明存在需要人工裁定的口径冲突。

## 四之四、第五章写作提示词

`references/chapter-05-prompt-pack.md` 提供四个可直接复制的提示词：清单准备、逐系统写作、
写后自检、缺口回填，并给出各领域的角度提示与"何时算完成"的判定标准。推荐流程：
**先建清单 → 逐系统销号 → `self-check` → 按 `next_actions` 回填 → 复检至 valid**。

## 五、features 清单用法（功能点级证据）

预算与子系统方案里的功能行是可确定解析的。先抽取清单，再核对覆盖：

```bash
python "<SKILL_ROOT>\scripts\cli.py" extract-features \
  --project-root "<PROJECT_ROOT>" --features-path work/features.json
python "<SKILL_ROOT>\scripts\cli.py" check-features \
  --project-root "<PROJECT_ROOT>" --features-path work/features.json
```

`check-features` 输出 `total`、`covered`、`missing` 与覆盖率；缺失的功能点必须补写
到第五章对应系统下，或标 GAP 说明原因。
