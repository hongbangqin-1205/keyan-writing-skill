---
name: keyan-writing
description: 依据可研模板目录树和章节规范，将建设方案编写成可研报告或指定章小节。优先迁移对口标题和复用正文段落，再查用户补充材料，仍不足才用知识库和网络取证撰写；保留原文、来源和显式缺口。适用于建设方案转可研、目录映射、同名直复、语义迁移与按模板套写。
metadata:
  short-description: 建设方案→可研报告章节生成
---

# 可研编写（keyan-writing）

把**建设方案**（以及调研报告、子系统方案等原料）按技能内置的**可研模板目录骨架**逐节点写成可研报告正文。
默认只上传建设方案即可；外部可研模板是替换固定骨架时的可选输入，不是必需输入。
每个节点的取材顺序固定：**对口同名直复 → 相关标题迁移 → 建设方案正文复用 → 用户其他材料 → 知识库/网络取证撰写 → 显式缺口**。

## 何时使用

- 用户给出建设方案（.docx / .md / .txt），要求产出可研报告或其中某一章、某一节；也支持用户另传模板覆盖内置骨架。
- 用户提到：目录树、同名直复、语义迁移、按模板套写、把建设方案转成可研、写第 X 章第 X 节。

## 铁律

1. **先树后文**：没有扫描出"到最小层级"的目录树之前，不写正文。
2. **同名直复零改写，但要过"归属仲裁"**：模板节点与建设方案节点标题归一化后同名、
   且该候选确实属于本节素材范围时，整棵子树原文复制，`LLM_REWRITE_COUNT = 0`
   （不润色、不总结、不同义改写、不调语序），只允许替换标题编号与层级。
   复制内容对章节规范覆盖不足时，**另起段落按规范补足**，而不是改写已复制的原文。
   泛化标题（建设目标/总体架构/系统管理…）在建设方案里常有多处或只在一处，同名未必对口——
   范围外或被更贴合小节占用的候选会降级，见下"同名归属仲裁"。
3. **语义迁移要有依据**：无同名时取语义候选，候选须同时过"标题相似"与"正文贴合章节规范"两道比选；
   迁移整段后按规范补齐缺失要素，并在 sidecar / 对照文件里记录候选、理由与比选分。
4. **不编造**：建设方案与知识库都没有的数字（金额、指标、人名、地点、日期）一律不写，
   标 `GAP` 或"待核"，不得用经验值填充。
5. **范围由用户决定**：用户说"写第五章第六节"就只处理该节点，不要顺手把整份报告写完。
6. **每章先 plan 后 author，落稿必 check**。
7. **未映射不等于无材料**：不能只交付“推荐写作小标题”。按
   `references/local-reuse.md` 继续检索标题、正文、其他上传材料；多段命中由 agent 排序、排版和补过渡，
  原文事实、数字和口径保持不变。已命中但覆盖不完整的，对剩余缺项继续取材。
8. **成品与临时脚本分开放**：成品 md 一律落到项目根的 `可研成果/`（中文名目录，用户直接翻看），
   一次性临时脚本一律写进项目根的 `临时脚本/`，收尾时把该目录整个删掉——两者都不许散落在项目根。
9. **跨项目不继承项目专名**：共用的模板原件只提供固定章、节及通用写作规范。5.6 下的领域/系统标题是
   当次项目动态节点；新建设方案必须使用独立工作区，不能带入旧项目的人工锚点、草稿或缓存。
   扫描 source/template 后先运行 `project-tree` 查看候选，核对后用 `--systems` 明确本次系统清单；
   不把旧模板中「数智潍坊健康大脑」及 9.1 等编号对应当作新项目事实。详见 `references/workflow.md`。

## 目录结构

```
keyan-writing-skill/
├─ SKILL.md                       # 核心执行文件
├─ metadata.json                  # 元信息
├─ examples/                      # 使用示例
│   ├─ example1.md
│   └─ example2.md
├─ scripts/                       # 可执行脚本
│   ├─ main.py                    # 对外入口
│   ├─ utils.py                   # 通用辅助函数
│   └─ keyan/                     # 核心实现
├─ resources/                     # 提示词和默认配置
│   ├─ prompt.md
│   └─ config.yaml
├─ tests/                         # 测试与评测
│   ├─ test_cases.md
│   └─ eval.yaml
├─ README.md                     # 使用说明
├─ CHANGELOG.md                  # 变更日志
├─ references/                    # 运行所需的详细规范与内置模板
│   ├─ workflow.md
│   ├─ chapter-writing/
│   └─ template-outline/
└─ agents/openai.yaml             # 网页端 Agent 显示配置
```

其中前十项是可上传 skill 的标准骨架；`references/` 和 `agents/` 是本技能的必要扩展目录，
不能为了追求目录简化而删除。`references/legacy/` 仅作历史存档，不参与默认写作流程。

## 工作区

一个项目一个工作区（默认 `./keyan-work`，用 `--workspace` 或环境变量 `KEYAN_WORKSPACE` 指定）：

```
<ws>/source/    建设方案：目录树.md/.json、叶子清单.md、blocks.json、assets/、<文件名>.md（全文 Markdown）
<ws>/template/  可研模板目录：默认由内置纯目录骨架生成；用户另传模板时由扫描结果覆盖
<ws>/match/     同名索引与语义候选映射
<ws>/plan/      <范围>.计划总览.md、<范围>.计划.json、<节点>.任务单.md/.json、<节点>.骨架.md
<ws>/drafts/    <节点>.md、<节点>.对照.md（规范对照）、<节点>.sidecar.json（来源+sha256+候选）
<ws>/chapters/  <范围>.md（装配稿）、<范围>.sidecar.json
<ws>/normalized/ KB-*.md（知识库命中落盘）
<ws>/reports/   编写进度.md/.json
<ws>/cache/     内容指纹路由缓存、知识库查询缓存、SQLite 本地全文索引
```

项目根（工作区的上一级）只保留输入文件、`可研成果/`、`临时脚本/` 和工作区：

- `<项目根>/可研成果/` —— **交付目录**。`assemble`/`author` 自动把装配稿发布成
  `<编号> <标题>.md`（如 `5.6.1 数智潍坊健康大脑.md`）；也可用 `publish` 重发。
- `<项目根>/临时脚本/` —— **临时脚本目录**。Agent 自己的一次性探查、校对、统计脚本都放这里，
  绝不允许直接写在项目根；任务收尾用 `clean` 把整个目录删掉。

## 运行环境

需要 python-docx。使用 Codex 运行时里的解释器（`load_workspace_dependencies` 返回的 python 路径），
例如 `C:\Users\<用户>\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`；
PATH 上的 `python` 在 Windows 上可能是应用商店占位符（运行无输出）。先自检：

```powershell
& $py "D:\可研1\keyan-writing-skill\scripts\cli.py" verify
```

## 命令

```powershell
$py  = "<runtime>\python.exe"
$cli = "D:\可研1\keyan-writing-skill\scripts\cli.py"
$ws  = "D:\可研1\keyan-work"

& $py $cli init   --workspace $ws
& $py $cli scan   --input "D:\...\建设方案xxx.docx"          --role source   --workspace $ws
& $py $cli index  --workspace $ws
& $py $cli plan   --scope 5.13 --workspace $ws
& $py $cli author --scope 5.13 --workspace $ws
& $py $cli check  --scope 5.13 --workspace $ws
& $py $cli run    --scope 5.13 --jobs 3 --workspace $ws
& $py $cli report --workspace $ws
& $py $cli publish --scope 5.13 --workspace $ws   # 成品 md -> <项目根>/可研成果/
& $py $cli clean   --workspace $ws                # 收尾：删除 <项目根>/临时脚本/
```

| 命令 | 作用 |
|---|---|
| `init` | 建立工作区目录，并把内置可研目录骨架物化到 `template/` |
| `scan --input <文件> --role source\|template\|material_01` | 解析 docx/md/txt → 目录树、叶子清单、全文 Markdown、图片素材；`source` 必需，`template` 仅在替换内置骨架时使用，`material_01` 等用于补充材料 |
| `tree [--role] [--grep 词] [--level N] [--leaves] [--output 路径] [--max-depth N]` | 查看/导出目录树 |
| `index` | 建立模板↔建设方案的同名索引与语义候选映射（写 `match/`） |
| `plan --scope <范围>` | 对范围内节点做来源路由，产出计划总览与每节点写作任务单/骨架 |
| `author --scope <范围>` | 落稿：同名/语义节点直接出草稿；缺料节点先生成全文取证任务包，必须由 Agent 完成正文后再装配 |
| `run --scope <范围>` | 同一进程执行 `plan → author → check`；复用完整草稿和有效缓存，适合断点续跑 |
| `assemble --scope <范围>` | 把草稿装配为 `<ws>/chapters/<范围>.md`，并自动发布到 `<项目根>/可研成果/` |
| `check --scope <范围>` | 校验规范覆盖、篇幅下限、空标题、GAP/TODO、重复复制、复制完整性 |
| `report` | 编写进度与缺口清单 |
| `search -q <词> [--dir <目录>] [--exact-only]` | 建设方案原文检索（精确 + 近似） |
| `kb -q <词> [--kb 库名] [--list] [--save]` | 知识库检索（Dify，无凭据时回退本地 wiki）；`--save` 落盘 `normalized/KB-*.md` |
| `link --node <模板节点> --source <建设方案节点> [--mode copy\|migrate\|write] [--note 理由]` | 手工锚点：把模板节点钉到指定来源节点（最高优先级）；`--list` 查看、`--remove` 删除 |
| `anchor --scope <模板域> [--from <建设方案域>] [--depth N]` | 自动锚点：保序最优分配把模板域对到建设方案域，低置信度进复核清单；`--dry-run` 只看不写、`--review` 看清单、`--apply [判读.json]` 回填方案 D 判读 |
| `publish [--scope <范围>]` | 把装配稿发布到 `<项目根>/可研成果/<编号> <标题>.md`（中文名目录，用户直接取用）；省略 `--scope` 则发布 `chapters/` 下全部 |
| `clean` | 删除 `<项目根>/临时脚本/`（收尾清理）；不动 `可研成果/` 与工作区 |
| `verify` | 自检依赖、规范目录、知识库可达性 |

**范围写法**：`5`（整章）、`5.6`、`5.6.1`、`chapter_05_06`、`第五章第六节`、`all`。
默认自动展开一层；`--node` 只处理该节点本身；`--deep` 展开整棵子树到最小层级。

**常用开关**：`--no-kb`（跳过知识库，快）、`--allow-web`（允许联网检索，默认关）、
`--force`（覆盖已有草稿）、`--force-write`（强制走撰写，不做同名直复）、`--no-assemble`（不自动装配）、
`--ignore-claims`（忽略归属仲裁，退回"同名就直复"）、`--ignore-overrides`（忽略手工锚点）、
`--jobs N`（并发执行已冻结路由后的知识库查询，默认 3）、`--refresh-cache`（强制重建优化缓存）、
`--no-publish`（只写 `chapters/`，不发布到 `可研成果/`）。

缓存不得改变取材顺序或评分：路由缓存由建设方案、模板、章节规范、手工锚点、算法代码的内容哈希共同失效；
知识库缓存保留来源、页码、分数和原文；SQLite 索引只加速召回，仍使用原 bigram 评分和稳定排序。
路由和段落认领始终串行，只有路由冻结后的独立知识库查询可以并发。

**退出码**：`0` 成功；`2` 部分完成（仍有 GAP / 待写）；`3` 冲突（检测到违例复制）；`1` 错误。

## 取材顺序与路由

优先级不可调换（细则见 `references/workflow.md`）：

1. **`exact_direct_copy` 同名直复** — 标题归一化后与建设方案相同，**且通过归属仲裁** →
   整棵子树原文复制（详见下节；未通过仲裁的同名候选会降级，不会复制）。
2. **`semantic_migrate` 语义候选迁移** — 无同名 → 取相似标题候选，逐条比对候选正文与章节规范的贴合度，
   选最合适的一个整段迁移，再按规范补足缺失要素。
3. **`title_migrate` 相关标题迁移** — 标题相关且正文贴合本节规范时迁移。
4. **`paragraph_reuse` 建设方案正文复用** — 标题未映射时先查素材范围正文，仍不足再查输入文件全文；法律法规、标准规范同时识别法规名称和标准编号。多段由 agent 排序、排版并补独立过渡，原文事实不改。
5. **`material_reuse` 用户材料复用** — 建设方案不足时，先检索已登记的 `material_01`、`material_02` 等材料标题，再检索其正文。
6. **`grounded_write` 证据撰写** — 本地材料不足才查知识库，必要时在授权范围内联网，按本小节规范完成正文。
7. **`gap` 缺口** — 证据仍不足时列明缺什么，不编造。

相关标题和正文命中只是取材依据，不是成稿验收。先核对目标祖先路径与小节规范；被归属仲裁排除的来源不得在正文检索时绕回来。
脚本保留复制正文或逐段哈希，`check` 复核；完整流程见 `references/local-reuse.md`。

## 同名归属仲裁

**问题**：建设方案里只有一个「建设目标」（在"建设目标与建设内容"下），模板里却有多个
（概述>项目概况、安全一体化平台、运行维护系统设计方案…）。若按标题同名就复制，会把项目级
建设目标搬到运维系统小节里。

**做法**（`scripts/keyan/arbitration.py`，`index` 产出 `match/同名归属.{json,md}`）：

1. **兄弟组锚定素材范围**：某模板父节点的子节点若多数命中同一个建设方案节点的子级
   （如模板 5.13.x ← 建设方案 9.9.2.x），则该建设方案节点就是这组的"素材范围"（scope）。
2. **综合分** = 0.45 结构上下文（父级/祖先标题相似度）+ 0.25 规范贴合 + 0.30 范围归属。
3. **认领仲裁**：同一建设方案节点被多个模板节点同名认领时，分高者直复；分低且上下文弱
   （<0.5）者降级。范围内找不到同名子节点 → 直接不直复，转撰写。

降级诊断：`exact_out_of_scope`（候选不在本节素材范围内）、`exact_claimed_by_better_owner`
（已被更贴合的小节占用）、`exact_source_reserved`（已被手工锚点占用）。降级节点转
`semantic_migrate` 或 `grounded_write`，并在 `plan/<节点>.任务单.md` 里给出
**素材范围**（如"9.9.2 运行维护系统设计，子树 3832 字，含运行维护内容/流程/制度/质保内容"）
与摘录，供撰写时取证。

**手工锚点兜底**：判定不合意时显式钉住，优先级最高：

```powershell
& $py $cli link --node chapter_05_13_01 --source chapter_09_09_02 --mode write `
                --note "运维系统的建设目标取自9.9.2" --workspace $ws
& $py $cli link --list   --workspace $ws      # 查看
& $py $cli link --node chapter_05_13_01 --remove --workspace $ws
```

`--mode copy` 整段直复｜`migrate` 整段迁移后按规范补足｜`write` 只作素材范围（来源是容器节点时默认，
避免把子节点内容重复搬入）。锚点写入 `match/来源覆盖.json`，`plan`/`author` 全程尊重。

**自动锚点（A＋B）与判读（D）**：每换一份建设方案就手写一遍锚点不现实，`anchor` 按结构证据自动派生，
低置信度交 agent 判读后回填：

```powershell
& $py $cli anchor --scope 5.6 --from 9 --depth 2 --workspace $ws   # 派生 → match/自动锚点.json
& $py $cli anchor --review --workspace $ws                         # 待判读清单 → reports/锚点复核.md
& $py $cli anchor --apply  --workspace $ws                         # 判读回填后重算
```

同级配对**保序**（不允许交叉）、两侧都允许留空（模板新增／来源独有不会被硬凑成一对），
得分 = `0.50×标题 + 0.28×体量 + 0.08×表 + 0.07×图 + 0.07×子节点`；≥0.60 直接落锚、
≥0.35 落锚并进复核、<0.35 不落锚只等判读。
**生效锚点 = 自动锚点为主体、人工锚点覆盖同名 key**：`link` 只写 `来源覆盖.json`（人工，永不被自动
派生覆盖），`anchor` 只写 `自动锚点.json`（可随时重算）。细则见 `references/workflow.md` 阶段 2。

## 质量基准

以 `references/chapter-writing/` 为准：章级总纲 + 小节级规范（必写要素、篇幅下限、必备表格、检查清单）。
`plan`/`check` 会解析这些要素算覆盖度，`check` 报告 `spec_coverage`、`below_floor`、`missing_tables`。
写任何小节前先读对应小节规范，再动笔。

## 已知约束

- `author` 对标题迁移、正文复用和其他材料命中自动搬运原文；agent 仍需复核语义、整理多段并补规范缺项。
  `grounded_write` 的**任务单 + 骨架 + 待写草稿**是中间产物，不能装配成最终章节，也不能直接交付；脚本会生成 `plan/AGENT待完成.md`，Agent 必须先完成正文。
- 标题没有命中不等于没有材料：必须继续检索建设方案全文正文，再检索用户补充材料；只有本地材料不足时才查知识库，获准联网后才查网络。不能因为标题未映射就留下空标题。
- 建设方案与模板章节编号往往不一致，一律按**标题**匹配，不按编号对齐。
- 同名 ≠ 对口：泛化标题可能命中别处（模板 5.13.1「建设目标」对不上建设方案 7.1「建设目标」）。
  `index`/`plan` 会用"同名归属仲裁"判定，被降级的节点报 `exact_out_of_scope` /
  `exact_claimed_by_better_owner` 并转撰写；判定不对时用 `link` 手工锚点钉住来源。
- `--scope 5.13` 处理的是 5.13 的**子节点**（5.13.1、5.13.2 …）；要连 5.13 自身正文一起写就加 `--node`。
- 大文件慢：38MB / 1.8 万段落约 45–60 s，有缓存；非必要不加 `--rebuild`。
- 知识库单次查询 30–75 s，只在 `grounded_write` / `gap` 节点触发。
- `check` 输出按 `--limit`（默认 40）截断，看 `measurements_total` / `truncated` 判断是否被裁。
