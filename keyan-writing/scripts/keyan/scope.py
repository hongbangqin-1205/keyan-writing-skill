"""scope 解析：支持 chapter_05_06 / 5.6 / 第五章第六节 / all 等写法。"""
import re

from .headings import cn_to_int
from .tree import iter_nodes, node_by_key, node_by_number

_CHINESE = re.compile(r"第\s*([0-9一二三四五六七八九十百零〇]+)\s*([章节条])")
_DOTTED = re.compile(r"^\d{1,2}(?:[.．]\d{1,2})*$")
_CHINESE_ONLY = re.compile(r"^[一二三四五六七八九十百零〇]{1,3}(?:[.．][一二三四五六七八九十百零〇]{1,3})*$")


def _to_numbers(token):
    text = (token or "").strip()
    if not text:
        return []
    if text.lower() in ("all", "*", "全部", "整篇", "全文"):
        return ["all"]
    if text.lower().startswith("chapter_"):
        return [_canonical_chapter_key(text)]
    numbers = []
    chinese_hits = _CHINESE.findall(text)
    if chinese_hits:
        numbers = [str(cn_to_int(value)) for value, _ in chinese_hits]
    else:
        cleaned = text.replace(" ", "")
        if _DOTTED.match(cleaned):
            numbers = cleaned.replace("．", ".").split(".")
        elif _CHINESE_ONLY.match(cleaned):
            numbers = [str(cn_to_int(piece)) for piece in re.split(r"[.．]", cleaned)]
    return [value for value in numbers if value and value != "None"]


def _canonical_chapter_key(token):
    parts = re.split(r"[_\-]", token.strip())
    values = [part for part in parts if part and part.lower() != "chapter"]
    if not values:
        return "all"
    try:
        first = int(values[0])
    except ValueError:
        return token
    key = "chapter_%02d" % first
    for value in values[1:]:
        key += "_%02d" % int(value)
    return key


def parse_scope(token, tree):
    """把 scope 写法解析成目标节点 key 列表（按文档顺序，父节点覆盖子节点）。"""
    tokens = [piece for piece in re.split(r"[,，;；\s]+", token or "") if piece]
    if not tokens:
        tokens = ["all"]
    keys, labels, unresolved = [], [], []
    for piece in tokens:
        if piece.lower().startswith("chapter_"):
            key = _canonical_chapter_key(piece)
            if node_by_key(tree, key) is None:
                key = _fallback_key(tree, key)
            if node_by_key(tree, key) is None:
                unresolved.append(piece)
                continue
            keys.append(key)
            labels.append(key.replace("chapter_", "").lstrip("0") or key)
            continue
        numbers = _to_numbers(piece)
        if not numbers:
            unresolved.append(piece)
            continue
        if numbers == ["all"]:
            keys.extend(node["key"] for node in tree["chapters"])
            labels.append("all")
            continue
        key = "chapter_%02d" % int(numbers[0])
        if len(numbers) > 1:
            key += "".join("_%02d" % int(value) for value in numbers[1:])
        if node_by_key(tree, key) is None:
            key = _fallback_key(tree, key)
        if node_by_key(tree, key) is None:
            unresolved.append(piece)
            continue
        keys.append(key)
        labels.append(".".join(numbers))
    ordered = _order_and_dedupe(tree, keys)
    return {"keys": ordered, "labels": labels, "unresolved": unresolved,
            "label": ",".join(labels) or ",".join(tokens)}


def _fallback_key(tree, key):
    """节点不存在时逐级退让到最近的已存在祖先（用户编号与模板漂移时不至于空跑）。"""
    parts = key.split("_")
    while len(parts) > 1:
        parts = parts[:-1]
        candidate = "_".join(parts)
        if node_by_key(tree, candidate) is not None:
            return candidate
    return key


def _order_and_dedupe(tree, keys):
    wanted = set(keys)
    ordered = []
    for node in iter_nodes(tree["chapters"]):
        if node["key"] in wanted and not any(_is_ancestor(node, other) for other in wanted if other != node["key"]):
            ordered.append(node["key"])
    for key in keys:
        if key not in ordered and key in wanted:
            ordered.append(key)
    return ordered


def _is_ancestor(node, other_key):
    return other_key.startswith(node["key"] + "_")


def nodes_for_keys(tree, keys):
    result = []
    for key in keys:
        node = node_by_key(tree, key)
        if node is not None:
            result.append(node)
    return result


def node_or_number(tree, token):
    """按 key / 编号 / 标题名找一个节点（用于单节作业）。"""
    if not token:
        return None
    node = node_by_key(tree, token)
    if node:
        return node
    node = node_by_number(tree, token)
    if node:
        return node
    scope = parse_scope(token, tree)
    nodes = nodes_for_keys(tree, scope["keys"])
    return nodes[0] if nodes else None