"""DOCX/文本 → 结构化 blocks（标题层级、正文、表格、图片、题注）。"""
import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

_HEADING_STYLE = re.compile(r"^\s*(?:Heading|标题)\s*([1-9]\d*)\s*$", re.IGNORECASE)
_CAPTION_STYLE = {"图", "表", "caption", "题注", "图注", "表注"}
_LIST_STYLE = re.compile(r"(list\s*paragraph|列表段落|列表文字|无间隔|项目符号)", re.IGNORECASE)
_BLIP = ".//" + qn("a:blip")
_EMBED = qn("r:embed")
_BR = qn("w:br")


def _text_of_paragraph(par):
    pieces = []
    for run in par.runs:
        text = run.text or ""
        if not text:
            continue
        if run._element.findall(_BR):
            text = text.replace("\v", "\n")
        if run.bold and text.strip():
            text = "**" + text.strip() + "**"
        pieces.append(text)
    if pieces:
        return "".join(pieces).strip()
    for node in par._p.iter():
        if node.tag == qn("w:t") and node.text:
            pieces.append(node.text)
    return "".join(pieces).strip()


def _style_name(par):
    try:
        return par.style.name or ""
    except Exception:
        return ""


def heading_level(par):
    name = _style_name(par)
    match = _HEADING_STYLE.match(name)
    if match:
        return int(match.group(1))
    if name.strip() in ("Title", "标题"):
        return 1
    pPr = par._p.pPr
    if pPr is not None:
        outline = pPr.find(qn("w:outlineLvl"))
        if outline is not None:
            value = outline.get(qn("w:val"))
            if value is not None and value.strip().isdigit():
                return int(value) + 1
    return 0


def _image_rids(par):
    rids = []
    for blip in par._p.findall(_BLIP):
        rid = blip.get(_EMBED)
        if rid:
            rids.append(rid)
    return rids


def _table_rows(table):
    rows = []
    for row in table.rows:
        values = []
        for cell in row.cells:
            text = " ".join(part.strip() for part in cell.text.split("\n") if part.strip())
            values.append(text)
        if any(values):
            rows.append(values)
    return rows


def iter_block_items(document):
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def read_document(path):
    """读取 .docx/.md/.txt，返回 {"blocks": [...], "stats": {...}}。"""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".md", ".markdown", ".txt"):
        return _read_text_file(path)
    if suffix != ".docx":
        raise ValueError("unsupported input type: %s" % path.suffix)
    document = Document(str(path))
    blocks = []
    for item in iter_block_items(document):
        if isinstance(item, Paragraph):
            level = heading_level(item)
            text = _text_of_paragraph(item)
            style = _style_name(item)
            rids = _image_rids(item)
            if level and text:
                blocks.append({"kind": "heading", "level": level, "text": text, "style": style})
                continue
            if rids:
                for rid in rids:
                    blocks.append({"kind": "image", "rid": rid, "text": text, "style": style})
                if text and style.strip().lower() not in _CAPTION_STYLE:
                    continue
            if not text:
                continue
            if style.strip().lower() in _CAPTION_STYLE or re.match(r"^\s*(图|表)\s*\d", text):
                blocks.append({"kind": "caption", "text": text, "style": style})
            elif _LIST_STYLE.search(style):
                blocks.append({"kind": "list", "text": text, "style": style})
            else:
                blocks.append({"kind": "para", "text": text, "style": style})
        else:
            rows = _table_rows(item)
            if rows:
                blocks.append({"kind": "table", "rows": rows, "n_rows": len(rows),
                               "n_cols": max(len(r) for r in rows)})
    for index, block in enumerate(blocks):
        block["index"] = index
    return {"blocks": blocks, "stats": _stats(blocks), "path": str(path), "name": path.name}


def _read_text_file(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = []
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r"^(#{1,9})\s+(.*)$", stripped)
        if match:
            blocks.append({"kind": "heading", "level": len(match.group(1)),
                           "text": match.group(2).strip(), "style": "markdown"})
        elif stripped:
            blocks.append({"kind": "para", "text": stripped, "style": "markdown"})
    for index, block in enumerate(blocks):
        block["index"] = index
    return {"blocks": blocks, "stats": _stats(blocks), "path": str(path), "name": path.name}


def _stats(blocks):
    counts = {}
    for block in blocks:
        counts[block["kind"]] = counts.get(block["kind"], 0) + 1
    chars = sum(len(b.get("text", "")) for b in blocks if b["kind"] != "table")
    chars += sum(len("".join(cell for row in b["rows"] for cell in row)) for b in blocks if b["kind"] == "table")
    return {"blocks": len(blocks), "chars": chars, "headings": counts.get("heading", 0),
            "tables": counts.get("table", 0), "images": counts.get("image", 0),
            "paragraphs": counts.get("para", 0)}


def extract_assets(path, rids, assets_dir):
    """把 docx 内嵌图片导出到 assets_dir，返回 {rid: 相对文件名}。"""
    document = Document(str(path))
    assets_dir = Path(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)
    mapping = {}
    wanted = set(rids)
    for rel_id, part in document.part.related_parts.items():
        if rel_id not in wanted:
            continue
        name = Path(str(part.partname)).name
        target = assets_dir / name
        counter = 1
        while target.exists():
            target = assets_dir / ("%s-%d%s" % (Path(name).stem, counter, Path(name).suffix))
            counter += 1
        target.write_bytes(part.blob)
        mapping[rel_id] = target.name
    return mapping