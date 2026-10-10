# -*- coding: utf-8 -*-
"""codex.py — 麦麦图鉴 · 收录核心逻辑与命令行入口。

核心循环: 点单 → 收集 → 点亮 → 炫耀
双通道点亮:
    ① 主动收录（主）: 在本 Skill 内下单, 订单完成后由 create-order /
       query-order 返回的 orderProductList 直接收录
    ② 增量补录（辅）: 每次打开图鉴时用 order-list 最近订单兜底防漏
       （order-list 仅返回最近 10 单, 不支持分页, 故定位为增量补录）

收录原子单位 = 订单子项（组合餐展开到单品级）:
    orderProductList[].comboItemList 存在 → 逐子项收录
    不存在（单品直购）→ 以商品本体收录
取消订单（orderStatus 含「取消」）不收录。

用法（均可在仓库根目录执行）:
    python scripts/codex.py absorb-menu  --menu data/snapshots/menu.json \
        --catalog data/catalog.json [--period regular|breakfast] [--store 1440001]
    python scripts/codex.py absorb-order --order data/snapshots/order-list.json \
        --codex data/codex.json [--catalog data/catalog.json]
    python scripts/codex.py sync --orders data/snapshots/order-list.json \
        --codex data/codex.json --catalog data/catalog.json
    python scripts/codex.py stats --codex data/codex.json [--catalog data/catalog.json]
    python scripts/codex.py render --codex data/codex.json --catalog data/catalog.json \
        --out-md output/codex.md --out-card output/share-card.html
"""

import argparse
import datetime
import json
import os
import sys

# 保证 scripts/ 目录内模块可直接互相 import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalog as catalog_mod  # noqa: E402
import rarity as rarity_mod  # noqa: E402

SCHEMA_VERSION = 1
CANCELLED_KEYWORD = "取消"

# 仓库/Skill 根目录（scripts/ 的上级）。
# 所有 CLI 默认路径锚定此目录而非 cwd, 保证从任意工作目录执行都可用。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default(rel_path):
    return os.path.join(ROOT, rel_path)

# ---------------------------------------------------------------------------
# 等级体系（按点亮单品总数）
# ---------------------------------------------------------------------------
LEVELS = [
    (100, 5, "麦门图鉴大师"),
    (60, 4, "品鉴家"),
    (30, 3, "老饕"),
    (10, 2, "常客"),
    (0, 1, "麦门新客"),
]

# ---------------------------------------------------------------------------
# 特质徽章
# ---------------------------------------------------------------------------
BADGES = [
    ("🍔 汉堡猎人", lambda s: s["by_book"].get("汉堡册", 0) >= 10),
    ("🍟 薯条之王", lambda s: s["potato_count"] >= 5),
    ("🌅 早餐战神", lambda s: s["by_book"].get("早餐册", 0) >= 15),
    ("🍦 甜品控", lambda s: s["dessert_done"]),
    ("✨ 限定收藏家", lambda s: s["ssr_ur_count"] >= 3),
    ("🏃 暴走探索者", lambda s: s["weekly_new"] >= 10),
    ("🗺️ 环游麦门", lambda s: s["store_count"] >= 10),
    ("💎 绝版猎人", lambda s: s["ur_count"] >= 1),
]


# ---------------------------------------------------------------------------
# CodexStore — 个人图鉴状态
# ---------------------------------------------------------------------------
class CodexStore:
    def __init__(self, data=None):
        data = data or {}
        self.schema_version = data.get("schema_version", SCHEMA_VERSION)
        self.created_at = data.get("created_at", _now())
        self.last_sync = data.get("last_sync", "")
        self.items = data.get("items", {})          # code -> item
        self.stores = data.get("stores", {})        # storeCode -> {name, visits}
        self.orders_seen = data.get("orders_seen", [])

    # -- 持久化 ------------------------------------------------------------
    @classmethod
    def load(cls, path):
        if not os.path.exists(path):
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def save(self, path):
        self.last_sync = _now()
        payload = {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "last_sync": self.last_sync,
            "items": self.items,
            "stores": self.stores,
            "orders_seen": self.orders_seen,
        }
        _ensure_parent(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # -- 收录 --------------------------------------------------------------
    def absorb_order(self, order, catalog=None):
        """收录单笔订单。返回 (新点亮项列表, 累加项列表)。

        :param order: 订单 dict（order-list 元素或 query-order 返回）
        :param catalog: catalog_mod.Catalog 实例或 None
        """
        new_items, bumped = [], []
        order_id = str(order.get("orderId") or "")
        if order_id and order_id in self.orders_seen:
            return new_items, bumped
        if CANCELLED_KEYWORD in str(order.get("orderStatus") or ""):
            if order_id:
                self.orders_seen.append(order_id)
            return new_items, bumped

        create_time = order.get("createTime") or ""
        store_name = order.get("storeName") or ""
        store_code = str(order.get("storeCode") or "")

        for product in order.get("orderProductList") or []:
            sub_items = product.get("comboItemList") or []
            for unit in (sub_items if sub_items else [product]):
                self._absorb_unit(
                    unit.get("productCode"), unit.get("name") or unit.get("productName"),
                    unit.get("quantity") or 1, create_time, store_name,
                    catalog, new_items, bumped,
                )
            # 无子项的单品在外层已收录；组合餐父项（套餐本身）不单独收录，
            # 图鉴以单品级为原子单位。

        if order_id:
            self.orders_seen.append(order_id)
        if store_code or store_name:
            entry = self.stores.setdefault(
                store_code or store_name, {"name": store_name, "visits": 0})
            entry["visits"] += 1
            if store_name:
                entry["name"] = store_name
        return new_items, bumped

    def _absorb_unit(self, code, name, quantity, create_time, store_name,
                     catalog, new_items, bumped):
        """收录一个单品级条目。

        图鉴条目 key = 归一化身份（防止同品分裂）:
            菜单池匹配成功 → catalog code（如所有规格的薯条合并为「薯条」）
            匹配失败       → "n:" + 归一化名称（如两个不同 code 的香芋派合并）
        """
        code = str(code or "")
        name = str(name or code)
        matched = catalog.match(code, name)[0] if catalog is not None else None
        key = str(matched) if matched else "n:" + rarity_mod.normalize_name(name)
        item = self.items.get(key)
        if item is not None:
            item["count"] = item.get("count", 0) + (quantity or 1)
            bumped.append(item["name"])
            return
        item = {
            "name": name,
            "book": catalog_mod.BOOK_SNACK,
            "rarity": rarity_mod.RARITY_R,
            "first_unlock": create_time,
            "store": store_name,
            "count": quantity or 1,
            "image": "",
            "catalog_code": "",
        }
        if catalog is not None:
            self._enrich_with_catalog(item, code, catalog)
        self.items[key] = item
        new_items.append(item)

    def _enrich_with_catalog(self, item, code, catalog):
        """用图鉴池信息回填 item: 标准名/图片/册别/稀有度。"""
        matched, how = catalog.match(code, item["name"])
        if matched:
            entry = catalog.products[matched]
            item["catalog_code"] = matched
            item["name"] = entry.get("name") or item["name"]  # 用菜单标准名
            item["image"] = entry.get("image") or ""
            item["rarity"] = rarity_mod.classify(
                entry["name"], entry.get("tags"), on_sale=True,
                periods=set(entry.get("periods") or []))
            item["book"] = (catalog_mod.BOOK_LIMITED
                            if rarity_mod.is_limited(entry["name"])
                            else entry.get("book") or item["book"])
        else:
            item["rarity"] = rarity_mod.RARITY_UR  # 池外 → 绝版候选
            if rarity_mod.is_limited(item["name"]):
                item["book"] = catalog_mod.BOOK_LIMITED
            else:
                item["book"] = catalog_mod.book_of(item["name"])

    def reclassify(self, catalog):
        """全量重判（UR 复活机制: 菜单池扩充后 UR 可能回到在售）。"""
        revived = []
        for key, item in self.items.items():
            before = item.get("rarity")
            self._enrich_with_catalog(item, key, catalog)
            if before == rarity_mod.RARITY_UR and item["rarity"] != rarity_mod.RARITY_UR:
                revived.append(item["name"])
        return revived

    # -- 统计 --------------------------------------------------------------
    def stats(self, catalog=None):
        items = self.items.values()
        total = len(items)
        by_book = {}
        for it in items:
            by_book[it["book"]] = by_book.get(it["book"], 0) + 1

        level_no, title = LEVELS[-1][1], LEVELS[-1][2]
        for threshold, lv, t in LEVELS:
            if total >= threshold:
                level_no, title = lv, t
                break

        ur_count = sum(1 for it in items if it["rarity"] == rarity_mod.RARITY_UR)
        ssr_count = sum(1 for it in items if it["rarity"] == rarity_mod.RARITY_SSR)
        weekly_new = sum(
            1 for it in items
            if _within_days(it.get("first_unlock") or "", 7))
        favorite = max(items, key=lambda x: x.get("count", 0), default=None)
        treasure = None
        for want in (rarity_mod.RARITY_UR, rarity_mod.RARITY_SSR):
            cands = [it for it in items if it["rarity"] == want]
            if cands:
                treasure = min(cands, key=lambda x: x.get("first_unlock") or "9999")
                break

        pool_by_book = catalog.pool_by_book() if catalog else {}
        dessert_pool = pool_by_book.get(catalog_mod.BOOK_DESSERT) or {}
        dessert_done = (bool(dessert_pool) and all(
            any(c == d or it.get("catalog_code") == d for c, it in self.items.items())
            for d in dessert_pool))

        summary = {
            "unlocked": total,
            "level": level_no,
            "title": title,
            "by_book": by_book,
            "pool_total": len(catalog) if catalog else None,
            "pool_by_book": ({b: len(v) for b, v in pool_by_book.items()}
                             if catalog else {}),
            "ur_count": ur_count,
            "ssr_count": ssr_count,
            "ssr_ur_count": ssr_count + ur_count,
            "potato_count": sum(1 for it in items if "薯" in it["name"]),
            "weekly_new": weekly_new,
            "store_count": len(self.stores),
            "dessert_done": dessert_done,
            "favorite": {"name": favorite["name"], "count": favorite["count"]}
            if favorite else None,
            "treasure": {"name": treasure["name"], "rarity": treasure["rarity"]}
            if treasure else None,
        }
        summary["badges"] = [name for name, cond in BADGES if cond(summary)]
        return summary


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _within_days(time_str, days):
    try:
        t = datetime.datetime.strptime(time_str[:19], "%Y-%m-%d %H:%M:%S")
        return (datetime.datetime.now() - t).days <= days
    except (ValueError, TypeError):
        return False


def _ensure_parent(path):
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def extract_orders(payload):
    """从 order-list 完整响应 / list / 单订单 dict 中提取订单列表。"""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(payload, list):
        return payload
    data = payload.get("data") or {}
    if isinstance(data, dict) and isinstance(data.get("list"), list):
        return data["list"]
    if isinstance(payload.get("orderProductList"), list):
        return [payload]
    return []


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _emit(obj):
    """以 UTF-8 输出 JSON 摘要（供 Skill 层解读）。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# CLI 子命令
# ---------------------------------------------------------------------------
def cmd_absorb_menu(args):
    cat = catalog_mod.Catalog.load(args.catalog)
    payload = _load_json(args.menu)
    added, updated = cat.absorb_menu(payload, period=args.period, store=args.store)
    cat.save(args.catalog)
    _emit({
        "action": "absorb-menu",
        "catalog": args.catalog,
        "period": args.period,
        "pool_size": len(cat),
        "added": added,
        "updated": updated,
    })


def cmd_absorb_order(args):
    store = CodexStore.load(args.codex)
    cat = catalog_mod.Catalog.load(args.catalog) if args.catalog else None
    orders = extract_orders(_load_json(args.order))
    new_all, bump_all = [], []
    for order in orders:
        new_items, bumped = store.absorb_order(order, cat)
        new_all.extend(new_items)
        bump_all.extend(bumped)
    if cat:
        revived = store.reclassify(cat)
    else:
        revived = []
    store.save(args.codex)
    _emit({
        "action": "absorb-order",
        "orders_read": len(orders),
        "new_unlocks": [{"name": i["name"], "book": i["book"],
                         "rarity": i["rarity"]} for i in new_all],
        "bumped": bump_all,
        "revived_from_ur": revived,
        "total_unlocked": len(store.items),
    })


def cmd_sync(args):
    store = CodexStore.load(args.codex)
    cat = catalog_mod.Catalog.load(args.catalog) if args.catalog else None
    orders = extract_orders(_load_json(args.orders))
    new_all = []
    for order in orders:
        new_items, _ = store.absorb_order(order, cat)
        new_all.extend(new_items)
    revived = store.reclassify(cat) if cat else []
    store.save(args.codex)
    _emit({
        "action": "sync",
        "orders_read": len(orders),
        "new_unlocks": [{"name": i["name"], "book": i["book"],
                         "rarity": i["rarity"]} for i in new_all],
        "revived_from_ur": revived,
        "stats": store.stats(cat),
    })


def cmd_stats(args):
    store = CodexStore.load(args.codex)
    cat = catalog_mod.Catalog.load(args.catalog) if args.catalog else None
    _emit({"action": "stats", "stats": store.stats(cat)})


def cmd_render(args):
    import render
    store = CodexStore.load(args.codex)
    cat = catalog_mod.Catalog.load(args.catalog) if args.catalog else None
    outputs = {}
    if args.out_md:
        _ensure_parent(args.out_md)
        with open(args.out_md, "w", encoding="utf-8") as f:
            f.write(render.render_markdown(store, cat))
        outputs["markdown"] = args.out_md
    if args.out_card:
        outputs["share_card"] = render.render_share_card(
            store, cat, args.template, args.out_card)
    _emit({"action": "render", "outputs": outputs,
           "stats": store.stats(cat)})


def build_parser():
    parser = argparse.ArgumentParser(description="麦麦图鉴 McD Codex 收录引擎")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("absorb-menu", help="合并一份 query-meals 菜单快照进图鉴池")
    p.add_argument("--menu", required=True, help="query-meals 响应 JSON 文件")
    p.add_argument("--catalog", default=_default("data/catalog.json"))
    p.add_argument("--period", default="regular", choices=["regular", "breakfast"])
    p.add_argument("--store", default="")
    p.set_defaults(func=cmd_absorb_menu)

    p = sub.add_parser("absorb-order", help="收录订单（order-list / query-order 响应）")
    p.add_argument("--order", required=True, help="订单 JSON 文件")
    p.add_argument("--codex", default=_default("data/codex.json"))
    p.add_argument("--catalog", default=_default("data/catalog.json"))
    p.set_defaults(func=cmd_absorb_order)

    p = sub.add_parser("sync", help="补录全部订单并重判稀有度")
    p.add_argument("--orders", required=True, help="order-list 响应 JSON 文件")
    p.add_argument("--codex", default=_default("data/codex.json"))
    p.add_argument("--catalog", default=_default("data/catalog.json"))
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("stats", help="输出图鉴统计（等级/称号/徽章）")
    p.add_argument("--codex", default=_default("data/codex.json"))
    p.add_argument("--catalog", default=_default("data/catalog.json"))
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("render", help="渲染 Markdown 图鉴与 HTML 分享卡")
    p.add_argument("--codex", default=_default("data/codex.json"))
    p.add_argument("--catalog", default=_default("data/catalog.json"))
    p.add_argument("--out-md", default=_default("output/codex.md"))
    p.add_argument("--out-card", default=_default("output/share-card.html"))
    p.add_argument("--template", default=None,
                   help="分享卡模板路径（缺省用脚本相对路径的默认模板）")
    p.set_defaults(func=cmd_render)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
