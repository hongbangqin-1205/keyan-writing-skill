# keyan-writing-skill

依据技能内置的**可研模板目录骨架**把**建设方案**逐节点写成可行性研究报告的 Codex 技能。
默认只需上传建设方案；只有更换固定模板时才需要另传模板文件。
取材优先级固定：**对口同名直复 → 相关标题迁移 → 正文段落复用 → 用户其他材料 → 知识库/网络取证撰写 → 显式缺口**。

- 使用说明（技能入口）：[`SKILL.md`](SKILL.md)
- 全流程细则：[`references/workflow.md`](references/workflow.md)
- 未映射节点处理：[`references/local-reuse.md`](references/local-reuse.md)
- 章节规范（质量基准）：[`references/chapter-writing/`](references/chapter-writing)
- 旧版文档存档：[`references/legacy/`](references/legacy)

## 输出与目录约定

技能运行时的目录分工固定，成品和临时文件分开放：

- `<项目根>/可研成果/` —— **交付目录**。`assemble` / `author` 装配后自动把成品 md 按
  `<编号> <标题>.md`（如 `5.6.1 数智潍坊健康大脑.md`）发布到这里，用户可直接翻看；需要补发时跑 `publish`。
- `<项目根>/临时脚本/` —— **临时脚本目录**。一次性探查、校对、统计脚本统一写这里，绝不落在项目根；
  收尾跑 `clean` 把整个目录删掉。
- 项目根 = 工作区的上一级（`keyan-work` 的上一级），输入文件与工作区本身不受影响。

## 发布结构

本目录已经按可上传的 skill 根目录组织，可直接作为一个整体上传；不要只上传 `SKILL.md` 或
`scripts/` 子目录。核心结构如下：

```text
keyan-writing-skill/
├── SKILL.md
├── metadata.json
├── examples/
│   ├── example1.md
│   └── example2.md
├── scripts/
│   ├── main.py
│   └── utils.py
├── resources/
│   ├── prompt.md
│   └── config.yaml
├── tests/
│   ├── test_cases.md
│   └── eval.yaml
├── README.md
└── CHANGELOG.md
```

另外保留两个运行扩展目录：`references/` 存放章节规范、流程和内置模板骨架，
`agents/openai.yaml` 提供网页端 Agent 的显示信息；它们不是多余文件，上传时应一并保留。

推荐在仓库根目录执行：

```powershell
$py = "<Python 3.10+>"
& $py -m pip install python-docx
& $py scripts/main.py verify --workspace "D:\可研1\keyan-work"
& $py -m pytest -q
```

通过 GitHub 发布后，可将仓库路径交给支持 `skills.sh` 的 Agent 导入。导入时应指向包含
`SKILL.md` 的 skill 根目录，而不是 `scripts/` 或 `references/` 子目录。

## 快速开始

```powershell
$py  = "<Codex 运行时>\dependencies\python\python.exe"
$cli = "D:\可研1\keyan-writing-skill\scripts\cli.py"
$ws  = "D:\可研1\keyan-work"

& $py $cli verify --workspace $ws
& $py $cli init   --workspace $ws
& $py $cli scan   --input "建设方案.docx" --role source   --workspace $ws
& $py $cli index  --workspace $ws
& $py $cli anchor --scope 5.6 --from 9 --depth 2 --workspace $ws  # 自动锚点（重算覆盖）
& $py $cli anchor --review --workspace $ws                        # 待判读清单
& $py $cli plan   --scope 5.13 --workspace $ws
& $py $cli author --scope 5.13 --workspace $ws
& $py $cli check  --scope 5.13 --workspace $ws
& $py $cli report --workspace $ws
& $py $cli publish --scope 5.13 --workspace $ws   # 成品 md -> <项目根>/可研成果/
& $py $cli clean  --workspace $ws                 # 收尾：删除 <项目根>/临时脚本/
```

`init` 会把 `references/template-outline/可研报告目录骨架.md` 自动编译到工作区的
`template/目录树.json`。如确需改用另一套固定模板，再额外执行
`scan --input "新模板.docx" --role template` 覆盖内置骨架。

也可以使用统一入口 `scripts/main.py` 替代 `scripts/cli.py`。

## 测试

```powershell
& $py -m pytest -q      # 在技能根目录执行
```

其他材料在 `plan` 前登记，每份使用独立角色：

```powershell
& $py $cli scan --input "补充调研报告.docx" --role material_01 --workspace $ws
& $py $cli scan --input "运维补充方案.docx" --role material_02 --workspace $ws
```

标题未映射时不会直接跳到推荐小标题：先复用建设方案正文，再查其他材料；多段由 agent 排序、排版和补过渡，
本地证据不足才查知识库与网络。`--allow-web` 只是授权标志，脚本不会自行联网；`author` 生成的任务包或待写骨架不是最终报告，仍需 agent 完成正文并运行 `check`。

## 依赖

Python 3.10+ 与 `python-docx`（其余为标准库）。知识库检索为可选，
找到 `consulting-kb-retrieval` 时启用，否则回退本地 wiki 或跳过。
