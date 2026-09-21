# 可研编写工作流（keyan-writing）

本文件是当前版本（v0.1.x）的唯一权威流程说明，与 `scripts/keyan/` 实现一致。
不要照抄 `references/legacy/` 里的命令——那是早期版本的接口。

核心原则：**先建树、再路由、后动笔；优先复用本地原文，再查用户补充材料，最后才查知识库/网络；每一段要么可追溯到来源，要么标 GAP，不得编造。**

---

## 阶段 0 · 准备

```powershell
$py  = "<runtime>\python.exe"
$cli = "D:\可研1\keyan-writing-skill\scripts\cli.py"
$ws  = "D:\可研1\keyan-work"

& $py $cli verify --workspace $ws      # 依赖 / 规范目录 / 知识库可达性
& $py $cli init   --workspace $ws
```

`verify` 检查 python-docx、`references/chapter-writing/` 是否存在（≥7 章）、知识库是否可达。
知识库不可达不影响主流程，只是检索降级为本地 wiki。

---

## 阶段 1 · 扫描输入，建立"到最小层级"的目录树

默认只扫描建设方案。`init` 已把技能内置的项目中立目录骨架自动物化到 `template/`：

```powershell
& $py $cli scan --input "建设方案.docx"       --role source   --workspace $ws
# 支持 .docx / .md / .txt；源文件更新后重扫，或加 --rebuild 强制重解析
```

内置骨架来自 `references/template-outline/可研报告目录骨架.md`，只含固定标题，不含示例正文。
1.3.2、3.1、3.2、3.3.1、5.6、6.3.3、11.1、11.3 的项目专属子节点不会继承旧项目；
其中 5.6 必须在阶段 2 用 `project-tree` 按本次建设方案派生。只有用户明确更换固定模板时，才执行：

```powershell
& $py $cli scan --input "另一套可研模板.docx" --role template --workspace $ws
```

产物（`source/` 与 `template/` 目录下同名）：

| 文件 | 说明 |
|---|---|
| `目录树.json` | 结构化树，供后续命令使用 |
| `目录树.md` | 人读缩进树，含每节点 `own_chars`/`subtree_chars`/表数/图数 |
| `叶子清单.md` | 所有叶子（最小层级）标题索引 |
| `<原文件名>.md` | 全文 Markdown（标题层级重挂，表格转 Markdown，图片引用 `assets/`） |
| `blocks.json` | 段落级缓存，含样式、大纲级别、表格、图片 rId |
| `assets/` | 从 docx 抽出的内嵌图片 |

**"最小层级"** = 文档大纲（标题样式或 `outlineLvl`）能达到的最深一级；层级是压缩后的连续深度，
不会被空级别撑出空洞。用 `tree --leaves` 或看 `叶子清单.md` 核对：

```powershell
& $py $cli tree --role source --leaves --limit 20
& $py $cli tree --role template --grep 安全 --output D:\...\模板_安全相关.md
```

扫描后先自检三件事，再进入下一步：

1. 模板树的最小层级是否覆盖到小节（不是停在"第 X 章"）。
2. 建设方案树是否出现明显错层（例如正文段落被误判为标题）——看 `目录树.md` 的层级缩进。
3. `stats`（`nodes` / `leaves` / `max_depth` / `tables` / `images`）是否与预期量级相符。

---

## 阶段 2 · 建立索引与路由计划

```powershell
& $py $cli index --workspace $ws
& $py $cli plan  --scope 5.13 --workspace $ws
```

`index` 建立模板节点 ↔ 建设方案节点的同名索引与候选映射（`match/`），并给出整体分布
（同名 / 语义 / 需撰写各占多少）。

`plan` 对 scope 内每个节点给出一个决策（`plan/<范围>.计划.json`）和一份人读总览
（`plan/<范围>.计划总览.md`），并为每个节点写 `plan/<节点>.任务单.md`（+ `.json`）与 `<节点>.骨架.md`。

**范围（scope）写法**：`5`（整章）、`5.6`、`5.6.1`、`chapter_05_06`、`第五章第六节`、`all`。

**跨项目 5.6（先项目目录后生成）**：一个项目一个全新工作区。扫描共用模板和本项目建设方案后，
运行 `project-tree --from <本次系统域>` 列出直接子节点候选；核对哪些是真正属于 5.6 的系统/领域，
再运行 `project-tree --from <本次系统域> --systems <编号1,编号2,...>` 派生 `template/项目目录树.json`
和指纹绑定的 `template/项目目录元数据.json`。`--from` 可省略，仅在候选来源域明确时自动识别；
`--systems` 不可省略确认。之后按项目目录中的 5.6.N 执行 `plan` → `author` → `check`。
原模板的潍坊目录保持只读，项目目录实例优先用于路由和装配；本项目来源锚点优先于旧手工锚点。
`project-tree` 从已确认来源子树生成对应标题及层级，不等于已经完成预算清单的语义重挂：
来源层级含歧义时须逐项按正文/表格/预算证据复核，不得宣称已自动解决。
扫描后若换建设方案，直接使用新工作区；旧工作区有锚点或草稿时 `scan` 拒绝覆盖。
默认自动展开一层；`--node` 只处理节点本身；`--deep` 展开整棵子树到最小层级。
用户指明"第 X 章第 Y 节"时，`--scope X.Y` 默认处理的是**该节的子节点**（各小节正文）；
若要连该节自身的正文一起写，加 `--node`。装配时节的标题由模板树给出，正文来自各子节点草稿，
因此 `--scope 5.13` = 写 5.13.1、5.13.2 …（不含 5.13 自己的正文段）。

**同名归属仲裁**：`index` 会同时产出 `match/同名归属.json`（结构化）与 `match/同名归属.md`
（人读：降级清单 / 一源多处复用 / 素材范围锚定）。`plan`、`author` 在路由前重建该仲裁，
因此改动手工锚点后无需重跑 `index`。判定式：

```
综合分 = 0.45 × 结构上下文 + 0.25 × 规范贴合 + 0.30 × 素材范围归属
结构上下文 = 0.5 × 父级标题相似度 + 0.3 × 祖先路径最相近一对 + 0.2 × 完全相同祖先覆盖率
素材范围(scope) = 兄弟节点多数命中的那个建设方案父节点（兄弟组锚定，并向深层传播）
```

同一来源被多个模板节点认领时，只有分最高者直复；其余在"结构上下文 <0.5 且分数低于赢家 0.15
以上"时降级（上下文强的复用属正常，例如同一系统在概述章与第五章各出现一次，不降级）。

决策模式与判据：

| 模式 | 触发条件 | 判据细节 |
|---|---|---|
| `exact_direct_copy` | 标题同名 **且通过归属仲裁** | 范围内候选得分最高且未被更贴合的小节占用；多个同名时报 `ambiguous_exact` |
| `semantic_migrate` | 无同名，但有可迁移候选 | 召回：标题相似 ≥0.34、少量增删字的近似标题 **或** 属同义词族；短标题候选也保留；排序：`combined = 0.55×标题相似 + 0.45×规范贴合`；接受：标题相似 ≥0.34 或同义族，否则 `combined ≥ 0.45` |
| `grounded_write` | 候选不达标或不存在 | 触发知识库检索；政策文号/标准版本/法规日期必查 |
| `gap` | 素材不足 | 不编造，输出缺口清单 |

`plan` 输出的诊断码（写在决策与计划里）：

- `ambiguous_exact`：同名多选，已按上下文择优。
- `thin_match`：同名子树 <400 字且无子节点，复制后需按规范补足。
- `spec_gap_after_copy`：同名直复内容对规范要素覆盖 <0.35，需按规范补写。
- `migrate_weak_spec_fit`：迁移候选规范覆盖 <0.2，迁移后需大量补写。
- `candidate_below_threshold`：语义候选接近但不达标，转撰写。
- `spec_missing`：找不到对应章节规范，按通用要求撰写。
- `exact_out_of_scope`：同名候选不在本节素材范围内（如模板 5.13.1「建设目标」对不上建设方案 7.1）。
- `exact_claimed_by_better_owner`：同名候选已归属分更高的模板节点。
- `exact_source_reserved`：同名候选已被手工锚点占用。
- `scope_material_only`：本节的素材范围节点自身正文偏薄，只作撰写素材，不做整段迁移。
- `ambiguous_exact` 之外的降级都会写进 `plan/<范围>.计划总览.md` 顶部，便于逐条复核。

**同名但语义不符的自查**：标题完全相同不代表内容对口。当 `plan` 给出上下文兼容度低（如 0.00）、
`spec_gap_after_copy`（规范覆盖 <0.35）时，说明命中的可能是另一章的同名小节（例如模板"建设目标"
命中第七节的"建设目标"）。同名规则仍优先复制，但必须按规范补足，并在交付前确认这个同名是否
就是模板要的那一节；确认不成立时用 `--force-write` 改走撰写，或改选语义候选。

**手工锚点（最高优先级）**：仲裁判定不合意时显式指定来源，写 `match/来源覆盖.json`：

```powershell
& $py $cli link --node chapter_05_13_01 --source chapter_09_09_02 --mode write --note "理由" --workspace $ws
& $py $cli link --list --workspace $ws
& $py $cli link --node chapter_05_13_01 --remove --workspace $ws
```

`--mode copy` 整段直复；`migrate` 整段迁移后按规范补足；`write` 只作素材范围。来源是容器节点
（含子节点）时默认 `write`，避免把子节点内容整棵搬入造成跨节重复。被钉住的建设方案节点不会
再被其他模板节点直复。

**自动锚点（保序最优分配 A＋B）**：换一份建设方案就把锚点重写一遍太费事，`anchor` 把这件事变成
可复算的派生。同级配对沿两侧文档顺序单调推进（**保序**：不允许交叉），在保序前提下用序列对齐
求总得分最大的配对，两侧都允许留空，于是"模板新增""来源独有"不会被硬凑成一对。

```powershell
& $py $cli anchor --scope 5.6 --from 9 --depth 2 --workspace $ws   # 派生并落盘
& $py $cli anchor --scope 5.6 --from 9 --dry-run --workspace $ws  # 只看不写
& $py $cli anchor --review  --workspace $ws                        # 复核清单（回放已落盘结果，不重算）
& $py $cli anchor --apply   --workspace $ws                        # 回填判读结论后重算
```

`--apply` / `--review` 不带 `--scope` 时沿用上次派生记录里的域（报 `reuse_stored` 诊断）。
省略 `--from` 时按"与模板域子表最合得来"自动选建设方案域（报 `auto_source` 诊断）。
产出 `match/自动锚点.json`（每条含 `score`／`basis`／`tier`／`auto_rule`）与
`reports/锚点复核.md`（待判读清单）。

打分只用可核验的结构证据，不做语义猜测：

```
得分 = 0.50 × 标题相似 + 0.28 × 子树体量比 + 0.08 × 表数比 + 0.07 × 图数比 + 0.07 × 子节点数比
```

（表／图／子节点各 +1 平滑；两侧都没有记满分。）分档与处置：

| 分档 | 分数 | 处置 |
|---|---|---|
| `high` | ≥ 0.60 | 直接落锚 |
| `mid` | ≥ 0.35 | 落锚，并进复核清单 |
| `low` | < 0.35 | **不落锚**，只进复核清单等判读 |

模式由结构自定：同构子树（自身分 ≥0.60、子节点配对覆盖 ≥0.60、平均配对分 ≥0.50）走 `copy`；
叶子节点或自身分达线的容器走 `migrate`；对不上又不够像的容器才退 `write`。
另有 `excluded`（已有人工锚点）、`unmatched_template`（模板新增）、`unmatched_source`（来源独有）
三类结构差，直接列进复核清单而不是硬凑成一对。

**判读回填（方案 D）**：复核清单里的每一条都由 agent 逐条判读，把结论写进 `match/锚点判读.json`
再 `--apply`：

```json
{
  "chapter_05_06_04_01": { "action": "accept", "source": "chapter_09_04_01", "mode": "copy", "note": "9.4.1 功能架构改名" },
  "chapter_05_06_04_05": { "action": "reject", "note": "来源侧无对应，回归归属仲裁" },
  "chapter_05_06_08_01": { "action": "new" },
  "chapter_09_09":        { "action": "ignore" }
}
```

`accept` 采纳该来源（`mode` 省略时按结构自定）｜`reject` 不落锚、交回归属仲裁｜
`new` 模板新增、来源侧确无对应｜`ignore` 来源独有、忽略（挂在它下面的锚点一并撤销）。
判过的条目退出复核清单并记进 `summary.resolved`；`decision_diagnostics` 报
`unknown_action`／`unknown_node`／`decision_source_missing`。

**两条锚点的关系**：`match/来源覆盖.json` 是人工锚点，`match/自动锚点.json` 是自动锚点；
生效锚点 = 自动锚点为主体、人工锚点在同名 key 上覆盖。因此

- **人工锚点永不被动**：`link` 只写 `来源覆盖.json`；`anchor` 也不给已钉住的节点落锚，
  只沿用它的来源继续往深层派生（报 `excluded`）。
- **自动锚点可随时重算覆盖**：换输入文件重跑 `anchor` 即可，不必逐条改写。

路由侧区分两者来路：自动锚点报 `自动锚点：…（保序最优分配（A+B），序位对齐得分 0.631）`
并写 `anchor_auto`／`anchor_tier`／`anchor_score`／`anchor_rule`；人工锚点仍报 `手工锚点：…`。
`link --list` 会附带 `auto_count` 与 `auto_anchors` 诊断，提示还有多少自动锚点在生效。

**动笔前必读任务单**：任务单里已列出该节点的小节规范（必写要素、篇幅下限、必备表格、检查清单）、
来源候选、知识库命中、下一步动作。骨架文件给出标题层级与要素占位。

---

## 阶段 3 · 落稿

```powershell
& $py $cli author --scope 5.13 --workspace $ws
```

`author` 按路由结果分派：

- `exact_direct_copy` / `semantic_migrate` → **直接出稿**：把建设方案对应子树整段复制进
  `drafts/<节点>.md`，标题按模板层级重挂，正文不改写；同时写
  `drafts/<节点>.sidecar.json`（来源 key/编号/标题、`integrity_sha256`、候选与诊断）
  与 `drafts/<节点>.对照.md`（规范逐项命中/缺失清单）。`llm_rewrite = False`。
  已有草稿默认跳过，需要覆盖加 `--force`。
- `grounded_write` / `gap` → **先出取证任务包**：`plan/<节点>.任务单.md` + `<节点>.骨架.md` +
  `drafts/<节点>.md`（带 `<!-- keyan mode=grounded_write ... -->` 头与 `待写`/`TODO` 标记）。这是中间产物；脚本不会把它装配成最终章节，并会写 `plan/AGENT待完成.md`。

### 撰写 `grounded_write` 正文（由你完成）

1. 读 `plan/<节点>.任务单.md` 与 `references/chapter-writing/` 下对应小节规范
   （章级 `chapter-XX.md` + 小节级 `sections/chapter-XX/NN-*.md`）。
2. 取证据：先按目标标题及祖先路径查建设方案全文 Markdown 和 blocks；标题命中失败时，必须改查正文段落，优先复用原文。再用 `search -q <关键词>` 补充全文结果；`kb -q <关键词> --save` 仅在本地材料和用户补充材料不足时查知识库并落盘
   `normalized/KB-*.md`；`--allow-web`（或用户明确同意）时才联网，联网结果同样落盘。
3. 按规范撰写，覆盖全部必写要素，达到篇幅下限，补齐必备表格（用 Markdown 表格）。
4. 任务单里的 **素材范围**（`evidence_scope`）是本节的首选取材子树，不是全文检索的绝对边界；
   范围内只有弱关键词命中时，必须继续比较全文的近似标题和正文核心词，跨范围引用要说明理由；
   范围节点自身正文偏薄时（`scope_material_only`）要结合其子节点素材归纳。
5. 缺证据处写 `GAP：<缺什么>`，技术推导写 `〔推导：依据〕`；**不得编造数字**。
5. 删掉草稿首行的 `keyan mode=...` 注释与所有 `待写`/`TODO` 标记。
6. 删除骨架中的 `待写`/`TODO`，重跑 `check` 确认 `todo_remaining = 0`、空标题为 0、篇幅达标；在此之前不得运行最终 `assemble` 或把章节交付。

---

## 阶段 4 · 校验

```powershell
& $py $cli check  --scope 5.13 --workspace $ws
& $py $cli report --workspace $ws
```

`check` 对每个叶子节点（以及已出稿的容器节点）测量：去空白字数、标题数、空标题、
`GAP` 数、`待写/TODO` 数、规范要素覆盖、篇幅下限、必备表格、复制完整性（sidecar sha256）、
跨节点 ≥40 字逐字重复。

常见诊断码与处理：

| 诊断码 | 含义 | 处理 |
|---|---|---|
| `draft_missing` | 无草稿（看骨架是否已生成） | 跑 `author`，或按任务单撰写 |
| `todo_remaining` | 仍有"待写/TODO"标记 | 写完并删除标记 |
| `gap_present` | 有 GAP 句（不计有效篇幅） | 补证据或显式确认待核 |
| `empty_heading` | 标题下无正文 | 补内容或删空标题 |
| `spec_coverage_low` | 规范要素覆盖 <0.5 | 按 `spec_miss` 列表补写 |
| `below_floor` | 字数低于规范下限 | 扩写（有证据地扩写，不灌水） |
| `missing_tables` | 缺必备表格 | 按规范补表 |
| `copy_modified` | 直复正文哈希与来源不一致 | 恢复原文，或改走语义迁移/撰写并更新 sidecar |
| 跨节点重复 | 两节出现 ≥40 字逐字相同 | 删重复段落，改为引用 |

`report` 汇总已产出草稿（模式、字数、有效字数、来源）与缺口清单，写 `reports/编写进度.md`。

---

## 阶段 5 · 交付

```powershell
& $py $cli assemble --scope 5 --workspace $ws
& $py $cli clean --workspace $ws
```

把 scope 内草稿按模板结构递归装配为 `chapters/<范围>.md`（带 `used_drafts` sidecar），
并自动发布到项目根的 `可研成果/<编号> <标题>.md`（中文名目录，用户直接取用）。
`author` 默认已自动装配并发布一次；需要重新装配时单独跑 `assemble`，只想补发成品跑
`publish [--scope <范围>]`，加 `--no-publish` 则只写 `chapters/` 不发布。

一次性临时脚本统一写项目根的 `临时脚本/`，任务收尾跑 `clean` 把整个目录删掉（不动 `可研成果/` 与工作区）。

导出 Word 属于下游动作：Markdown → docx 时保持标题层级与编号一致，图片用 `assets/` 中的原图。

---

## 来源优先级与使用边界

映射不到标题时不能直接输出推荐小标题。顺序是：建设方案相关标题 → 建设方案正文段落 → 用户补充材料的标题和正文 → 知识库/网络取证撰写 → GAP。命中部分内容后，继续为章节规范中未覆盖的要素取材。

正文复用允许来源标题不相似，但必须核对目标祖先路径、素材范围、主体和上下文。先查范围内正文，范围内不足再查输入文件全文；全文回退排除范围外同名标题，但不排除确实相关的正文段落。法律法规、标准规范还要检索法规名称、标准编号和“国家法律法规”等正文表述。多段命中由 agent 排序、排版并补独立过渡；原文金额、数字、主体、条件和口径不得改写。被同名归属仲裁排除的候选不能换成“正文复用”再次搬入。

补充材料使用 `material_01`、`material_02` 等独立角色扫描，详见 `references/local-reuse.md`。

| 来源 | 用于 | 禁止 |
|---|---|---|
| 本地建设方案（`source/`） | 项目事实、现状、建设内容、规模、金额；同名节点原文直复 | 未经核验直接采信过期版本数字 |
| 知识库（`consulting-kb-retrieval`） | 政策文号、标准规范版本、法规日期、行业口径 | 把案例项目的人名/地点/金额当本项目事实 |
| 网络检索（需 `--allow-web` 或用户同意） | 最新政策/标准/公开技术资料，用于核对版本 | 未落盘就引用；把检索摘要当原文引用 |
| 模型自有知识 | 仅用于组织语言、行业通识表述 | 作为数字、文号、结论的唯一依据 |

命中知识库或网络材料后落盘（`normalized/KB-*.md` / `WEB-*.md`），再在正文中引用。

---

## 运行环境与常见坑

- **解释器**：用 Codex 运行时 python（`load_workspace_dependencies`），PATH 上的 `python` 在
  Windows 可能是应用商店占位符（无输出、无报错）。
- **编码**：本技能所有文件为无 BOM UTF-8；Windows 控制台读中文前先
  `chcp 65001` 并设 `[Console]::OutputEncoding`、`$env:PYTHONIOENCODING='utf-8'`。
- **性能**：38MB / 1.8 万段落文档扫描约 45–60 s，`index` 约 40 s；重复运行靠 `blocks.json` 缓存，
  非必要不加 `--rebuild`。`author --scope all` 可能耗时 10 分钟以上。
- **知识库**：Dify 单次查询 30–75 s，只在 `grounded_write`/`gap` 节点触发；批量撰写时可用
  `--no-kb` 先落稿，再对缺料节点单独 `kb` 检索。
- **模板章数差异**：模板可能与规范目录树章数不同（更少/更多），一律按标题匹配、按模板结构成文。
- **`check` 输出**：默认 `--limit 40`，大章会被截断，看 `measurements_total`/`truncated`。
- **退出码**：`0` 成功；`2` 部分完成（GAP/待写残留）；`3` 冲突（违例复制）；`1` 错误。
  在自动化流程里把 `2` 当"待补"而不是失败。

---

## 典型交互

| 用户说法 | 执行 |
|---|---|
| "把这份建设方案按模板写成可研" | 阶段 0→2，然后逐章 `author` + `check` + `report` |
| "写第五章第六节" | `plan --scope 5.6` → `author --scope 5.6` → `check --scope 5.6` |
| "这一节没有同名内容，怎么办" | 看 `plan` 决策：`semantic_migrate` 会列出候选、理由与缺项；不达标则按 `grounded_write` 任务单撰写 |
| "这一节的同名内容明显对不上" | 看 `match/同名归属.md` 的降级原因与素材范围；判定不对就 `link --node ... --source ...` 钉住来源后重跑 `plan`/`author` |
| "同名被搬到别处了 / 我要改回同名就复制" | `--ignore-claims` 退回朴素同名直复；或 `link --mode copy` 只针对个别节点 |
| "看看目录树对不对" | `tree --role template --leaves`、`tree --role source --grep <词>` |
| "哪里有缺口" | `report`（缺口清单）＋ `check` 的 `gap_present`/`todo_remaining` |
| "这一节内容太短" | `check` 看 `below_floor` 与 `spec_miss`，按规范要素与必备表格扩写 |
