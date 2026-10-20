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
    # 派/圣代/新地都是甜品柜台的常客, 必须排在「小食」之前
    (r"冰淇淋|麦旋风|新地|圆筒|甜筒|阿芙佳朵|圣代|派$|蛋糕|布丁|冰棒", BOOK_DESSERT),
    (r"咖啡|奶茶|豆浆|可乐|雪碧|红茶|绿茶|牛奶|纯悦|苹果汁|橙橙|柠柠|燕麦奶|黑巧|奶铁|美式|卡布奇诺|奶昔|柠檬茶|锡兰",
     BOOK_DRINK),
    (r"麦满分|油条|粥|早餐|早安|炒双蛋|厚松饼", BOOK_BREAKFAST),
    (r"堡$|汉堡|巨无霸|卷$", BOOK_BURGER),
    (r"薯条|薯饼|麦乐鸡|鸡翅|鸡块|玉米杯|苹果片|拼盘|酱$|香肠|炸鸡|大四角",
     BOOK_SNACK),
    (r"周边|泡泡机|玩具|挠痒|捶痒", BOOK_SNACK),
]

# ---------------------------------------------------------------------------
# 套餐 / 组合识别
# ---------------------------------------------------------------------------
# 图鉴的原子单位是**单品**（codex.py: 组合餐展开到子项收录）。
# 若把套餐也放进图鉴池, 会出现三个问题:
#   1. 分母虚高（真实菜单 148 项里 60+ 是各种 N 件套）, 进度永远上不去;
#   2. 同一个汉堡既算「单品」又算「套餐」, 一格餐品占两格图鉴;
#   3. 早餐池被「二件套/三件套」塞满, 整册权重彻底失衡。
# 因此池内只保留单品级餐品, 套餐在采样时被显式跳过（并在 CLI 里报数）。
COMBO_TAGS = {"套餐", "二件套", "三件套", "四件套", "五件套", "六件套", "八件套",
              "组合", "小食拼盘", "随心配"}
_COMBO_NAME_RE = re.compile(
    r"(套餐|组合|件套|双人餐|单人餐|三人餐|四人餐|分享餐|随心选|随心配|任选"
    r"|拼盘|宫格|十翅|重奏|乐园餐|自选|双全盒|盒$)")
_COMBO_CATEGORIES = {"精选单人餐", "500大卡套餐", "随心配1+1", "小食拼盘/多人餐", "开心乐园"}

# 周边 / 玩具类（泡泡机、毛绒、按摩捶…）不是餐品, 不进餐品图鉴。
# 若不拦掉, 它们会以「上新」标签混进小食册并抢到 SSR, 让图鉴看起来像个杂货铺。
_MERCH_RE = re.compile(r"(周边|泡泡机|玩具|公仔|毛绒|按摩捶|捶痒|挠痒|挂件|徽章|贴纸|抱枕)")


def is_merch(name):
    """是否周边/玩具类商品（非餐品, 不进入图鉴池）。"""
    return bool(_MERCH_RE.search(name or ""))


def combo_of(name, tags=None, category=None):
    """判定是否为套餐/组合形态（用于把套餐挡在图鉴池之外）。

    命中任一条件即视为套餐:
        * 名称含「套餐 / 组合 / N 件套 / 单人餐 / 随心配 …」
        * 菜单标签含「套餐 / 二件套 / 三件套 …」
        * 菜单分类是套餐专区（精选单人餐 / 500大卡套餐 / 随心配1+1 …）

    >>> combo_of("板烧鸡腿堡三件套")
    True
    >>> combo_of("板烧鸡腿堡")
    False
    """
    tags = tags or []
    if any(t in COMBO_TAGS for t in tags):
        return True
    if category and category.replace("\n", "") in _COMBO_CATEGORIES:
        return True
    return bool(_COMBO_NAME_RE.search(name or ""))


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
        # 每个「门店 + 时段」只保留最近一次成功快照；products 是其当前并集。
        # 旧版文件没有 snapshots，首次成功更新后会自动迁移到快照模型。
        self.snapshots = data.get("snapshots", {})
        self.updated_at = data.get("updated_at", "")
        self.last_skipped_combos = []
        self.last_skipped_merch = []
        self.last_skipped_unknown = []
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
            "snapshots": self.snapshots,
            "products": self.products,
        }
        _atomic_dump_json(path, payload)

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

        previous_codes = set(self.products)
        snapshot_products = {}
        skipped_combos = []
        skipped_merch = []
        skipped_unknown = []
        for cat in categories:
            cat_name = (cat.get("name") or "").replace("\n", "")
            for meal in cat.get("meals") or []:
                code = str(meal.get("code") or "")
                tags = meal.get("tags") or []
                info = meals_map.get(code) or {}
                name = info.get("name") or str(meal.get("name") or code)
                # 只有编码没有名称（详情缺失）的条目无法成为图鉴一格
                if not name.strip() or name.strip() == code:
                    skipped_unknown.append(code)
                    continue
                # 图鉴只收集单品: 套餐/组合会被展开成单品后收录, 池内不再重复计数
                if combo_of(name, tags, cat_name):
                    skipped_combos.append(name)
                    continue
                if is_merch(name):
                    skipped_merch.append(name)
                    continue
                snapshot_products[code] = {
                    "name": name,
                    "image": info.get("image") or "",
                    "tags": sorted(set(tags)),
                    "category": cat_name,
                    "book": book_of(name, cat_name),
                    "periods": [period],
                    "price": info.get("currentPrice") or "",
                }
        # 一份「全是套餐」的响应无法支撑单品图鉴, 视为无效快照（不改动现有池）
        if not snapshot_products:
            raise CatalogPayloadError("query-meals 响应不含任何单品餐品，已跳过图鉴池更新")
        self.last_skipped_combos += skipped_combos
        self.last_skipped_merch += skipped_merch
        self.last_skipped_unknown += skipped_unknown

        fetched_at = fetched_at or _now()
        source_key = "%s::%s" % (str(store), period)
        self.snapshots[source_key] = {
            "store": str(store),
            "period": period,
            "fetched_at": fetched_at,
            "products": snapshot_products,
        }
        # 同一门店与时段替换旧快照；不同门店/时段取当前快照并集。
        self._rebuild_products_from_snapshots()
        self.sources = [
            {"store": snap["store"], "period": snap["period"],
             "fetched_at": snap["fetched_at"]}
            for snap in self.snapshots.values()
        ]
        current_codes = set(self.products)
        added = len(current_codes - previous_codes)
        updated = len(current_codes & previous_codes)
        return added, updated

    def _rebuild_products_from_snapshots(self):
        """由各来源的最新成功快照重建当前菜单池。"""
        products = {}
        for snap in self.snapshots.values():
            for code, incoming in snap.get("products", {}).items():
                if code not in products:
                    products[code] = dict(incoming)
                    products[code]["tags"] = list(incoming.get("tags") or [])
                    products[code]["periods"] = list(incoming.get("periods") or [])
                    continue
                entry = products[code]
                entry["tags"] = sorted(set(entry.get("tags") or []) |
                                       set(incoming.get("tags") or []))
                entry["periods"] = sorted(set(entry.get("periods") or []) |
                                          set(incoming.get("periods") or []))
                if not entry.get("image") and incoming.get("image"):
                    entry["image"] = incoming["image"]
        self.products = _merge_duplicate_names(products)
        self.reclassify()
        self._rebuild_name_index()

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


def _merge_duplicate_names(products):
    """同名餐品合并为一格。

    真实菜单里同一个餐品常有多个菜单 code（例如「派」同时以 4106 与
    9900015165、「脆薯饼」以 4825 与 521741 出现在同一次响应里）。
    若不合并, 图鉴墙会出现两个一模一样的格子, 分母也虚高。
    合并时保留信息最全的那条（有图 > 有价 > 编码靠前）, 时段与标签取并集。
    """
    def score(entry):
        return (1 if entry.get("image") else 0) + (1 if entry.get("price") else 0)

    result = {}
    index = {}
    for code, entry in sorted(products.items(), key=lambda kv: -score(kv[1])):
        key = rarity.normalize_name(entry.get("name") or "")
        if not key:
            result[code] = entry
            continue
        if key not in index:
            index[key] = code
            result[code] = entry
            continue
        keep = result[index[key]]
        keep["tags"] = sorted(set(keep.get("tags") or []) |
                              set(entry.get("tags") or []))
        keep["periods"] = sorted(set(keep.get("periods") or []) |
                                 set(entry.get("periods") or []))
        for field in ("image", "price", "category", "book"):
            if not keep.get(field) and entry.get(field):
                keep[field] = entry[field]
        keep.setdefault("merged_codes", []).append(code)
    return result


def _atomic_dump_json(path, payload):
    """原子保存图鉴池，避免写入中断损坏现有文件。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _now():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
