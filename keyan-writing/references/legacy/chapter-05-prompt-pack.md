# 第五章写作提示词包

本文件提供可直接复制使用的提示词，把第五章从"写概述"推进到"写功能点"。配合
`check-depth` / `check-features` / `self-check` 三个确定性命令使用，形成
**清单先行 → 逐项销号 → 脚本验收 → 缺口回填** 的闭环。

核心原则：**先建清单，再写作；不建清单就写，必然写成空壳。**

---

## 阶段 0：准备（一次性）

```
你是可研报告编写助手。请为第五章准备写作基线，不要写正文。

1. 阅读客户模板/权威可研，抽出第五章"系统设计方案"的 H3 领域清单。
2. 为每个领域抽出 H4 系统清单。
3. 运行确定性抽取，获取功能点主清单：
   python <SKILL>/scripts/cli.py extract-features --project-root <ROOT> --features-path work/features.json
   python <SKILL>/scripts/cli.py check-features  --project-root <ROOT>
4. 把领域→系统→功能点整理为 `work/chapter_05_inventory.md` 表格：
   | 领域 | 系统 | 模块 | 子模块 | 功能点 | 功能描述 | 证据来源 |
5. 输出：领域数、系统数、功能点数、每个领域的功能点数小计。
```

验收：`work/chapter_05_inventory.md` 的领域数、系统数、功能点数与
`work/features.json` 一致；不一致要说明原因（不是静默合并）。

---

## 阶段 1：按领域逐系统写作（主提示词）

一次只写一个系统，不要合并、不要跨系统。把 `{{变量}}` 替换为实际值。

```
你是可研报告编写助手。请撰写第五章"系统设计方案"中 {{领域}} 领域的 {{系统名称}}。

【已建清单】work/chapter_05_inventory.md 中 {{领域}} → {{系统名称}} 的功能点共 {{N}} 个，
必须逐条写入，不得合并、不得省略、不得用"等""若干"代替。

【证据】在 normalized/ 中查阅 {{证据文件}}（系统建设方案/需求清单/预算清单）。
系统名称、模块、功能点、接口、性能指标必须来自证据；无法确认的写
`GAP: <一句话待确认事项>`，不得编造。

【输出结构】（H4 起，逐级向下）
#### {{系统名称}}
##### 总体架构
系统在整体架构中的定位、与上下游系统的关系。
##### 功能架构
按模块列出（通常 5~10 个模块），用表格：| 模块 | 子模块 | 主要功能 |
##### 业务流程
核心流程的步骤（有序列表），写清角色、动作、系统动作、结果。
##### 数据架构
数据来源、流向、存储、共享；涉及的数据表/数据集名称来自证据。
##### 系统功能设计
###### {{模块A}}
####### {{子模块A1}}
######## {{功能点A1-a}}：<功能描述：输入、处理、输出>
######## {{功能点A1-b}}：<功能描述>
####### {{子模块A2}}
######## {{功能点A2-a}}：<功能描述>
###### {{模块B}}
……（把所有功能点写完为止）

【硬性要求】
- 每个功能点是一行 H8/H9 标题 + 其后一段功能描述（1~3 句，写清输入/处理/输出），
  正文不得少于 20 字；只有标题没有描述视为未达标。
- 每个模块至少 1 个子模块；每个子模块至少 1 个功能点。
- 不写手工章节编号之外的编号；金额单位"万元"，占比两位小数。
- 规划系统不得写成已建成。
- 完成后自报：本系统写了 {{m}} 个模块、{{k}} 个功能点。
```

### 每个领域的角度提示（可选，按需附加）

- **健康大脑/数据中枢**：数据集成、数据开发、数据标准化、数据治理、数据服务与共享、
  数据分析与可视化、数据资源目录、数据要素流通。
- **标准体系**：数据标准、技术标准、管理标准、业务规范、信息安全防护。
- **提服务**：统一入口/身份认证、便民服务应用、互联网医院、电子健康卡、影像云、
  延续性护理、健康画像。
- **重整合**：整合型医生工作站、医疗技术管理、基本公共卫生监管、单病种移动医生端、
  移动居民端。
- **强机构（科研）**：科研数据服务、专病库、队列研究、科研项目管理、分析挖掘工具。
- **兴产业**：数据资产服务平台、商保结算、数据要素流通。
- **促协同**：疾病监测、质控中心、区域远程医疗（远程诊断/会诊/双向转诊）、病原检测。
- **辅治理**：绩效考核、等级评审、临床重点专科、信用、统计与决策、药品监管、廉洁医采、
  规划与项目管理、健康考核。
- **安全一体化平台**：等保定级、安全等保体系、安全评估、密码保障、系统测试、信创适配。

---

## 阶段 2：写完后的自检（确定性，不依赖模型）

写完一章就立刻自检，不要等全文写完：

```bash
# 深度契约：字数、标题、功能点、表格行、领域、空壳叶子
python <SKILL>/scripts/cli.py check-depth --project-root <ROOT> --outline-path outline.json

# 功能点覆盖：清单里哪些功能点还没写进正文
python <SKILL>/scripts/cli.py check-features --project-root <ROOT> --features-path work/features.json

# 事实基线：与基线口径冲突的数字
python <SKILL>/scripts/cli.py check-baseline --project-root <ROOT> --outline-path outline.json

# 汇总补写清单（推荐）：契约缺口 + 空标题 + 功能点缺口 + 基线冲突 + GAP
python <SKILL>/scripts/cli.py self-check --project-root <ROOT> --outline-path outline.json
```

`self-check` 输出 `next_actions`（按优先级排序的补写清单）与 `summary`。
只看 `next_actions` 就能知道"还差什么、差多少"。

### 自检后的人工确认项（务必回答）

1. `contract_floor` 是否 partial？若调低过契约，是否有正当理由？无理由就恢复基线。
2. `depth.diagnostics` 里是否有 `depth_leaf_body`（有标题无描述的叶子）？逐个补功能描述。
3. 是否有 `empty_section` / `empty_item` / `empty_heading`？**每个必需小节都必须有正文或
   `GAP:` 说明，不能留空标题**——这是最容易漏、也最显眼的缺陷。
4. `features.missing_*` 是否覆盖所有功能点？未覆盖的要么补写，要么标 GAP 说明。
5. 各领域 `function_points` 分布是否均衡？某个领域明显偏少通常是漏写。
6. `baseline.diagnostics` 是否为空？冲突要么改正文、要么把合理并列值写进 `allowed`。
7. `gaps` 数量是否合理？GAP 应"逐条可查"，而不是把大段内容一句 GAP 带过。

---

## 阶段 3：缺口回填提示词

把 `self-check` 的 `next_actions` 贴进去，逐条销号：

```
以下是 self-check 给出的第五章补写清单（按优先级）：
{{粘贴 next_actions}}

请逐条完成，不要跳项、不要合并：
1. 对每个 feature_coverage 项：打开 work/features.json，找到对应 source_id 的缺失功能点，
   补写到第五章对应系统下（H6~H9），并写功能描述。
2. 对每个 expand_body / more_function_points 项：扩写到契约数字以上。
3. 对每个 thin_leaves 项：给不足 20 字的功能点补"输入、处理、输出"描述。
4. 对每个 empty_section / empty_item / empty_heading 项：补正文；若确无资料，
   写成 `GAP: <一句话待确认事项>` 单独一行，**不得留空标题**。
5. 对每个 fact_baseline_conflict 项：核对证据后改正文；确属口径差异的写进基线 allowed。
6. 对每个 contract_below_floor 项：恢复契约或说明下调理由。
7. 完成后重新运行 check-depth、check-features、check-baseline、self-check，直到 status 为 valid。

每完成一项，报告：项类型、所在章节/系统、补充数量。不要输出正文全文。
```

---

## 判定标准（何时算第五章完成）

| 检查 | 达标 |
|---|---|
| `check-depth` | status = valid，且无 `depth_leaf_body`、无 `empty_section`/`empty_item` |
| `check-features` | coverage ≥ 0.95（其余标 GAP） |
| `check-baseline` | status = valid（冲突已改或已列入 allowed） |
| `self-check` | status = valid，`next_actions` 为空或仅剩 GAP 类 |
| 领域覆盖 | 与客户模板一致（含标准体系、安全一体化） |
| 功能点分布 | 每个领域都有功能点，无空白领域 |

未达标就不要登记为 current。宁可显式标注进度，也不要让空壳章通过。
