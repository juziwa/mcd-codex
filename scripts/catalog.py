# -*- coding: utf-8 -*-
"""catalog.py — 麦麦图鉴 · 图鉴池（菜单池）构建与册别归类。

图鉴池 = 多时段采样的 query-meals 菜单合集。麦当劳菜单按餐段返回
（早餐品仅出现在早餐时段菜单），因此需对同一门店分别采样
「常规时段」（不传 reservationDate）与「早餐时段」（传实际日期 10:00）
后合并，才能支撑可靠的绝版（UR）判定。

册别（六册）:
    🍔 汉堡册 / 🌅 早餐册 / 🍟 小食册 / 🍦 甜品册 / 🥤 饮品册 / ✨ 限定册
"""

import json
import os
import re

import rarity


class CatalogPayloadError(ValueError):
    """Raised when a query-meals response cannot safely update the catalog."""

# ---------------------------------------------------------------------------
# 册别常量
# ---------------------------------------------------------------------------
BOOK_BURGER = "汉堡册"
BOOK_BREAKFAST = "早餐册"
BOOK_SNACK = "小食册"
BOOK_DESSERT = "甜品册"
BOOK_DRINK = "饮品册"
BOOK_LIMITED = "限定册"

BOOKS = [BOOK_BURGER, BOOK_BREAKFAST, BOOK_SNACK, BOOK_DESSERT, BOOK_DRINK, BOOK_LIMITED]

BOOK_EMOJI = {
    BOOK_BURGER: "🍔",
    BOOK_BREAKFAST: "🌅",
    BOOK_SNACK: "🍟",
    BOOK_DESSERT: "🍦",
    BOOK_DRINK: "🥤",
    BOOK_LIMITED: "✨",
}

# 菜单分类名 → 册别（分类名可能含换行, 如「鸡肉汉堡\\n/卷」）
_CATEGORY_BOOK_RULES = [
    (r"早餐|麦满分|厚松饼|炒双蛋|营养卷|一早现磨|满分假日", BOOK_BREAKFAST),
    (r"汉堡|牛鱼肉堡|大堡口福|单人餐", BOOK_BURGER),
    (r"炸鸡|小食拼盘|多人餐|开心乐园|500大卡", BOOK_SNACK),
    (r"麦咖啡|饮品", BOOK_DRINK),
]

# 名称关键词 → 册别（分类缺失/不明时兜底; 顺序即优先级）
_NAME_BOOK_RULES = [
    (r"冰淇淋|麦旋风|新地|圆筒|甜筒|阿芙佳朵", BOOK_DESSERT),
    (r"咖啡|奶茶|豆浆|可乐|雪碧|红茶|绿茶|牛奶|纯悦|苹果汁|橙橙|柠柠|燕麦奶|黑巧|奶铁|美式|卡布奇诺|奶昔|柠檬茶|锡兰",
     BOOK_DRINK),
    (r"麦满分|油条|粥|早餐|早安|炒双蛋|厚松饼", BOOK_BREAKFAST),
    (r"堡$|汉堡|巨无霸|卷$", BOOK_BURGER),
    (r"薯条|薯饼|麦乐鸡|鸡翅|鸡块|玉米杯|苹果片|派$|拼盘|酱$|香肠|炸鸡|大四角",
     BOOK_SNACK),
    (r"周边|泡泡机|玩具|挠痒|捶痒", BOOK_SNACK),
]


def book_of(name, category=None):
    """判定餐品归属册别: 分类规则优先, 名称规则兜底, 最终兜底小食册。"""
    if category:
        for pattern, book in _CATEGORY_BOOK_RULES:
            if re.search(pattern, category.replace("\n", "")):
                return book
    norm_name = (name or "").strip()
    for pattern, book in _NAME_BOOK_RULES:
        if re.search(pattern, norm_name):
            return book
    return BOOK_SNACK


# ---------------------------------------------------------------------------
# 图鉴池（Catalog）
# ---------------------------------------------------------------------------
class Catalog:
    """多时段合并的菜单池。

    结构:
        self.products[code] = {
            "name", "image", "tags", "book", "category",
            "rarity", "periods": {"regular", "breakfast"}, "price"
        }
        self.name_index[normalized_name] = [code, ...]
    """

    def __init__(self, data=None):
        data = data or {}
        self.products = data.get("products", {})
        self.sources = data.get("sources", [])
        self.updated_at = data.get("updated_at", "")
        self._rebuild_name_index()

    # -- 构建 ------------------------------------------------------------
    @classmethod
    def load(cls, path):
        if not os.path.exists(path):
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def save(self, path):
        self.updated_at = _now()
        payload = {
            "updated_at": self.updated_at,
            "sources": self.sources,
            "products": self.products,
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def absorb_menu(self, menu_payload, period="regular", store="", fetched_at=None):
        """合并一份 query-meals 响应进图鉴池。

        :param menu_payload: query-meals 的原始 JSON（dict 或 JSON 字符串）
        :param period: 采样时段 "regular"（当前时段）或 "breakfast"（早餐采样）
        :param store: 采样门店 storeCode
        :return: (新增数, 更新数)
        """
        if isinstance(menu_payload, str):
            try:
                menu_payload = json.loads(menu_payload)
            except json.JSONDecodeError as exc:
                raise CatalogPayloadError("query-meals 响应不是有效 JSON") from exc
        if not isinstance(menu_payload, dict):
            raise CatalogPayloadError("query-meals 响应不是 JSON 对象")
        # 部分 MCP 客户端只保留 data；若有状态字段，则必须明确表示成功。
        if ("success" in menu_payload and menu_payload["success"] is not True
                or "code" in menu_payload and menu_payload["code"] not in (200, "200")):
            raise CatalogPayloadError("query-meals 返回失败，已保留原图鉴池")
        data = menu_payload.get("data")
        if not isinstance(data, dict):
            raise CatalogPayloadError("query-meals 响应缺少有效 data")
        categories = data.get("categories")
        meals_map = data.get("meals")
        if not isinstance(categories, list) or not isinstance(meals_map, dict):
            raise CatalogPayloadError("query-meals 响应缺少有效 categories/meals")

        # 先完整验证再修改，避免一份响应的后半段损坏时留下半份菜单。
        menu_count = 0
        for category in categories:
            if (not isinstance(category, dict)
                    or (category.get("name") is not None
                        and not isinstance(category.get("name"), str))
                    or not isinstance(category.get("meals", []), list)):
                raise CatalogPayloadError("query-meals 分类结构无效")
            for meal in category.get("meals", []):
                if not isinstance(meal, dict):
                    raise CatalogPayloadError("query-meals 餐品结构无效")
                code = meal.get("code")
                if not isinstance(code, str) or not code.strip():
                    raise CatalogPayloadError("query-meals 餐品缺少编码")
                info = meals_map.get(code) or {}
                if not isinstance(info, dict):
                    raise CatalogPayloadError("query-meals 餐品详情无效")
                fallback_name = meal.get("name") or code
                if not isinstance(info.get("name") or fallback_name, str):
                    raise CatalogPayloadError("query-meals 餐品名称无效")
                if not isinstance(info.get("image") or "", str):
                    raise CatalogPayloadError("query-meals 餐品图片字段无效")
                tags = meal.get("tags", [])
                if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
                    raise CatalogPayloadError("query-meals 餐品标签无效")
                menu_count += 1
        # 空菜单可能是未营业或无供应，不能据此宣告历史餐品绝版。
        if menu_count == 0:
            raise CatalogPayloadError("query-meals 响应不含可用餐品，已跳过图鉴池更新")

        added, updated = 0, 0
        for cat in categories:
            cat_name = (cat.get("name") or "").replace("\n", "")
            for meal in cat.get("meals") or []:
                code = str(meal.get("code") or "")
                if not code:
                    continue
                tags = meal.get("tags") or []
                info = meals_map.get(code) or {}
                name = info.get("name") or str(meal.get("name") or code)
                entry = self.products.get(code)
                if entry is None:
                    entry = {
                        "name": name,
                        "image": info.get("image") or "",
                        "tags": sorted(set(tags)),
                        "category": cat_name,
                        "book": book_of(name, cat_name),
                        "periods": [],
                        "price": info.get("currentPrice") or "",
                    }
                    self.products[code] = entry
                    added += 1
                else:
                    # 合并 tags / 时段 / 图片（后到的信息补充先到的）
                    entry["tags"] = sorted(set(entry["tags"]) | set(tags))
                    if info.get("image"):
                        entry["image"] = entry["image"] or info["image"]
                    updated += 1
                if period not in entry["periods"]:
                    entry["periods"].append(period)

        self.sources.append({
            "store": str(store),
            "period": period,
            "fetched_at": fetched_at or _now(),
        })
        # 全量重判稀有度（UR 复活机制: 新采样时段可能把 UR 拉回在售）
        self.reclassify()
        self._rebuild_name_index()
        return added, updated

    def reclassify(self):
        """对池内所有产品重新判定稀有度。"""
        for code, entry in self.products.items():
            entry["rarity"] = rarity.classify(
                entry["name"], entry.get("tags"),
                on_sale=True, periods=set(entry.get("periods") or []),
            )

    def _rebuild_name_index(self):
        self.name_index = {}
        for code, entry in self.products.items():
            key = rarity.normalize_name(entry.get("name") or "")
            if key:
                self.name_index.setdefault(key, []).append(code)

    # -- 查询 ------------------------------------------------------------
    def match(self, code, name):
        """在售匹配: 返回 (matched_catalog_code 或 None, 匹配方式)。

        匹配顺序: code 精确 → 名称归一化精确 → 菜单别名 → 名称弱匹配（互为子串）。
        """
        code = str(code or "")
        if code and code in self.products:
            return code, "code"
        key = rarity.normalize_name(name or "")
        if key and key in self.name_index:
            return self.name_index[key][0], "name"
        alias = rarity.match_name(name or "")
        if alias and alias != key and alias in self.name_index:
            return self.name_index[alias][0], "alias"
        if alias:
            for codes in self.name_index.values():
                if rarity.is_weak_match(alias, self.products[codes[0]]["name"]):
                    return codes[0], "weak"
        return None, None

    def is_on_sale(self, code, name):
        return self.match(code, name)[0] is not None

    def pool_by_book(self):
        """{册别: {code: entry}} 限定册仅收录名称含联名/限定关键词的款。"""
        result = {b: {} for b in BOOKS}
        for code, entry in self.products.items():
            book = entry.get("book") or BOOK_SNACK
            if rarity.is_limited(entry["name"]):
                book = BOOK_LIMITED
            result.setdefault(book, {})[code] = entry
        return result

    def __len__(self):
        return len(self.products)


def _now():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
