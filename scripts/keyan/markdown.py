"""blocks → Markdown（可做标题层级重挂，用于"同名直复"和"语义迁移"落盘）。"""

import re


def _escape_cell(text):
    return (text or "").replace("|", "\\|").replace("\n", " ")


def render_table(block):
    rows = block.get("rows") or []
    if not rows:
        return []
    width = max(len(row) for row in rows)
    lines = []
    numbered_list = (width == 1 and len(rows) >= 2 and
                     all(re.match(r"^\s*\d{1,3}\s*[.．、)）:]", row[0] or "")
                         for row in rows))
    if numbered_list:
        lines.append("| 内容 |")
        lines.append("|---|")
        for row in rows:
            lines.append("| %s |" % _escape_cell(row[0]))
        lines.append("")
        return lines
    header = rows[0] + [""] * (width - len(rows[0]))
    lines.append("| " + " | ".join(_escape_cell(cell) for cell in header) + " |")
    lines.append("|" + "---|" * width)
    for row in rows[1:]:
        padded = row + [""] * (width - len(row))
        lines.append("| " + " | ".join(_escape_cell(cell) for cell in padded) + " |")
    lines.append("")
    return lines


def blocks_to_markdown(blocks, *, heading_offset=None, target_level=None, asset_map=None,
                       include_captions=True, keep_styles=False):
    """blocks → markdown 文本。

    heading_offset: 所有标题层级整体平移量（None 表示不平移）。
    target_level:  若给出，则第一个标题被重挂到该层级，其余标题按相对层级顺延。
    asset_map:     {rid: 文件名}，用于图片引用。
    """
    lines = []
    base_level = None
    if target_level is not None:
        for block in blocks:
            if block["kind"] == "heading":
                base_level = block["level"]
                break
    for block in blocks:
        kind = block["kind"]
        if kind == "heading":
            level = block["level"]
            if base_level is not None:
                level = target_level + (level - base_level)
            elif heading_offset:
                level = level + heading_offset
            level = max(1, min(level, 9))
            lines.append("")
            lines.append("#" * level + " " + block["text"].strip())
            lines.append("")
        elif kind == "table":
            if lines and lines[-1] != "":
                lines.append("")
            lines.extend(render_table(block))
        elif kind == "image":
            name = (asset_map or {}).get(block.get("rid"), "missing-%s.png" % block.get("rid"))
            lines.append("![](assets/%s)" % name)
            lines.append("")
        elif kind == "caption":
            if include_captions:
                lines.append(block["text"])
        elif kind == "list":
            lines.append("- " + block["text"])
        else:
            text = block.get("text", "").strip()
            if text:
                lines.append(text)
    text = "\n".join(lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip() + "\n"


def blocks_to_plain_text(blocks):
    parts = []
    for block in blocks:
        if block["kind"] == "table":
            for row in block.get("rows", []):
                parts.append("\t".join(row))
        else:
            parts.append(block.get("text", ""))
    return "\n".join(part for part in parts if part)
