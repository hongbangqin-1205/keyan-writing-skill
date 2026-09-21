"""建设方案标题索引与匹配：同名直复候选 + 语义候选 + 规范匹配打分。"""
from .headings import (bigrams, candidate_accepted, candidate_similarity, normalize_title,
                       similarity)
from .tree import iter_nodes, node_by_key, subtree_text


def walk_with_parent(nodes, parent=None):
    """遍历目录树并带上父节点，用于记录父级 key/标题。"""
    for node in nodes:
        yield node, parent
        yield from walk_with_parent(node.get("children") or [], node)


def in_scope(entry, scope_key):
    """候选是否落在素材范围（scope 节点自身或其子孙）内。"""
    if not scope_key:
        return False
    return entry.get("key") == scope_key or scope_key in (entry.get("path_keys") or ())


class SourceIndex:
    """建设方案（或任一来源文件）目录树的检索索引。"""

    def __init__(self, tree, blocks):
        self.tree = tree
        self.blocks = blocks
        self.entries = []
        self.by_norm = {}
        self.by_key = {}
        self._text_cache = {}
        self._parent_of = {}
        for node, parent in walk_with_parent(tree.get("chapters", [])):
            entry = {
                "key": node["key"], "number": node["number"], "title": node["title"],
                "norm_title": node["norm_title"], "level": node["level"], "depth": node["depth"],
                "own_chars": node.get("own_chars", 0), "subtree_chars": node.get("subtree_chars", 0),
                "tables": node.get("tables", 0), "images": node.get("images", 0),
                "children_count": node.get("children_count", 0), "leaf": node.get("leaf", True),
                "doc_order": node.get("doc_order", 0), "path_titles": list(node.get("path_titles", [])),
                "parent_key": parent["key"] if parent else None,
                "parent_title": parent["title"] if parent else "",
                "path_keys": [],
            }
            self._parent_of[entry["key"]] = entry["parent_key"]
            self.entries.append(entry)
            self.by_key[entry["key"]] = entry
            if entry["norm_title"]:
                self.by_norm.setdefault(entry["norm_title"], []).append(entry)
        for entry in self.entries:
            chain, cursor = [], entry["parent_key"]
            while cursor:
                chain.append(cursor)
                cursor = self._parent_of.get(cursor)
            entry["path_keys"] = list(reversed(chain)) + [entry["key"]]
        self._bigrams = {entry["key"]: bigrams(entry["norm_title"]) for entry in self.entries}
        self._gram_index = {}
        for entry in self.entries:
            for gram in self._bigrams[entry["key"]]:
                self._gram_index.setdefault(gram, []).append(entry)

    # ---------------------------------------------------------------- 同名
    def exact_entries(self, title):
        return list(self.by_norm.get(normalize_title(title), []))

    def resolve_exact(self, target_node, *, min_chars=40):
        """同名候选 → 上下文兼容性排序。返回 (best, scored_candidates)。"""
        candidates = self.exact_entries(target_node.get("title", ""))
        if target_node.get("norm_title"):
            candidates = [entry for entry in candidates
                          if entry["norm_title"] == target_node["norm_title"]] or candidates
        scored = []
        for entry in candidates:
            context = self.context_score(target_node, entry)
            same_chapter = entry["number"].split(".")[0] == target_node["number"].split(".")[0]
            substance = min(entry["subtree_chars"], 40000) / 40000.0
            copyable = entry["subtree_chars"] >= min_chars or entry["children_count"] > 0
            score = round(2.0 * context + (1.0 if same_chapter else 0.0) + substance, 4)
            scored.append({"entry": entry, "context_score": context, "same_chapter": same_chapter,
                           "copyable": copyable, "score": score})
        scored.sort(key=lambda item: (-item["score"], item["entry"]["doc_order"]))
        copyable = [item for item in scored if item["copyable"]]
        best = copyable[0] if copyable else None
        return best, scored

    def context_score(self, target_node, entry):
        """上下文兼容度：父级标题相似度 + 祖先路径最相近一对 + 完全相同祖先覆盖率。

        不以层级位置比较——建设方案与可研模板的分层深度常常不同，同名标题可能落在
        不同深度；真正说明"是同一处内容"的是它的上级标题。父标题用相似度而不是严格
        相等，这样"运行维护系统设计"与"运行维护系统设计方案"这类近义上级也能命中。
        """
        target_ancestors = [normalize_title(title) for title in target_node.get("path_titles", [])[:-1]]
        entry_ancestors = [normalize_title(title) for title in entry["path_titles"][:-1]]
        target_ancestors = [title for title in target_ancestors if title]
        entry_ancestors = [title for title in entry_ancestors if title]
        if not target_ancestors or not entry_ancestors:
            return 0.0
        parent_sim = similarity(target_ancestors[-1], entry_ancestors[-1])
        if target_ancestors[-1] == entry_ancestors[-1]:
            parent_sim = 1.0
        best_pair = max((similarity(left, right) for left in target_ancestors
                         for right in entry_ancestors), default=0.0)
        overlap = len(set(target_ancestors) & set(entry_ancestors)) / len(set(target_ancestors))
        return round(0.5 * parent_sim + 0.3 * best_pair + 0.2 * overlap, 4)

    # ---------------------------------------------------------------- 语义
    def similar_entries(self, title, *, k=12, min_chars=200, min_score=0.2, recall=400):
        """语义候选：先用 bigram 倒排召回，再算相似度（避免全量 O(N×M) 扫描）。"""
        title_norm = normalize_title(title)
        if not title_norm:
            return []
        pool, seen = [], set()
        for gram in sorted(bigrams(title_norm), key=lambda item: -len(self._gram_index.get(item, ()))):
            for entry in self._gram_index.get(gram, ()):
                if entry["key"] in seen:
                    continue
                seen.add(entry["key"])
                pool.append(entry)
                if len(pool) >= recall:
                    break
            if len(pool) >= recall:
                break
        scored = []
        for entry in pool:
            if not entry["norm_title"] or entry["norm_title"] == title_norm:
                continue
            if entry["subtree_chars"] < min_chars and entry["children_count"] == 0:
                continue
            effective, head_ok, synonym = candidate_similarity(title_norm, entry["norm_title"])
            if not candidate_accepted(effective, head_ok, synonym):
                continue
            if effective < min_score and not synonym:
                continue
            scored.append((effective, entry))
        scored.sort(key=lambda item: (-item[0], item[1]["doc_order"]))
        return scored[:k]

    # ---------------------------------------------------------------- 正文
    def entry_text(self, entry, *, limit=120000, target_node=None):
        key = (entry["key"], limit)
        if key in self._text_cache:
            return self._text_cache[key]
        node = node_by_key(self.tree, entry["key"])
        text = subtree_text(self.blocks, node, limit=limit) if node else ""
        self._text_cache[key] = text
        return text

    def text_of_key(self, key, *, limit=120000):
        entry = self.by_key.get(key)
        return self.entry_text(entry, limit=limit) if entry else ""

    def spec_fit(self, entry, keywords, *, limit=30, text_limit=120000):
        """按章节规范的必写要素关键词，衡量候选子树正文的贴合度。"""
        text = self.entry_text(entry, limit=text_limit)
        ordered = sorted({word for word in keywords if word}, key=len, reverse=True)[:limit]
        if not ordered:
            return {"score": 0.0, "hit": [], "miss": [], "chars": len(text)}
        hit = [word for word in ordered if word in text]
        miss = [word for word in ordered if word not in hit]
        return {"score": round(len(hit) / len(ordered), 4), "hit": hit, "miss": miss, "chars": len(text)}