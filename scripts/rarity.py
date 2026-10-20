# -*- coding: utf-8 -*-
"""rarity.py — 麦麦图鉴 · 稀有度判定与名称归一化。

稀有度体系（四档，收集玩法的地基）:
    R   常规款  菜单上的常规在售单品
    SR  人气款  招牌经典款（品牌长青的碳水支柱）
    SSR 限定款  联名 / 主题限定 / 当季上新
    UR  绝版款  历史吃过，但当前所有已采样菜单池中均已下架

设计原则 —— **越稀有越少**:
    早期版本把「仅早餐时段供应」直接判为 SSR，导致早餐池 55 款 100% 变成
    「限定款金色」，SSR 占全池 55%（比常规款还多），稀有度的稀缺感被彻底
    关掉（详见项目诊断硬伤 1）。现行规则改为按「限定属性」而不是「供应时段」
    分层：
        1. UR  —— 只由「是否在池内」决定，永远不进池（池 ≡ 当前在售）
        2. SSR —— 名称含联名/主题限定词，或菜单标签含上新/限定
        3. SR  —— 招牌经典款（SIGNATURE_KEYWORDS），或菜单标签含人气
        4. R   —— 其余常规在售
    时段（periods）只用于展示「早餐限定 / 全时段」，不再参与稀有度判定。

设计要点（源自真实 MCP 数据勘察）:
    1. 订单子项的 productCode 与菜单单品的 code 是两套体系
       （例: 订单「板烧鸡腿堡」=901406，菜单单品「板烧鸡腿堡」=1406），
       因此在售判定必须 code 精确匹配 + 名称归一化匹配双通道，防止误判绝版。
    2. 菜单按餐段返回（早餐品仅出现在早餐时段菜单），
       绝版判定必须基于多时段合并后的菜单池。
    3. 同一产品可能存在多个菜单 code（例: 脆薯饼同时存在 4825 / 521741），
       名称索引需支持一对多。
"""

import re

# ---------------------------------------------------------------------------
# 稀有度常量
# ---------------------------------------------------------------------------
RARITY_R = "R"      # 常规款
RARITY_SR = "SR"    # 人气款
RARITY_SSR = "SSR"  # 限定款
RARITY_UR = "UR"    # 绝版款

RARITY_LABEL = {
    RARITY_R: "常规款",
    RARITY_SR: "人气款",
    RARITY_SSR: "限定款",
    RARITY_UR: "绝版款",
}

RARITY_STARS = {RARITY_R: "★", RARITY_SR: "★★", RARITY_SSR: "★★★", RARITY_UR: "★★★★"}

# 稀有度由低到高（排序 / 分档统计用）
RARITY_ORDER = [RARITY_R, RARITY_SR, RARITY_SSR, RARITY_UR]
RARITY_RANK = {r: i for i, r in enumerate(RARITY_ORDER)}

# 判定为 SSR 的联名/主题限定关键词（名称包含即算）
LIMITED_KEYWORDS = [
    "高达", "世界波", "泷", "联名", "限定", "典藏",
    "节日限定", "周年限定", "季节限定", "季节", "圣诞", "春节", "中秋", "新年",
]

# 判定为 SSR 的菜单标签关键词（当季上新 / 限定)。
# 注意: 「限定特惠」是**限时折扣**而不是限定商品, 早期版本把它算作 SSR,
# 导致 4 款常年供应的麦咖啡因为打折被标成「限定款」, 已剔除。
LIMITED_TAGS = ["上新", "新品", "新品上市", "限定", "限量", "联名", "人气回归"]

# 促销类标签（含「限定」二字但本质是打折, 不能算限定商品）
PROMO_TAGS = {"限定特惠", "限时特惠", "限时优惠", "限时秒杀", "特惠"}

# 判定为 SR 的菜单标签关键词（官方认定的人气款）
POPULAR_TAGS = ["人气", "人气产品", "人气经典", "爆款", "粉丝之选", "人气热卖"]

# 判定为 SR 的招牌经典款（**归一化名称精确匹配**）。
# 只收「品牌长青的招牌单品」——新款/限定款由 SSR 通道处理；
# 时段限定（如仅早餐在售）不是稀有的理由。
# 用精确匹配而非子串匹配, 避免「脆脆薯条 / 迷你新地 / 4块麦乐鸡」这类
# 规格变体把 SR 撑到 30%+, 让 R / SR / SSR 保持清晰梯度。
SIGNATURE_NAMES = {
    # 汉堡
    "巨无霸", "板烧鸡腿堡", "麦辣鸡腿汉堡", "麦香鸡", "麦香鱼",
    "双层吉士汉堡", "吉士汉堡",
    # 小食
    "薯条", "麦乐鸡", "麦辣鸡翅", "脆薯饼",
    # 甜品
    "经典麦旋风", "新地", "圆筒冰淇淋",
    # 饮品
    "可乐", "优品豆浆",
    # 早餐
    "猪柳蛋麦满分", "脆香油条",
}

# 名称归一化时直接剔除的符号与噪音词
_STRIP_CHARS_RE = re.compile(r"[\s\u3000™®()（）\[\]【】“”\"'‘’·]")
# 规格后缀（归一化时移除，使「优品豆浆大杯」→「优品豆浆」）
_SIZE_SUFFIX_RE = re.compile(r"(大杯|中杯|小杯|大装|中装|小装|大份|中份|小份)$")
# 规格同义词（订单侧叫法 → 菜单侧叫法）。
# 属「同一款产品的不同规格/写法」, 既参与在售匹配, 也参与图鉴身份合并。
_SYNONYMS = {
    "可口可乐": "可乐",
    "无糖可口可乐": "无糖可乐",
    "中薯条": "薯条",
    "大薯条": "薯条",
    "小薯条": "薯条",
}

# 菜单槽位别名（订单侧口味/名称 → 菜单通用名）。
# 菜单上「派」是一个通用槽位（可选香芋/菠萝口味）, 别名仅用于「在售判定」,
# 不参与图鉴身份合并 —— 否则香芋派与菠萝派会被错误合并为一条。
_MENU_ALIASES = {
    "香芋派": "派",
    "菠萝派": "派",
}

# 弱匹配（互为子串）所需的最短核心词长度
_WEAK_MATCH_MIN_LEN = 3


def normalize_name(name):
    """身份级归一化: 去符号/空格/规格后缀 + 规格同义词。

    用于图鉴条目身份（防同品分裂）, 不含口味别名。

    >>> normalize_name("优品豆浆大杯")
    '优品豆浆'
    >>> normalize_name("中薯条")
    '薯条'
    >>> normalize_name("香芋派")
    '香芋派'
    """
    if not name:
        return ""
    s = _STRIP_CHARS_RE.sub("", str(name))
    s = _SIZE_SUFFIX_RE.sub("", s)
    return _SYNONYMS.get(s, s)


def match_name(name):
    """匹配级归一化: 身份级归一化 + 菜单槽位别名。

    仅用于「在售判定」, 不用于身份 key。

    >>> match_name("香芋派")
    '派'
    """
    s = normalize_name(name)
    return _MENU_ALIASES.get(s, s)


def is_weak_match(a, b):
    """弱匹配: 归一化后互为子串且短边长度达标（用于兜底的在售判定, 不用于合并）。"""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb or na == nb:
        return na == nb
    if len(na) < _WEAK_MATCH_MIN_LEN or len(nb) < _WEAK_MATCH_MIN_LEN:
        return False
    return na in nb or nb in na


def classify(name, tags=None, on_sale=True, periods=None):
    """稀有度判定主入口。

    :param name:    餐品名称
    :param tags:    菜单侧 tags（订单侧收录时可为 None）
    :param on_sale: 是否在合并菜单池中（False → UR 绝版款）
    :param periods: 该品出现的菜单时段集合, 如 {"regular"} / {"breakfast"} /
                    {"regular", "breakfast"}。**不再参与稀有度判定**，
                    仅保留参数以兼容既有调用方。
    :return: R / SR / SSR / UR
    """
    tags = tags or []
    if not on_sale:
        return RARITY_UR

    # 1) 联名 / 主题限定关键词 → SSR
    if any(k in name for k in LIMITED_KEYWORDS):
        return RARITY_SSR
    # 2) 菜单标签: 限定/上新类 → SSR（促销标签不参与）
    for t in tags:
        if t in PROMO_TAGS:
            continue
        for kw in LIMITED_TAGS:
            if kw in t:
                return RARITY_SSR
    # 3) 招牌经典款 或 官方人气标签 → SR
    for t in tags:
        for kw in POPULAR_TAGS:
            if kw in t:
                return RARITY_SR
    if is_signature(name):
        return RARITY_SR
    return RARITY_R


def is_signature(name):
    """是否属于招牌经典款（归一化名称精确匹配）。"""
    return normalize_name(name) in SIGNATURE_NAMES


def is_limited(name):
    """是否属于限定册（仅按名称中的联名/限定关键词判定, 不看 tags）。"""
    norm = normalize_name(name)
    return any(k in norm for k in LIMITED_KEYWORDS)


def rank_of(rarity):
    """稀有度档位序号（R=0 … UR=3），未知档位按 0 处理。"""
    return RARITY_RANK.get(rarity, 0)
