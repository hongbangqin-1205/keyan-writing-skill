# keyan-writing-skill

[![skills.sh](https://skills.sh/b/hongbangqin-1205/keyan-writing-skill)](https://skills.sh/hongbangqin-1205/keyan-writing-skill)

**可研报告编写（keyan-writing）** —— 依据内置的**可研模板目录骨架**与章节规范，把**建设方案**
（以及调研报告、子系统方案等原料）逐节点写成可行性研究报告正文的 Agent Skill。

- 安装：`npx skills add hongbangqin-1205/keyan-writing-skill --skill keyan-writing`
- 技能页：https://skills.sh/hongbangqin-1205/keyan-writing-skill/keyan-writing
- 当前版本：**1.4.0**（见 [`keyan-writing/CHANGELOG.md`](keyan-writing/CHANGELOG.md)）

## 安装

```bash
npx skills add hongbangqin-1205/keyan-writing-skill --skill keyan-writing
```

也支持完整地址写法：

```bash
npx skills add https://github.com/hongbangqin-1205/keyan-writing-skill --skill keyan-writing
```

## 取材顺序（固定）

对口同名直复 → 相关标题迁移 → 建设方案正文复用 → 用户其他材料 → 知识库/网络取证撰写 → 显式缺口。

默认只需上传建设方案；只有要替换内置固定骨架时，才额外上传可研模板。

## 仓库结构

技能本体在 [`keyan-writing/`](keyan-writing) 子目录，仓库根只放本 README：

```text
keyan-writing-skill/
├── README.md          # 本文件（仓库入口）
└── keyan-writing/     # 技能根目录
    ├── SKILL.md       # 技能入口
    ├── metadata.json
    ├── CHANGELOG.md
    ├── agents/        # 网页端 Agent 显示信息
    ├── examples/
    ├── references/    # 流程细则、章节规范、内置模板骨架
    ├── resources/
    ├── scripts/       # CLI 与运行时脚本
    └── tests/         # 回归测试与 eval baseline
```

安装与使用说明见 [`keyan-writing/README.md`](keyan-writing/README.md)，技能入口见
[`keyan-writing/SKILL.md`](keyan-writing/SKILL.md)。

## 测试

```powershell
$py = "<Python 3.10+>"
& $py -m pytest -q                                              # 全量回归
& $py -m pytest -q tests/test_routing_hardening.py              # 路由加固定点
& $py tests/eval_routing_baseline.py                            # 确定性路由 baseline
```

## 许可证

本仓库当前未指定开源许可证；如需授权条款请补充 `LICENSE` 文件。
