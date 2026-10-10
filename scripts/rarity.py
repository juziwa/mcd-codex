# -*- coding: utf-8 -*-
"""rarity.py — 麦麦图鉴 · 稀有度判定与名称归一化。

稀有度体系（四档）:
    R   常规款  常年菜单在售
    SR  人气款  菜单 tags 含「人气」
    SSR 限定款  限定/联名/上新/人气回归，或仅在部分时段（如早餐）供应
    UR  绝版款  历史吃过，但当前所有已采样菜单池中均已下架

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

# 判定为 SSR 的限定/联名关键词（名称包含即算）
LIMITED_KEYWORDS = ["高达", "世界波", "泷", "联名", "限定", "节日限定"]

# 判定为 SSR 的菜单标签关键词
LIMITED_TAGS = ["上新", "新品", "新品上市", "人气回归", "限定", "限定特惠"]

# 判定为 SR 的菜单标签关键词
POPULAR_TAGS = ["人气", "人气产品", "人气经典", "爆款"]

# 名称归一化时直接剔除的符号与噪音词
_STRIP_CHARS_RE = re.compile(r"[\s\u3000™®()（）\[\]【】“”\"'‘’·]")
# 规格后缀（归一化时移除，使「优品豆浆大杯」→「优品豆浆」）
_SIZE_SUFFIX_RE = re.compile(r"(大杯|中杯|小杯|大装|中装|小装)$")
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
                    {"regular", "breakfast"}。仅单一非全日时段 → SSR（限时供应）
    :return: R / SR / SSR / UR
    """
    tags = tags or []
    if not on_sale:
        return RARITY_UR

    # 1) 联名 / 限定关键词 → SSR
    if any(k in name for k in LIMITED_KEYWORDS):
        return RARITY_SSR
    # 2) 菜单标签: 限定类 → SSR, 人气类 → SR
    for t in tags:
        for kw in LIMITED_TAGS:
            if kw in t:
                return RARITY_SSR
    # 3) 仅在单一非全日时段供应（如只在早餐菜单出现）→ SSR 限时款
    #    （"regular" 为全时段主干菜单, 单独出现不算限时）
    if periods and len(periods) == 1 and "regular" not in periods:
        return RARITY_SSR
    for t in tags:
        for kw in POPULAR_TAGS:
            if kw in t:
                return RARITY_SR
    return RARITY_R


def is_limited(name):
    """是否属于限定册（仅按名称中的联名/限定关键词判定, 不看 tags）。"""
    return any(k in name for k in LIMITED_KEYWORDS)
