# CLI 命令参考

入口 `python scripts/cli.py <command>`，所有输出为单行 JSON。退出码：`0` 成功/当前，
`2` partial/invalid/stale，`3` 冲突，`1` 错误或损坏。命令不依赖当前工作目录。
完整命令列表与参数以 `python scripts/cli.py <command> --help` 为准，此处只列常用写法。

```bash
python scripts/cli.py template                                    # base profile
python scripts/cli.py validate-outline --outline-path outline.json
python scripts/cli.py validate-evidence --source-manifest-path manifest.json --evidence evidence.json
python scripts/cli.py validate-dossier --outline-path outline.json --dossier-path docs
python scripts/cli.py validate-plan --outline-path outline.json --plan-path docs/chapter_05/计划.md
python scripts/cli.py check-depth --outline-path outline.json [--scope chapter_05_06]
python scripts/cli.py check-provenance [--min-anchor-coverage 0.8] [--max-derived-ratio 0.3]
python scripts/cli.py check-duplication --sources-dir normalized
python scripts/cli.py extract-features --features-path work/features.json
python scripts/cli.py check-features --features-path work/features.json
python scripts/cli.py check-baseline --outline-path outline.json
python scripts/cli.py self-check --outline-path outline.json --features-path work/features.json
python scripts/cli.py assemble --target-node chapter_05 --sections sections/chapter_05.json \
  --evidence evidence.json --source-manifest-path manifest.json --output chapters/chapter_05 \
  [--dossier-path docs/chapter_05]
python scripts/cli.py register-chapter chapters/chapter_05/chapter_05.md \
  --outline-path outline.json --source-manifest-path manifest.json
python scripts/cli.py check-chapter chapters/chapter_05/chapter_05.md
python scripts/cli.py check-consistency chapters/chapter_*/chapter_*.md --outline-path outline.json
python scripts/cli.py report --report-id latest --limit 20
```

## 本地检索（独立脚本，非 cli.py 子命令）

```bash
# 精确定位文号/标准号/机构名/金额（返回文件名+行号+片段）
python scripts/local_search.py --sources-dir normalized --query "国办发〔2021〕18号"
# 跨文件相关段落召回（精确 + BM25）
python scripts/local_search.py --sources-dir normalized --query "健康大脑 数据共享" --top-k 5
# 只要精确匹配
python scripts/local_search.py --sources-dir normalized --query "GB/T 22239-2019" --exact-only
```

仅返回候选片段与出处，是否选用由模型判断；详见 `references/source-priority.md`「检索提示」。

## 第五章主清单抽取（独立脚本，非 cli.py 子命令）

```bash
# 从建设方案预算清单表抽功能点候选（高召回，agent 确认后归一为主清单销号表）
python scripts/extract_checklist.py --source 建设方案.docx --out 主清单候选.json
python scripts/extract_checklist.py --source 建设方案.docx --out 主清单候选.md --format md
```

只召回"path + 功能描述 + 工作量 + 表标题"，不强行定层级；层级归一由 agent 做。
详见 `references/chapter-writing/chapter-05.md` 与 `chapter-05-checklist-template.md`。

## 阶段 → 命令映射

| 阶段 | 命令 |
|---|---|
| P0 立项与基线 | `template`、`validate-outline` |
| P1 素材归一化 | `validate-evidence` |
| P2 章节资料包 | `validate-dossier` |
| P3 内容计划 | `validate-plan` |
| P3.5 小节正文大纲 | —（人读产物，无自动校验） |
| P4 起草（两轮） | —（`丰富记录.md` 人读记录） |
| P5 确定性校验 | `check-depth`/`check-provenance`/`check-duplication`/`check-features`/`check-baseline`/`self-check` |
| P6 独立评审 | 人/独立代理 |
| P7 装配发布 | `assemble`/`register-chapter`/`check-chapter`/`report` |
