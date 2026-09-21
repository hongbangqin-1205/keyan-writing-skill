"""标题归一化、相似度与关键词工具（纯逻辑，零依赖）。"""
import re
import unicodedata

CN_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}
CN_UNITS = {"十": 10, "百": 100, "千": 1000}

_MD_MARKS = re.compile(r"[#*`_>]+")
_LEAD_CHAPTER = re.compile(r"^第\s*[0-9一二三四五六七八九十百零〇]+\s*[章篇部分]")
_LEAD_SECTION = re.compile(r"^第\s*[0-9一二三四五六七八九十百零〇]+\s*[节条]")
_LEAD_CN_ITEM = re.compile(r"^[（(]?\s*[一二三四五六七八九十百零〇]{1,3}\s*[）)、.．:：]")
_LEAD_NUM_ITEM = re.compile(r"^[（(]?\s*\d{1,3}(?:\s*[.．]\s*\d{1,3})*\s*[）)、.．:：]?")
_LEAD_ALPHA_ITEM = re.compile(r"^[（(]?\s*[a-zA-Z]\s*[）)、.．:：]")
_TRAIL_PAGE = re.compile(r"(?<=[\u4e00-\u9fff）》】\)\)])\s*\d{1,4}\s*$")
_LEVEL_MARK = re.compile(r"[（(]\s*(?:[hH]\s*\d{1,2}|[一二三四五六七八九十]{1,3}|\d{1,3})\s*[）)]")
_PUNCT = re.compile(r"[\s\u3000，。；：、（）()〔〕【】《》〈〉“”‘’\"'·,.;:!?\-—－_/\\|~+*=<>&%$@\[\]{}]+")

# 语义近似但字面不同的标题族（用于同名之外的第二层召回）
SYNONYM_GROUPS = [
    {"总体架构", "总体设计", "总体框架", "总体方案", "系统总体架构"},
    {"业务架构", "业务设计", "业务框架", "业务流程设计"},
    {"数据架构", "数据设计", "数据体系", "数据资源规划"},
    {"网络拓扑", "网络架构", "网络设计", "网络系统设计方案", "网络系统设计"},
    {"技术路线", "技术方案", "技术选型", "技术架构"},
    {"系统设计方案", "系统设计", "应用系统设计", "系统功能设计"},
    {"终端系统及接口设计", "终端设计", "接口设计", "终端系统设计"},
    {"安全系统设计方案", "安全设计", "安全体系", "安全保障体系", "安全体系建设"},
    {"信息资源共享", "资源共享", "数据共享", "信息共享", "共享交换"},
    {"备份系统设计方案", "备份设计", "容灾备份", "备份与容灾"},
    {"部署方案", "系统部署", "部署设计", "部署架构"},
    {"运行维护系统设计方案", "运维方案", "运维设计", "运行维护方案"},
    {"建设管理方案", "建设管理", "项目管理方案"},
    {"运营模式选择", "运营模式", "运营方案"},
    {"运营组织方案", "运营组织", "组织方案", "组织机构"},
    {"安全保障方案", "安全保障", "安全管理方案"},
    {"绩效管理方案", "绩效管理", "绩效考核方案"},
    {"投资估算", "投资估算与资金筹措", "投资测算", "投资预算"},
    {"资金来源与落实情况", "资金来源", "资金筹措"},
    {"资金使用计划", "资金使用", "用款计划"},
    {"财务分析", "财务评价", "经济效益分析"},
    {"经济影响分析", "经济影响", "经济效果分析"},
    {"社会影响分析", "社会影响", "社会效益分析"},
    {"生态环境影响分析", "环境影响分析", "生态影响"},
    {"资源和能源利用效果分析", "资源利用分析", "能源利用分析"},
    {"碳达峰碳中和分析", "双碳分析", "碳达峰碳中和"},
    {"风险识别与评价", "风险识别", "风险分析", "风险评价"},
    {"风险管控方案", "风险管控", "风险应对", "风险防范措施"},
    {"风险应急预案", "应急预案", "应急方案"},
    {"主要研究结论", "研究结论", "结论"},
    {"问题与建议", "建议", "存在问题与建议"},
    {"附表", "附表清单", "表格附件"},
    {"附图", "附图清单", "图纸附件"},
    {"附件", "附件清单", "支撑材料"},
    {"信息化现状", "现状分析", "建设现状", "信息化建设现状"},
    {"存在问题及分析", "存在问题", "问题分析", "现状问题分析"},
    {"项目建设需求分析", "需求分析", "建设需求分析"},
    {"建设内容和规模", "建设内容", "建设规模", "主要建设内容"},
    {"项目产出方案", "产出方案", "产出说明"},
    {"项目建设背景", "建设背景", "背景分析"},
    {"规划政策符合性", "政策符合性", "规划符合性", "政策依据符合性"},
    {"项目建设必要性", "建设必要性", "必要性分析"},
    {"项目建设可行性", "建设可行性", "可行性分析"},
    {"编制依据", "编制依据与范围", "依据"},
    {"主要结论和建议", "主要结论与建议", "结论与建议"},
    {"项目概况", "项目基本情况", "项目概述"},
    {"项目单位概况", "建设单位概况", "项目单位基本情况"},
]

_SYNONYM_LOOKUP = {}
for _group in SYNONYM_GROUPS:
    _canon = sorted(_group)[0]
    for _word in _group:
        _SYNONYM_LOOKUP[_word] = _canon


def cn_to_int(text):
    """把中文数字（十/十五/二十三）转成整数，失败返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    total, section, number = 0, 0, 0
    for ch in text:
        if ch in CN_DIGITS:
            number = CN_DIGITS[ch]
        elif ch in CN_UNITS:
            unit = CN_UNITS[ch]
            section += (number or 1) * unit
            number = 0
        else:
            return None
    return total + section + number


def fullwidth_to_halfwidth(text):
    return unicodedata.normalize("NFKC", text or "")


def strip_number_prefix(text):
    """反复剥离标题前缀编号，返回 (编号串, 剩余标题)。"""
    text = (text or "").strip()
    prefixes = []
    changed = True
    while changed and text:
        changed = False
        for pattern in (_LEAD_CHAPTER, _LEAD_SECTION, _LEAD_CN_ITEM, _LEAD_NUM_ITEM, _LEAD_ALPHA_ITEM):
            match = pattern.match(text)
            if match:
                prefixes.append(match.group(0).strip())
                text = text[match.end():].strip()
                changed = True
                break
    return "".join(prefixes), text


def normalize_title(text):
    """标题归一化：去编号、去标点、统一全半角与大小写，用于同名判定。"""
    text = fullwidth_to_halfwidth(text or "")
    text = _MD_MARKS.sub(" ", text)
    text = text.replace("\u3000", " ")
    text = _LEVEL_MARK.sub(" ", text)
    text = _TRAIL_PAGE.sub("", text)
    _, text = strip_number_prefix(text)
    text = _PUNCT.sub("", text)
    return text.strip().lower()


def title_tokens(text):
    """把标题切成可比较的词元：2-gram + 拉丁词。"""
    norm = normalize_title(text)
    if not norm:
        return set()
    tokens = {norm}
    for size in (2, 3):
        for index in range(0, max(len(norm) - size + 1, 0)):
            tokens.add(norm[index:index + size])
    tokens.update(re.findall(r"[a-z0-9]{2,}", norm))
    return tokens


def bigrams(text):
    norm = normalize_title(text)
    if len(norm) < 2:
        return {norm} if norm else set()
    return {norm[i:i + 2] for i in range(len(norm) - 1)}


def jaccard(left, right):
    if not left or not right:
        return 0.0
    inter = len(left & right)
    union = len(left | right)
    return inter / union if union else 0.0


def containment(needle, haystack):
    """小集合被大集合覆盖的比例（短标题被长标题包含时更公平）。"""
    if not needle or not haystack:
        return 0.0
    return len(needle & haystack) / len(needle)


def similarity(left, right):
    """综合标题相似度 0~1：bigram Jaccard 与包含度取加权。"""
    if not left or not right:
        return 0.0
    left_norm, right_norm = normalize_title(left), normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    left_bi, right_bi = bigrams(left_norm), bigrams(right_norm)
    base = max(jaccard(left_bi, right_bi), 0.75 * containment(left_bi, right_bi),
               0.75 * containment(right_bi, left_bi))
    return round(min(base, 1.0), 4)


def synonym_canon(text):
    norm = normalize_title(text)
    for word, canon in _SYNONYM_LOOKUP.items():
        if norm == normalize_title(word):
            return canon
    return None


def synonym_related(left, right):
    """同一同义词族 → True。"""
    left_canon, right_canon = synonym_canon(left), synonym_canon(right)
    return bool(left_canon and right_canon and left_canon == right_canon)


def keywords_of(text, limit=None):
    """抽取用于覆盖度检查的关键词：中文 2-4 gram 里的高频实词 + 拉丁词/数字串。"""
    norm = normalize_title(text)
    words = re.findall(r"[a-z0-9][a-z0-9.\-]{1,}", norm)
    chinese = re.sub(r"[a-z0-9.\-]+", " ", norm)
    grams = set()
    for size in (4, 3, 2):
        for index in range(0, max(len(chinese) - size + 1, 0)):
            piece = chinese[index:index + size]
            if piece.strip():
                grams.add(piece)
    result = sorted(set(words) | grams, key=len, reverse=True)
    if limit:
        return result[:limit]
    return result


HEADING_NUMBER_RE = re.compile(r"^\s*(?:\d{1,2}(?:\s*[.．]\s*\d{1,2}){0,4}|[一二三四五六七八九十百零〇]{1,3})\s*[、.．)）]?\s+\S")
SECTION_WORD_RE = re.compile(r"^\s*第\s*[0-9一二三四五六七八九十百零〇]{1,3}\s*[章节条]")


def looks_like_heading(text):
    """无样式标题的兜底判定：短、无句末标点、像编号标题。"""
    text = (text or "").strip()
    if not text or len(text) > 40:
        return False
    if text.endswith(("。", "；", "，", "：", "！", "？", ".", "!", "?")):
        return False
    return bool(HEADING_NUMBER_RE.match(text) or SECTION_WORD_RE.match(text))

CATEGORY_SUFFIXES = (
    "系统设计方案", "设计方案", "技术方案", "建设方案", "实施方案", "方案", "设计",
    "体系", "架构", "拓扑", "分析", "评价", "评估", "管理", "规划", "目标", "内容",
    "规模", "要求", "研究", "选择", "落实", "计划", "情况", "措施", "平台", "模式",
    "流程", "结构", "标准", "规范", "清单", "报告", "说明", "建议", "结论", "附表",
    "附图", "附件", "职责", "现状", "问题", "需求", "任务", "依据", "来源",
)


def strip_category_suffix(text):
    """剥离"方案/设计/体系/架构…"等类别后缀，留下区分性词头。"""
    norm = normalize_title(text)
    changed = True
    while changed and len(norm) > 2:
        changed = False
        for suffix in CATEGORY_SUFFIXES:
            if len(norm) > len(suffix) and norm.endswith(suffix) and len(norm) - len(suffix) >= 2:
                norm = norm[: -len(suffix)]
                changed = True
                break
    return norm


# 剥掉类别后缀后剩下的"领域通用词头"不具区分性：建设/项目/工程… 只说明属于本类项目，
# 用它比对会把"建设任务"和"建设目标"算成完全相似。
GENERIC_HEADS = (
    "建设", "项目", "工程", "系统", "平台", "主要", "相关", "情况", "建议", "结论",
    "工作", "内容", "要求", "我国", "国家", "全市", "我市", "本次", "本", "本项目",
    "本工程", "其他", "有关", "基本", "一般",
)

HEAD_RATIO = 0.5  # 词头要占对方词头的至少一半长度，短词头被长标题包含不算词头匹配


def is_generic_head(text):
    """词头是否是领域通用词（建设/项目/工程…），这类词头不能作为匹配依据。"""
    return normalize_title(text) in GENERIC_HEADS


def candidate_similarity(left, right):
    """候选相似度：(effective, head_ok, synonym)。

    - 同义标题族：直接认作候选；
    - 词头相似（≥0.3）：按相似度排序；但词头必须是区分性词头——
      通用词头（"建设"）、或远短于对方的词头（"安全" ⊂ "潍坊市网络安全现状"）不算匹配；
    - 只有类别后缀相同（如"…系统设计方案"）：相似度打折，且需 ≥0.5 才算候选，
      避免把"安全系统设计方案"迁移到"运行维护系统设计方案"。
    """
    raw = similarity(left, right)
    if synonym_related(left, right):
        return raw, False, True
    left_head = strip_category_suffix(left)
    right_head = strip_category_suffix(right)
    head = similarity(left_head, right_head) if (left_head and right_head) else 0.0
    if head >= 0.3 and _head_comparable(left_head, right_head):
        return max(raw, head), True, False
    return round(raw * 0.6, 4), False, False


def _head_comparable(left_head, right_head):
    """词头是否可作匹配依据：非通用词，且两者长度相当。"""
    if is_generic_head(left_head) or is_generic_head(right_head):
        return False
    longer, shorter = max(len(left_head), len(right_head)), min(len(left_head), len(right_head))
    return shorter >= HEAD_RATIO * longer


def candidate_accepted(effective, head_ok, synonym):
    if synonym:
        return True
    return effective >= (0.34 if head_ok else 0.5)

