"""按当次建设方案派生 5.6 项目目录，不修改只读模板目录。"""
from copy import deepcopy

from .headings import normalize_title
from .jsonio import AppError
from .tree import iter_nodes, node_by_number


def source_domains(source_tree):
    candidates = []
    for node in iter_nodes(source_tree["chapters"]):
        if not node["children"] or node["depth"] > 2:
            continue
        title = normalize_title(node["title"])
        score = 2 if "系统设计" in title or "建设详细方案" in title else 0
        if "建设方案" in title or "建设内容" in title:
            score += 1
        if score:
            candidates.append({"number": node["number"], "title": node["title"],
                               "key": node["key"], "score": score,
                               "children": len(node["children"])})
    return sorted(candidates, key=lambda row: (-row["score"], -row["children"]))


def choose_source_domain(source_tree, token=None):
    if token:
        node = node_by_number(source_tree, token)
        if node is None or not node["children"]:
            raise AppError("建设方案域不存在或没有子节点：%s" % token, status="partial")
        return node
    ranked = source_domains(source_tree)
    if not ranked or (len(ranked) > 1 and ranked[0]["score"] == ranked[1]["score"]):
        raise AppError("建设方案系统域不明确：请查看 source 目录树并用 --from 指定", status="partial")
    return node_by_number(source_tree, ranked[0]["number"])


def derive_project_tree(template_tree, source_parent, systems):
    tree = deepcopy(template_tree)
    target = node_by_number(tree, "5.6")
    if target is None:
        raise AppError("模板缺少 5.6 系统设计方案", status="partial")
    selected = [node_by_number({"chapters": source_parent["children"]}, token) for token in systems]
    if not selected or any(node is None for node in selected):
        raise AppError("--systems 中有不存在的系统编号", status="partial")
    if len({node["key"] for node in selected}) != len(selected):
        raise AppError("--systems 不可重复选同一系统", status="partial")
    if any(node not in source_parent["children"] for node in selected):
        raise AppError("--systems 只能选择 --from 域的直接子节点", status="partial")
    positions = [source_parent["children"].index(node) for node in selected]
    if positions != sorted(positions):
        raise AppError("--systems 须按建设方案中的系统顺序排列", status="partial")
    anchors = {}

    def clone(source, parent, position):
        node = deepcopy(source)
        node["number"] = "%s.%d" % (parent["number"], position)
        node["key"] = "%s_%02d" % (parent["key"], position)
        node["level"] = parent["level"] + 1
        node["depth"] = parent["depth"] + 1
        node["path_titles"] = parent["path_titles"] + [node["title"]]
        node["children"] = [clone(child, node, index) for index, child in
                            enumerate(source["children"], 1)]
        node["children_count"] = len(node["children"])
        node["leaf"] = not node["children"]
        anchors[node["key"]] = {"source": source["key"], "mode": "copy",
                                "auto": True, "auto_rule": "本项目目录实例：来源节点已确认",
                                "note": "本项目目录实例", "source_title": source["title"],
                                "source_number": source["number"]}
        return node

    target["children"] = [clone(node, target, index) for index, node in enumerate(selected, 1)]
    target["children_count"] = len(target["children"])
    target["leaf"] = False
    tree["node_count"] = sum(1 for _ in iter_nodes(tree["chapters"]))
    tree["leaf_count"] = sum(1 for node in iter_nodes(tree["chapters"]) if node["leaf"])
    tree["max_depth"] = max(node["depth"] for node in iter_nodes(tree["chapters"]))
    return tree, anchors
