"""目录树构建：把 blocks 变成"到最小层级"的层级树（含字数/表格/图片统计）。"""
from .headings import looks_like_heading, normalize_title, similarity



def build_tree(doc):
    """由 read_document 的结果构建层级树。返回 tree dict。"""
    blocks = doc["blocks"]
    root = {"children": [], "own_start": None, "own_end": None}
    stack = [{"node": root, "level": 0}]
    for block in blocks:
        if block["kind"] == "heading":
            level = int(block["level"])
            title = block["text"].strip()
            inferred = not looks_like_heading(title)
            while len(stack) > 1 and stack[-1]["level"] >= level:
                stack.pop()
            node = {
                "title": title,
                "norm_title": normalize_title(title),
                "level": level,
                "style": block.get("style", ""),
                "inferred": inferred,
                "own_start": block["index"],
                "own_end": block["index"],
                "children": [],
                "doc_order": block["index"],
            }
            stack[-1]["node"]["children"].append(node)
            stack.append({"node": node, "level": level})
        else:
            current = stack[-1]["node"]
            if current is not root:
                current["own_end"] = block["index"]
    root_children = _prune_empty(root["children"])
    _finalize(root_children, blocks, depth=0, counter=[0])
    _assign_keys(root_children)
    tree = {
        "name": doc.get("name", ""),
        "path": doc.get("path", ""),
        "stats": doc.get("stats", {}),
        "max_depth": max((node["depth"] for node in iter_nodes(root_children)), default=0),
        "node_count": sum(1 for _ in iter_nodes(root_children)),
        "leaf_count": sum(1 for node in iter_nodes(root_children) if node["leaf"]),
        "chapters": root_children,
    }
    return tree


def _prune_empty(children):
    result = []
    for node in children:
        node["children"] = _prune_empty(node["children"])
        if not node["norm_title"]:
            result.extend(node["children"])
            continue
        result.append(node)
    return result


def _level_index_map(children):
    """把原始 outline 级别压平成 1..n 的连续层级。"""
    levels = sorted({node["level"] for node in iter_nodes(children)})
    return {level: index + 1 for index, level in enumerate(levels)}


def _finalize(children, blocks, depth, counter):
    level_map = _level_index_map(children)
    for node in children:
        counter[0] += 1
        node["depth"] = depth + 1
        node["outline_depth"] = level_map.get(node["level"], depth + 1)
        node["children"] = node["children"]
        _finalize(node["children"], blocks, depth + 1, counter)
        node["own_chars"] = _chars(blocks, node["own_start"], node["own_end"], heading=True)
        node["subtree_chars"] = node["own_chars"] + sum(child["subtree_chars"] for child in node["children"])
        node["tables"] = _count(blocks, node, "table")
        node["images"] = _count(blocks, node, "image")
        node["children_count"] = len(node["children"])
        node["leaf"] = not node["children"]


def _count(blocks, node, kind):
    total = 0
    if node["own_end"] > node["own_start"]:
        for block in blocks[node["own_start"] + 1: node["own_end"] + 1]:
            if block["kind"] == kind:
                total += 1
    for child in node["children"]:
        total += child["tables"] if kind == "table" else child["images"]
    return total


def _chars(blocks, start, end, heading=False):
    if end <= start:
        return 0
    total = 0
    slice_ = blocks[start + 1: end + 1] if heading else blocks[start:end]
    for block in slice_:
        if block["kind"] == "table":
            total += len("".join(cell for row in block["rows"] for cell in row))
        else:
            total += len(block.get("text", ""))
    return total


def _assign_keys(chapters):
    for index, chapter in enumerate(chapters, start=1):
        chapter["number"] = str(index)
        chapter["key"] = "chapter_%02d" % index
        chapter["path_titles"] = [chapter["title"]]
        _assign_child_keys(chapter)


def _assign_child_keys(node):
    for index, child in enumerate(node["children"], start=1):
        child["number"] = "%s.%d" % (node["number"], index)
        child["key"] = "%s_%02d" % (node["key"], index)
        child["path_titles"] = node["path_titles"] + [child["title"]]
        _assign_child_keys(child)


def iter_nodes(chapters):
    for node in chapters:
        yield node
        for sub in iter_nodes(node["children"]):
            yield sub


def flatten(tree):
    return list(iter_nodes(tree["chapters"]))


def node_by_key(tree, key):
    for node in iter_nodes(tree["chapters"]):
        if node["key"] == key:
            return node
    return None


def node_by_number(tree, number):
    for node in iter_nodes(tree["chapters"]):
        if node["number"] == number:
            return node
    return None


def find_nodes(tree, title, *, exact=True, threshold=0.34):
    """按标题查找节点：exact=归一化同名；否则按相似度排序返回候选。"""
    scored = []
    for node in iter_nodes(tree["chapters"]):
        if exact:
            if node["norm_title"] and node["norm_title"] == normalize_title(title):
                scored.append((1.0, node))
        else:
            score = similarity(title, node["title"])
            if score >= threshold:
                scored.append((score, node))
    scored.sort(key=lambda item: (-item[0], item[1]["doc_order"]))
    return scored


def subtree_blocks(blocks, node):
    """返回节点子树覆盖的 blocks（含子节点）。"""
    start = node["own_start"]
    end = _subtree_end(blocks, node)
    return blocks[start:end + 1]


def _subtree_end(blocks, node):
    end = node["own_end"]
    for child in node["children"]:
        end = max(end, _subtree_end(blocks, child))
    return end


def subtree_text(blocks, node, *, limit=None):
    parts = []
    for block in subtree_blocks(blocks, node):
        if block["kind"] == "table":
            parts.append("".join(cell for row in block["rows"] for cell in row))
        else:
            parts.append(block.get("text", ""))
        if limit and sum(len(p) for p in parts) > limit:
            break
    text = "\n".join(part for part in parts if part)
    return text[:limit] if limit else text


def render_tree_markdown(tree, *, max_depth=None, with_stats=True, title=None):
    lines = []
    lines.append("# %s 目录树（到最小层级）" % (title or tree.get("name") or "文档"))
    lines.append("")
    lines.append("统计：章节 %d｜节点 %d｜叶子 %d｜最大层级 %d｜表格 %d｜图片 %d｜字数 %d" % (
        len(tree["chapters"]), tree["node_count"], tree["leaf_count"], tree["max_depth"],
        tree["stats"].get("tables", 0), tree["stats"].get("images", 0), tree["stats"].get("chars", 0)))
    lines.append("")
    for chapter in tree["chapters"]:
        _render_node(chapter, 0, lines, max_depth, with_stats)
    return "\n".join(lines) + "\n"


def _render_node(node, indent, lines, max_depth, with_stats):
    if max_depth is not None and node["depth"] > max_depth:
        return
    suffix = ""
    if with_stats:
        suffix = "  `[%s|%d字|表%d|图%d|子%d]`" % (
            node["key"], node["subtree_chars"], node["tables"], node["images"], node["children_count"])
    lines.append("%s- %s %s%s" % ("  " * indent, node["number"], node["title"], suffix))
    for child in node["children"]:
        _render_node(child, indent + 1, lines, max_depth, with_stats)


def render_leaf_index_markdown(tree, *, limit=None):
    lines = ["# 叶子层清单（最小层级）", "",
             "| 章 | 节点 | 层级 | 标题 | 字数 | 表格 | 图片 |", "|---|---|---|---|---|---|---|"]
    count = 0
    for node in iter_nodes(tree["chapters"]):
        if not node["leaf"]:
            continue
        count += 1
        if limit and count > limit:
            break
        lines.append("| %s | %s | %d | %s | %d | %d | %d |" % (
            node["number"].split(".")[0], node["key"], node["depth"], node["title"].replace("|", "/"),
            node["subtree_chars"], node["tables"], node["images"]))
    return "\n".join(lines) + "\n"


def tree_to_dict(tree):
    def convert(node):
        return {
            "key": node["key"], "number": node["number"], "level": node["level"],
            "depth": node["depth"], "title": node["title"], "norm_title": node["norm_title"],
            "style": node["style"], "leaf": node["leaf"], "own_chars": node["own_chars"],
            "subtree_chars": node["subtree_chars"], "tables": node["tables"], "images": node["images"],
            "children_count": node["children_count"], "doc_order": node["doc_order"],
            "own_start": node["own_start"], "own_end": node["own_end"],
            "path_titles": node["path_titles"],
            "children": [convert(child) for child in node["children"]],
        }
    return {
        "name": tree["name"], "path": tree["path"], "stats": tree["stats"],
        "max_depth": tree["max_depth"], "node_count": tree["node_count"],
        "leaf_count": tree["leaf_count"], "chapters": [convert(node) for node in tree["chapters"]],
    }


def tree_from_dict(payload):
    """把 tree_to_dict 的结果还原为可遍历（children/number/key/leaf 齐备）的树。"""
    def convert(node):
        copy = dict(node)
        copy["children"] = [convert(child) for child in node.get("children", [])]
        return copy
    return {
        "name": payload.get("name", ""), "path": payload.get("path", ""),
        "stats": payload.get("stats", {}), "max_depth": payload.get("max_depth", 0),
        "node_count": payload.get("node_count", 0), "leaf_count": payload.get("leaf_count", 0),
        "chapters": [convert(node) for node in payload.get("chapters", [])],
    }