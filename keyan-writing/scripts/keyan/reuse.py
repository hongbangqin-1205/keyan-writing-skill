"""正文相关检索与复用：映射不出来的节点继续找料的三级阶梯。

同名直复（exact_direct_copy）与语义迁移（semantic_migrate）都不成立时，不再只丢一个
"推荐小标题"骨架，而是按下面的顺序继续找料：

1. ``title_migrate``   标题相关：词面明显相关、正文贴合本节规范 → 把候选整棵子树迁过来；
2. ``paragraph_reuse`` 正文相关：在建设方案正文里检索相关段落，命中处**原文复用**（零改写），
                       命中多段时由 agent 组织段落顺序、补过渡；
3. ``material_reuse``  用户另传的其他材料（调研报告、子系统方案…）里检索标题或正文；
4. ``grounded_write``  上面都没有 → 查知识库 / 联网后按规范撰写。

复用只允许排版（排序、合并、补过渡句），事实、数字、口径不得改写：
sidecar 逐段记录原文与 sha256，``check`` 复核。
"""
import hashlib
import math
import re

from .headings import bigrams, normalize_title, similarity
from .tree import iter_nodes

REUSE_MIN_PARAGRAPH_CHARS = 12
REUSE_MIN_TOTAL_CHARS = 12
REUSE_MAX_TOTAL_CHARS = 3600     # 单节点复用上限，避免把整章搬过来
REUSE_MAX_GAP = 2                # 段落序号间隔 ≤ 该值视为同一段群
REUSE_MIN_SCORE = 0.34           # 段落相关度下限
REUSE_PER_SECTION_LIMIT = 3      # 同一来源小节最多取几段，避免单节淹没
REUSE_TOP_K = 8                  # 单节点最多取几段
REUSE_TERM_MAX_CHARS = 12        # 检索用词长度上限（长串枚举词不具区分性）
REUSE_HEAD_FLOOR = 0.45          # 段落所属小节标题与目标标题的相关度下限
REUSE_WORD_FLOOR = 0.25          # 规范要素词覆盖率下限
REUSE_SHORT_TITLE_CHARS = 3      # 标题短于该值时，只有小节标题完全同名才复用
REUSE_CORE_MIN_CHARS = 4         # 标题核心词（长前缀）最短长度
REUSE_CORE_RATIO = 0.4           # 核心词须占标题长度的比例（防止"卫生健康"这种通用前缀串系统）
REUSE_SCOPED_MIN_SCORE = 0.20    # 素材范围内的段落相关度下限（范围本身已证明章节对应）
_PURE_INDEX_RE = re.compile(r"^[.\u2026\s]+$")
_TEXT_KINDS = ("para", "list")   # 正文块类型（docx 扫描把段落记作 para）
_TERM_SEP_RE = re.compile(r"[/、：:（）()]")
_TITLE_QUALIFIER_RE = re.compile(r"^(相关|主要|本项目)")
_LEGAL_TITLE_RE = re.compile(r"(法律法规|法律|法规)")
_LEGAL_BODY_RE = re.compile(r"国家法律|法律法规|《[^》]{2,40}(?:法|条例|办法|规定)》")
_NAMED_LAW_RE = re.compile(r"《[^》]{2,40}(?:法|条例|办法|规定)》|中华人民共和国[^，。；]{1,24}(?:法|条例)")
_STANDARD_RE = re.compile(r"GB/?T\s*\d{4,6}(?:[-—]\d{4})?|标准规范|行业标准")


def _sha256(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _norm_text(text):
    return re.sub(r"\s+", "", text or "")


def paragraph_records(blocks, tree):
    """建设方案正文段落 → 检索记录（带所属小节标题路径与块序号）。"""
    records = []
    seen = set()
    for node in iter_nodes(tree.get("chapters", [])):
        start = node.get("own_start")
        end = node.get("own_end")
        if start is None or end is None:
            continue
        for index in range(int(start) + 1, min(int(end), len(blocks) - 1) + 1):
            block = blocks[index]
            if block.get("kind") not in _TEXT_KINDS:
                continue
            text = (block.get("text") or "").strip()
            if len(text) < REUSE_MIN_PARAGRAPH_CHARS or _PURE_INDEX_RE.match(text):
                continue
            fingerprint = _norm_text(text)
            identity = (node["key"], fingerprint)
            if identity in seen:
                continue
            seen.add(identity)
            records.append({
                "key": node["key"], "number": node["number"], "title": node["title"],
                "path_titles": list(node.get("path_titles") or []), "order": index,
                "text": text, "chars": len(fingerprint), "sha256": _sha256(fingerprint),
            })
    return records


def query_terms(keywords, *, limit=8):
    """检索用词：丢掉枚举长串（"一级指标/二级指标/…"）与过短噪声词。"""
    words = set()
    for word in keywords or ():
        word = (word or "").strip()
        if len(word) < 2 or len(word) > REUSE_TERM_MAX_CHARS:
            continue
        if _TERM_SEP_RE.search(word):
            continue
        words.add(word)
    return sorted(words, key=lambda item: (-len(item), item))[:limit]


def title_cores(title, *, min_chars=REUSE_CORE_MIN_CHARS, ratio=REUSE_CORE_RATIO):
    """标题核心词：由长到短的标题前缀（"清廉医院建设管理平台" → … → 清廉医院）。

    前缀还须占到标题长度的一定比例，否则"卫生健康统计与决策支持系统"会退化成
    "卫生健康"这种通用前缀，把别的系统的正文也捞进来。短标题没有可用核心词，
    只能靠小节同名复用。
    """
    norm = normalize_title(title)
    floor = max(min_chars, int(math.ceil(ratio * len(norm))))
    if len(norm) <= floor:
        return []
    return [norm[:size] for size in range(len(norm) - 1, floor - 1, -1)]


def core_hit(record, node):
    """正文或所属小节标题里命中的最长标题核心词（没命中返回 None）。"""
    text_norm = _norm_text(record["text"])
    paths = [normalize_title(item) for item in record.get("path_titles") or []]
    for core in title_cores(node.get("title", "")):
        if core in text_norm or any(core in path for path in paths):
            return core
    return None


def subtree_keys(node):
    """节点子树内的全部 key（素材范围判定用）。"""
    return {item["key"] for item in iter_nodes([node])}


def paragraph_fit(record, node, keywords, *, scoped=False):
    """范围过滤后的段落召回：同名、范围内核心词、正文命中或标题与要素相关。

    正文直接命中允许来源标题不相似；这是待 agent 按正文语义复核的候选，
    不代表已满足规范或具备完整项目事实。归属与素材范围由路由层先行约束。
    """
    text = record["text"]
    title = node.get("title", "")
    title_norm = normalize_title(title)
    title_focus = _TITLE_QUALIFIER_RE.sub("", title_norm)
    text_norm = _norm_text(text)
    path_norms = [normalize_title(item) for item in record.get("path_titles") or []]
    exact_path = bool(title_norm) and title_norm in path_norms
    if exact_path:
        head = 1.0
    else:
        head = max((similarity(title, item) for item in (record.get("path_titles") or [])),
                   default=0.0)
    terms = query_terms(keywords)
    hit = [word for word in terms if word in text]
    word_score = len(hit) / len(terms) if terms else 0.0
    grams = bigrams(title)
    gram_hit = [gram for gram in grams if gram in _norm_text(text)]
    gram_score = len(gram_hit) / len(grams) if grams else 0.0
    long_title = len(title_norm) >= REUSE_SHORT_TITLE_CHARS
    title_in_text = bool(long_title and title_norm and title_norm in _norm_text(text))
    title_focus_in_text = bool(title_focus and len(title_focus) >= 4
                               and title_focus in _norm_text(text))
    legal_body = bool(_LEGAL_TITLE_RE.search(title)
                      and (_LEGAL_BODY_RE.search(text) or _NAMED_LAW_RE.search(text)
                           or _STANDARD_RE.search(text)))
    explicit_title = bool(title_norm and re.search(
        r"(?:^|[。；\n])\s*" + re.escape(title_norm) + r"\s*[:：]", text))
    core = core_hit(record, node)
    near_core_in_text = bool(core and len(core) >= math.ceil(len(title_norm) * 0.8)
                             and core in text_norm and head >= REUSE_HEAD_FLOOR)
    basis = None
    if exact_path:
        passes, basis = True, "小节同名"
    elif scoped and core and (core in _norm_text(text) or title_in_text
                              or title_focus_in_text or word_score >= REUSE_WORD_FLOOR):
        passes, basis = True, "素材范围内命中标题核心词「%s」" % core
    elif legal_body:
        passes, basis = True, "正文命中法律法规或规范性文件"
    elif (title_in_text or title_focus_in_text) and len(title_focus) >= 4:
        passes, basis = True, "正文直接命中目标标题核心词"
    elif near_core_in_text:
        passes, basis = True, "正文命中近似标题核心词"
    elif head < REUSE_HEAD_FLOOR or not long_title:
        passes = False
    else:
        passes = bool(title_in_text or word_score >= REUSE_WORD_FLOOR
                      or any(len(word) >= 4 for word in hit))
        basis = "小节标题相关" if passes else None
    score = round(0.30 * head + 0.25 * word_score + 0.15 * gram_score
                  + 0.20 * (1.0 if exact_path else 0.8 if core else 0.0)
                  + 0.10 * (1.0 if scoped else 0.0), 4)
    if passes and basis in ("正文直接命中目标标题核心词", "正文命中近似标题核心词",
                            "正文命中法律法规或规范性文件"):
        score = max(score, REUSE_MIN_SCORE)
    return {"score": score, "head": round(head, 4), "word": round(word_score, 4),
            "gram": round(gram_score, 4), "hit": hit, "exact_path": exact_path,
            "title_in_text": title_in_text, "title_focus_in_text": title_focus_in_text,
            "explicit_title": explicit_title, "legal_body": legal_body,
            "core": core, "in_scope": bool(scoped),
            "basis": basis, "passes": passes}


def score_paragraph(record, node, keywords):
    """段落与目标节点的相关度（保留旧接口：分数 + 命中的规范要素词）。"""
    fit = paragraph_fit(record, node, keywords)
    return fit["score"], fit["hit"]


def search_paragraphs(records, node, keywords, *, top_k=REUSE_TOP_K, min_score=None,
                      exclude_keys=(), exclude_orders=(), scoped=False):
    """段落级检索：返回命中的段落（按相关度排序，同小节限量）。"""
    if not records:
        return []
    if min_score is None:
        min_score = REUSE_SCOPED_MIN_SCORE if scoped else REUSE_MIN_SCORE
    excluded = set(exclude_keys or ())
    taken = set(exclude_orders or ())
    scored = []
    for record in records:
        if record["key"] in excluded or record["order"] in taken:
            continue
        fit = paragraph_fit(record, node, keywords, scoped=scoped)
        if not fit["passes"] or fit["score"] < min_score:
            continue
        scored.append({"record": record, "score": fit["score"], "hit": fit["hit"], "fit": fit})
    scored.sort(key=lambda item: (-item["score"], item["record"]["order"]))
    title_norm = normalize_title(node.get("title", ""))
    strong = [item for item in scored
              if item["fit"].get("explicit_title")
              or (item["fit"].get("title_focus_in_text")
                  and item["fit"].get("head", 0) >= REUSE_HEAD_FLOOR)
              or (item["fit"].get("core") and
                  len(item["fit"]["core"]) >= math.ceil(len(title_norm) * 0.8)
                  and item["fit"].get("head", 0) >= REUSE_HEAD_FLOOR
                  and item["fit"]["core"] in _norm_text(item["record"]["text"]))]
    named_laws = [item for item in scored
                  if item["fit"].get("legal_body")
                  and (_NAMED_LAW_RE.search(item["record"]["text"])
                       or _STANDARD_RE.search(item["record"]["text"]))]
    if named_laws:
        law_names = [item for item in named_laws
                     if "中华人民共和国" in item["record"]["text"]]
        if law_names:
            named_laws = [item for item in named_laws
                          if any(item["record"]["key"] == law["record"]["key"]
                                 and abs(item["record"]["order"] - law["record"]["order"]) <= 6
                                 for law in law_names)]
        def law_cluster(item):
            record = item["record"]
            return sum(1 for other in named_laws
                       if other["record"]["key"] == record["key"]
                       and abs(other["record"]["order"] - record["order"]) <= 3)
        named_laws.sort(key=lambda item: (-law_cluster(item), -item["score"],
                                          item["record"]["order"]))
        clustered_laws = [item for item in named_laws if law_cluster(item) >= 2]
        scored = clustered_laws or named_laws
    elif strong:
        scored = strong
    picked, per_section = [], {}
    section_limit = top_k if named_laws else REUSE_PER_SECTION_LIMIT
    seen_text = set()
    for item in scored:
        key = item["record"]["key"]
        fingerprint = _norm_text(item["record"]["text"])
        if fingerprint in seen_text or per_section.get(key, 0) >= section_limit:
            continue
        seen_text.add(fingerprint)
        per_section[key] = per_section.get(key, 0) + 1
        picked.append(item)
        if len(picked) >= top_k:
            break
    return picked


def group_runs(picked, *, max_gap=REUSE_MAX_GAP, max_chars=REUSE_MAX_TOTAL_CHARS):
    """把命中的段落按原文顺序并成段群（同小节、序号相邻、总量受限）。"""
    ordered = sorted(picked, key=lambda item: item["record"]["order"])
    runs, current, total = [], [], 0
    for item in ordered:
        record = item["record"]
        if total + record["chars"] > max_chars:
            continue
        if current and (record["key"] != current[-1]["record"]["key"]
                        or record["order"] - current[-1]["record"]["order"] > max_gap):
            runs.append(current)
            current = []
        current.append(item)
        total += record["chars"]
    if current:
        runs.append(current)
    return runs


def runs_chars(runs):
    return sum(item["record"]["chars"] for run in runs for item in run)


def reuse_refs(runs):
    """复用段落引用（带原文，便于 sidecar 留档与 check 逐段复核）。"""
    refs = []
    for run in runs:
        for item in run:
            record = item["record"]
            refs.append({"key": record["key"], "number": record["number"], "title": record["title"],
                         "order": record["order"], "chars": record["chars"],
                         "score": item["score"], "sha256": record["sha256"],
                         "text": record["text"]})
    return refs


def render_body(runs):
    """复用段落的正文（原文，零改写）。"""
    parts = []
    for run in runs:
        for item in run:
            parts.append(item["record"]["text"])
            parts.append("")
    return "\n".join(parts).strip() + "\n"


def build_reuse(node, keywords, records, *, source, top_k=REUSE_TOP_K, exclude_orders=(),
                scoped=False):
    """段落检索 → 段群；没找到料时返回 None。"""
    picked = search_paragraphs(records, node, keywords, top_k=top_k,
                               exclude_orders=exclude_orders, scoped=scoped)
    if not picked:
        return None
    runs = group_runs(picked)
    total = runs_chars(runs)
    if total < REUSE_MIN_TOTAL_CHARS:
        return None
    body = render_body(runs)
    return {"source": source, "runs": runs, "refs": reuse_refs(runs), "chars": total,
            "paragraphs": sum(len(run) for run in runs), "top_score": picked[0]["score"],
            "hits": picked[0]["hit"], "body": body, "scoped": scoped,
            "basis": picked[0]["fit"]["basis"]}


def paragraphs_of(runs):
    return [item["record"]["text"] for run in runs for item in run]


def verify_reuse(body, refs):
    """复核复用段落是否原文保留：返回被改写/丢失的段落。"""
    flat = _norm_text(body)
    missing = []
    for ref in refs or []:
        text = _norm_text(ref.get("text") or "")
        if not text:
            continue
        if text not in flat or _sha256(text) != ref.get("sha256"):
            missing.append(ref)
    return missing
