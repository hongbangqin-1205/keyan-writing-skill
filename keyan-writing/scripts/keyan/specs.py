"""章节规范（references/chapter-writing）解析：必写要素、逐项篇幅、表格、完成标准、关键词。"""
import re
from pathlib import Path

from .headings import keywords_of, normalize_title, similarity

_ITEM_LINE = re.compile(r"^\s*(?:[-*]|\d{1,2}\s*[.、)）])\s+(.*)$")
_CHECKBOX = re.compile(r"^\s*[-*]\s*\[\s*\]\s*(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_QUOTED = re.compile(r"[「『“\"]([^「』“”\"]{2,30})[」』”\"]")
_CHAR_HINT = re.compile(r"(?:≥|>=|不少于|至少)?\s*(\d{2,6})\s*字")
_TABLE_INLINE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9]{2,20}表)\s*[*`]*\s*(?:[（(][^）)]{0,10}[）)])?\s*[:：]\s*([^\n]{2,100})")
_TABLE_MENTION = re.compile(r"[\u4e00-\u9fff]{2,16}表(?![A-Za-z\u4e00-\u9fff])")
_COLUMNS_AFTER = re.compile(r'列\s*[「『"“]?([\u4e00-\u9fffA-Za-z0-9/、]{4,120})[」』"”]?')
_GENERIC_TABLES = ("事实基线表", "明细表", "概览表", "一览表", "对照表", "替代表", "下表", "该表", "本表")
_TABLE_CELL = re.compile(r"^([\u4e00-\u9fffA-Za-z0-9]{2,20}表)\s*(?:[（(][^）)]{0,10}[）)])?$")
_SEPARATOR_CELL = re.compile(r"^:?-{2,}:?$")
_SECTION_TITLE = re.compile(r"^(\d{2})-(.+)\.md$", re.IGNORECASE)

_ELEMENT_SECTIONS = ("必写要素", "必写项", "要素", "结构", "子项", "写作要点", "内容要求",
                     "Dynamic structure", "Evidence and reuse", "Completion checks")
_ITEM_VERB_PREFIX = ("先", "再", "按", "用", "每", "如", "若", "当", "从", "把", "将", "需", "须",
                     "应", "可", "不", "要写", "不得", "必须", "应当", "写到", "写出")
_NEGATION_LINES = ("不得", "不能", "不写", "不要", "避免", "空话", "反模式", "禁止", "视为")
_TABLE_TRIM_PREFIX = ("附", "含", "并", "及", "和", "与", "或", "如", "见", "按", "为", "由", "以",
                      "在", "从", "对", "填", "报", "写", "列", "有")
_TABLE_BAD_PARTS = ("的", "及", "或", "和", "与", "是", "为", "并", "附", "如", "见", "含", "等",
                    "其", "该", "把", "将", "写", "列", "按")
_ITEM_HEADERS = ("#", "序号", "编号", "子项", "要素", "必写要素", "必写项", "必写内容", "内容项", "项目", "指标")
_DETAIL_HEADERS = ("写作内容", "内容", "篇幅", "要求", "说明", "指标值", "规范")

META_STOPWORDS = {
    "必写要素", "写作要点", "完成标准", "反模式", "正例", "典型表述", "通用要求", "关键规范",
    "写作提示", "章节通用纪律", "表格要求", "正文组织", "第二轮", "第一轮", "查漏补缺",
    "两轮写作要求", "写作流程", "小节与规范文件", "展开结构", "功能点证据", "深度契约",
    "核心机制", "说明", "示例", "要求", "依据", "注意事项", "使用规则", "模板", "结构",
    "内容", "目的", "成果", "禁止", "允许变化", "禁止变化", "检查维度", "关键提示",
    "写作纪律", "验收", "自检", "自查", "结论", "为什么", "验证方式", "证据形式", "硬规则",
    "本阶段", "本文件", "本文", "见前文", "如下", "写作单位", "章节结构", "表格", "图", "表",
}

_BAD_CHARS = ("**", "|", "http", "〔", "〕", "=>", "＝", "=")

_STYLE_PREFIXES = ("可用", "不得", "必须", "禁止", "建议", "尽量", "需要", "应该", "可以", "如", "若",
                   "例如", "示例", "参见", "见", "含", "配", "按", "以", "与", "及")
_STYLE_PARTS = ("列表", "有序", "无序", "风格", "形式", "字数", "篇幅", "口径", "表头", "列数", "行数")


def _good_keyword(word):
    word = (word or "").strip().strip("*`「」『』“”").strip()
    if not word or len(word) < 3 or len(word) > 24:
        return None
    if any(bad in word for bad in _BAD_CHARS):
        return None
    if "\n" in word or "\r" in word:
        return None
    if word in META_STOPWORDS:
        return None
    if re.search(r"[：:；;，,。！？!?（）()]", word):
        return None
    if re.fullmatch(r"[\d.\-]+", word):
        return None
    if re.fullmatch(r"[A-Za-z]+", word) and len(word) < 5:
        return None
    if word.startswith(_STYLE_PREFIXES) or any(part in word for part in _STYLE_PARTS):
        return None
    return word


class Specs:
    """references/chapter-writing 下的章节总纲与小节规范的只读索引。"""

    def __init__(self, skill_root):
        self.root = Path(skill_root)
        self.base = self.root / "references" / "chapter-writing"
        self.sections_dir = self.base / "sections"
        self.chapters = {}
        self._cache = {}
        self._load()

    def _load(self):
        if not self.base.is_dir():
            return
        for path in sorted(self.base.glob("chapter-*.md")):
            match = re.match(r"chapter-(\d{2})\.md$", path.name, re.IGNORECASE)
            if not match:
                continue
            number = int(match.group(1))
            entry = {"chapter": number, "title": path.stem, "path": path,
                     "text": path.read_text(encoding="utf-8", errors="replace"), "sections": []}
            chapter_sections = self.sections_dir / ("chapter-%02d" % number)
            if chapter_sections.is_dir():
                override_path = chapter_sections / "06-system-design.md"
                override_text = (override_path.read_text(encoding="utf-8", errors="replace")
                                 if override_path.exists() else None)
                for section_path in sorted(chapter_sections.glob("*.md")):
                    if section_path == override_path:
                        continue
                    name_match = _SECTION_TITLE.match(section_path.name)
                    title = name_match.group(2) if name_match else section_path.stem
                    order = int(name_match.group(1)) if name_match else 0
                    entry["sections"].append({
                        "title": title,
                        "norm_title": normalize_title(title),
                        "order": order,
                        "path": section_path,
                        "text": section_path.read_text(encoding="utf-8", errors="replace"),
                    })
                if override_text is not None:
                    for section in entry["sections"]:
                        if section["order"] == 6:
                            section["text"] = override_text
                            break
            self.chapters[number] = entry

    def chapter_numbers(self):
        return sorted(self.chapters)

    def chapter(self, number):
        try:
            return self.chapters.get(int(number))
        except (TypeError, ValueError):
            return None

    def spec_for_node(self, node):
        """按节点编号/标题匹配规范：章根 → 总纲；小节 → 同名或最相似小节规范。"""
        parts = str(node.get("number", "")).split(".")
        chapter = self.chapter(parts[0]) if parts and parts[0].isdigit() else None
        if not chapter:
            return None
        if len(parts) <= 1:
            spec = {"kind": "chapter", "chapter": chapter["chapter"], "title": chapter["title"],
                    "path": chapter["path"], "text": chapter["text"], "match_score": 1.0}
            return self._decorate(spec)
        # 小节规范既可能由自身标题命中，也可能由上级小节命中（深层节点如 5.13.1 建设目标
        # 应遵循 5.13 运行维护系统设计方案的规范）；上级标题按距离衰减。
        ancestors = [title for title in (node.get("path_titles") or [])[:-1] if title]
        targets = [(node.get("title", ""), 1.0, "本节点")]
        for depth, title in enumerate(reversed(ancestors)):
            targets.append((title, 0.85 ** (depth + 1), "上级" if depth == 0 else "上级的上级"))
        best, best_score, matched_by = None, 0.0, ""
        for section in chapter["sections"]:
            for title, weight, label in targets:
                if not title:
                    continue
                score = similarity(title, section["title"])
                if normalize_title(title) == section["norm_title"]:
                    score = 1.0
                score = round(score * weight, 4)
                if score > best_score:
                    best, best_score, matched_by = section, score, "%s《%s》" % (label, title)
        if best is None or best_score < 0.25:
            spec = {"kind": "chapter", "chapter": chapter["chapter"], "title": chapter["title"],
                    "path": chapter["path"], "text": chapter["text"],
                    "match_score": round(best_score, 4), "note": "未匹配到小节规范，回退章节总纲"}
            return self._decorate(spec)
        spec = {"kind": "section", "chapter": chapter["chapter"], "title": best["title"],
                "path": best["path"], "text": best["text"], "order": best["order"],
                "match_score": round(best_score, 4), "matched_by": matched_by}
        return self._decorate(spec)

    def _decorate(self, spec):
        key = str(spec["path"])
        if key not in self._cache:
            self._cache[key] = analyze_spec(spec["text"])
        spec = dict(spec)
        spec["requirements"] = self._cache[key]
        return spec


def _split_cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_row(cells):
    return bool(cells) and all(not cell or _SEPARATOR_CELL.match(cell) for cell in cells)


def _columns_of(cell):
    if not cell or "字" in cell[:2]:
        return []
    parts = [part.strip() for part in re.split(r"[/、|]", cell) if part.strip()]
    return parts if len(parts) >= 2 else []


def _fenced_flags(lines):
    """标记 ``` 围栏内的行（示例/模板，不作为规范要素与关键词来源）。"""
    flags, inside = [], False
    for line in lines:
        if line.strip().startswith("```"):
            flags.append(True)
            inside = not inside
            continue
        flags.append(inside)
    return flags


def _table_name(name):
    """把散文里提到的表名洗成规范表名；非表名返回 None。"""
    name = (name or "").strip()
    while name and name[0] in _TABLE_TRIM_PREFIX:
        name = name[1:]
    if not (2 <= len(name) <= 12) or not name.endswith("表"):
        return None
    if any(part in name for part in _TABLE_BAD_PARTS):
        return None
    return name


def analyze_spec(text):
    """从规范正文解析：必写要素（含逐项篇幅）、表格、完成标准、关键词。"""
    lines = text.splitlines()
    fenced = _fenced_flags(lines)
    items, checklist, tables, char_hints, item_depth = [], [], [], [], {}
    section = ""
    table_rows = []

    def flush_table():
        nonlocal table_rows
        rows = [row for row in table_rows if not _is_separator_row(row)]
        table_rows = []
        if len(rows) < 2:
            return
        header = rows[0]
        item_header = any(cell.strip() in _ITEM_HEADERS for cell in header[:2])
        detail_index = next((index for index, cell in enumerate(header)
                             if any(key in cell for key in _DETAIL_HEADERS)), None)
        if item_header:
            for row in rows[1:]:
                cells = [cell for cell in row if cell]
                if not cells:
                    continue
                label = next((cell for cell in row[:3] if cell and not cell.isdigit()), "")
                if not (2 <= len(label) <= 30):
                    continue
                hint = 0
                for value in _CHAR_HINT.findall(" ".join(row)):
                    hint = max(hint, int(value))
                detail = row[detail_index] if detail_index is not None and detail_index < len(row) else ""
                items.append({"section": section, "text": label})
                if hint:
                    item_depth[label] = hint
                    char_hints.append(hint)
                if detail and detail != label:
                    items[-1]["detail"] = detail
            return
        for row in rows:
            for index, cell in enumerate(row):
                if not _TABLE_CELL.match(cell) or not _table_name(cell):
                    continue
                columns = []
                for candidate in row[index + 1:]:
                    columns = _columns_of(candidate)
                    if columns:
                        break
                tables.append({"name": _table_name(cell), "columns": columns})
                break

    for index, raw in enumerate(lines):
        if fenced[index]:
            continue
        line = raw.strip()
        if line.startswith("|"):
            table_rows.append(_split_cells(line))
            continue
        if table_rows:
            flush_table()
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            continue
        if not line:
            continue
        for value in _CHAR_HINT.findall(line):
            char_hints.append(int(value))
        checkbox = _CHECKBOX.match(line)
        if checkbox:
            checklist.append(_clean(checkbox.group(1)))
            continue
        inline = _TABLE_INLINE.search(line)
        if inline:
            columns = [col.strip() for col in re.split(r"[/、|]", inline.group(2)) if col.strip()]
            tables.append({"name": inline.group(1).strip(), "columns": columns})
        item = _ITEM_LINE.match(line)
        if item and any(key in section for key in _ELEMENT_SECTIONS):
            cleaned = _bullet_item(item.group(1))
            if cleaned:
                items.append({"section": section, "text": cleaned})
    if table_rows:
        flush_table()

    known = {table["name"] for table in tables}
    last_name = None
    for index, raw in enumerate(lines):
        if fenced[index]:
            continue
        line = raw.strip()
        if not line:
            continue
        for match in _TABLE_INLINE.finditer(line):
            name = _table_name(match.group(1))
            if not name:
                continue
            columns = [col.strip() for col in re.split(r"[/、|]", match.group(2)) if col.strip()]
            if not any(table["name"] == name for table in tables):
                tables.append({"name": name, "columns": columns})
            last_name = name
        mentions = [name for name in (_table_name(hit) for hit in _TABLE_MENTION.findall(line))
                    if name and not any(generic in name for generic in _GENERIC_TABLES)]
        for name in mentions:
            if name not in known:
                known.add(name)
                tables.append({"name": name, "columns": []})
            last_name = name
        columns_match = _COLUMNS_AFTER.search(line)
        if columns_match and last_name:
            columns = [col.strip() for col in re.split(r"[/、]", columns_match.group(1)) if col.strip()]
            if len(columns) >= 2:
                for table in tables:
                    if table["name"] == last_name and not table["columns"]:
                        table["columns"] = columns
                        break

    keywords = []
    for index, raw in enumerate(lines):
        if fenced[index]:
            continue
        stripped = raw.strip()
        if stripped.startswith("#"):
            heading = re.sub(r"[（(][^）)]{0,20}[）)]", "", stripped.lstrip("#").strip()).replace(" ", "")
            keywords.append(heading)
            continue
        if not stripped or any(marker in stripped for marker in _NEGATION_LINES):
            continue
        keywords.extend(_BOLD.findall(stripped))
        keywords.extend(_QUOTED.findall(stripped))
    keywords.extend(_strip_qualifier(item["text"]) for item in items)
    keywords.extend(table["name"] for table in tables)
    keywords.extend(name for name in (_table_name(hit) for hit in
                                     re.findall(r"[\u4e00-\u9fff]{2,16}表(?![A-Za-z\u4e00-\u9fff])", text))
                    if name)
    keywords = [cleaned for cleaned in (_good_keyword(word) for word in keywords) if cleaned]

    unique_items, seen = [], set()
    for item in items:
        key = item["text"]
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(item)
    unique_tables, seen_tables = [], set()
    for table in tables:
        if table["name"] in seen_tables:
            continue
        seen_tables.add(table["name"])
        unique_tables.append(table)

    min_chars = max(char_hints) if char_hints else 0
    return {
        "min_chars": min_chars,
        "char_hints": sorted(set(char_hints), reverse=True)[:12],
        "item_depth": item_depth,
        "required_items": unique_items,
        "required_tables": unique_tables,
        "checklist": checklist,
        "keywords": _dedupe(keywords),
    }


def _clean(text):
    text = _BOLD.sub(r"\1", text or "")
    text = re.sub(r"[（(]([^）)]{0,40})[）)]", "", text)
    text = re.sub(r"^[❌✅✓✗\-\s]+", "", text)
    text = text.split("—")[0]
    return text.strip(" ;；。")


def _bullet_item(raw):
    """从条目行提取必写要素名：'标签：说明' 取标签；短名词短语取整句；散文句丢弃。"""
    text = _BOLD.sub(r"\1", raw or "")
    text = re.sub(r"^[❌✅✓✗\-\s]+", "", text).strip()
    if not text:
        return None
    head = re.split(r"[:：—–]", text, 1)[0]
    head = re.sub(r"[（(][^）)]*[）)]", "", head).strip(" ;；。、,")
    prose_head = re.search(r"""[。！？；，,、/“”"'\+ ]""", head)
    if (2 <= len(head) <= 20 and not prose_head and "是" not in head
            and not head.endswith(("的", "了", "写法", "读法", "叫法"))
            and not head.startswith(_ITEM_VERB_PREFIX)):
        return head
    tail = text.strip(" ;；。")
    if not (2 <= len(tail) <= 24) or re.search(r"[。！？；，,、/]", tail):
        return None
    if tail.startswith(_ITEM_VERB_PREFIX):
        return None
    return tail


def _strip_qualifier(text):
    text = re.split(r"[—\-:：]", text or "")[0]
    return _clean(text)[:24]


def _dedupe(values):
    seen, result = set(), []
    for value in values:
        value = (value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def coverage(text, keywords, *, limit=40):
    """关键词在文本中的覆盖率（最多统计 limit 个关键词，长词优先）。"""
    if not text:
        return {"score": 0.0, "hit": [], "miss": sorted(set(keywords), key=len, reverse=True)[:limit]}
    ordered = sorted({word for word in keywords if word}, key=len, reverse=True)[:limit]
    hit = [word for word in ordered if word in text]
    miss = [word for word in ordered if word not in hit]
    score = round(len(hit) / len(ordered), 4) if ordered else 0.0
    return {"score": score, "hit": hit, "miss": miss}


def spec_requirements(spec):
    """兼容两种形态：原始 spec（含 requirements）与 spec_payload（平铺字段）。"""
    if not spec:
        return {}
    requirements = spec.get("requirements")
    if isinstance(requirements, dict):
        return requirements
    return {key: spec.get(key) for key in ("min_chars", "char_hints", "item_depth",
                                           "required_items", "required_tables", "checklist",
                                           "keywords") if key in spec}


def spec_keywords(spec, extra=()):
    keywords = list(spec_requirements(spec).get("keywords", []))
    keywords.extend(extra)
    return _dedupe(keywords)


def _match_item(title, items):
    """节点标题命中某必写要素时返回该要素（完全相同优先，其次高相似）。"""
    norm = normalize_title(title)
    if not norm:
        return None
    for item in items:
        if normalize_title(item["text"]) == norm:
            return item
    best, score = None, 0.0
    for item in items:
        current = similarity(title, item["text"])
        if current > score:
            best, score = item, current
    return best if score >= 0.8 else None


def node_requirements(node, spec):
    """把规范收窄到本节点：节点标题命中某必写要素时，只保留该要素的篇幅与表格要求。

    例：1.1.2 建设目标 只对「建设目标」负责（500 字），不再继承 1.1 整节的
    投资构成表/绩效表等兄弟要素要求。
    """
    requirements = spec_requirements(spec)
    items = requirements.get("required_items") or []
    if not items:
        return requirements
    match = _match_item(node.get("title", ""), items)
    if not match:
        return requirements
    narrowed = dict(requirements)
    narrowed["required_items"] = [match]
    detail = "%s %s" % (match.get("detail") or "", match.get("text") or "")
    narrowed["required_tables"] = [table for table in (requirements.get("required_tables") or [])
                                   if table["name"] in detail]
    depth = (requirements.get("item_depth") or {}).get(match["text"], 0)
    narrowed["min_chars"] = depth or 0
    narrowed["matched_item"] = match["text"]
    return narrowed


def outline_keywords(text, limit=60):
    return keywords_of(text, limit=limit)


def spec_payload(spec):
    """把 spec 变成 JSON 可序列化的载荷（Path → str）。"""
    if not spec:
        return {"kind": "none", "title": "", "path": ""}
    requirements = spec.get("requirements") or {}
    return {
        "kind": spec.get("kind"),
        "chapter": spec.get("chapter"),
        "title": spec.get("title"),
        "path": str(spec.get("path")) if spec.get("path") else "",
        "match_score": spec.get("match_score"),
        "matched_by": spec.get("matched_by"),
        "note": spec.get("note"),
        "min_chars": requirements.get("min_chars", 0),
        "char_hints": requirements.get("char_hints", []),
        "item_depth": requirements.get("item_depth", {}),
        "required_items": requirements.get("required_items", []),
        "required_tables": requirements.get("required_tables", []),
        "checklist": requirements.get("checklist", []),
        "keywords": requirements.get("keywords", []),
    }
