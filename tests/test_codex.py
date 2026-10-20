# -*- coding: utf-8 -*-
"""麦麦图鉴（McD Codex）测试套件。

覆盖层次:
    单元测试  rarity 归一化/稀有度判定, catalog 册别归类/三通道匹配
    集成测试  CodexStore 收录全流程, CLI 子命令端到端
    边界测试  取消单 / 重复补录幂等 / 空数据 / 无图鉴池降级 / UR 复活
    回归测试  开发期修复的 4 个真实缺陷（同品分裂 / 时段 SSR 误判 /
             香芋派误判 UR / 限定册过宽）

运行: python -m unittest discover -s tests -v
   或: python tests/test_codex.py
"""

import json
import copy
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import catalog as catalog_mod  # noqa: E402
import codex as codex_mod  # noqa: E402
import rarity as rarity_mod  # noqa: E402
import render as render_mod  # noqa: E402  （render 依赖 catalog/rarity）

EXAMPLES = os.path.join(ROOT, "examples")


def _load_example(name):
    with open(os.path.join(EXAMPLES, name), "r", encoding="utf-8") as f:
        return json.load(f)


def _menu_payload(code_name_pairs, category="测试分类", period_tags=None):
    """构造一份极简 query-meals 响应，用于隔离测试。"""
    meals = {}
    cat_meals = []
    for code, name in code_name_pairs:
        meals[str(code)] = {"name": name, "image": "http://img/%s.png" % code,
                            "currentPrice": "10"}
        entry = {"code": str(code)}
        if period_tags and code in period_tags:
            entry["tags"] = period_tags[code]
        cat_meals.append(entry)
    return {"success": True, "data": {
        "categories": [{"name": category, "meals": cat_meals}],
        "meals": meals,
    }}


def _order(order_id, status, products, create_time="2026-10-01 12:00:00",
           store_code="1440001", store_name="测试餐厅"):
    """构造一笔订单。products: [(code, name, qty, [子项...])]"""
    plist = []
    for code, name, qty, subs in products:
        item = {"productCode": str(code), "productName": name, "quantity": qty}
        if subs:
            item["comboItemList"] = [
                {"productCode": str(c), "name": n, "quantity": q} for c, n, q in subs]
        plist.append(item)
    return {"orderId": order_id, "createTime": create_time,
            "orderStatus": status, "storeCode": store_code,
            "storeName": store_name, "orderProductList": plist}


# ===========================================================================
# 1. rarity.py — 名称归一化 / 弱匹配 / 稀有度判定
# ===========================================================================
class TestNormalize(unittest.TestCase):
    def test_strip_size_suffix(self):
        self.assertEqual(rarity_mod.normalize_name("优品豆浆大杯"), "优品豆浆")
        self.assertEqual(rarity_mod.normalize_name("可乐中杯"), "可乐")
        self.assertEqual(rarity_mod.normalize_name("麦咖啡™热美式中杯"), "麦咖啡热美式")

    def test_strip_symbols_and_quotes(self):
        self.assertEqual(rarity_mod.normalize_name("【美汁源】“黄金橙橙”"),
                         "美汁源黄金橙橙")
        self.assertEqual(rarity_mod.normalize_name("“我就喜欢”鸡薯双全盒"),
                         "我就喜欢鸡薯双全盒")
        self.assertEqual(rarity_mod.normalize_name("100% 苹果汁(盒装)"),
                         "100%苹果汁盒装")

    def test_synonyms(self):
        self.assertEqual(rarity_mod.normalize_name("可口可乐大杯"), "可乐")
        self.assertEqual(rarity_mod.normalize_name("中薯条"), "薯条")
        self.assertEqual(rarity_mod.normalize_name("大薯条"), "薯条")

    def test_menu_alias_not_in_identity(self):
        # 菜单别名（口味/槽位）不得污染身份 key
        self.assertEqual(rarity_mod.normalize_name("香芋派"), "香芋派")
        self.assertEqual(rarity_mod.match_name("香芋派"), "派")
        self.assertEqual(rarity_mod.match_name("菠萝派"), "派")

    def test_empty_and_none(self):
        self.assertEqual(rarity_mod.normalize_name(""), "")
        self.assertEqual(rarity_mod.normalize_name(None), "")


class TestWeakMatch(unittest.TestCase):
    def test_substring_match(self):
        self.assertTrue(rarity_mod.is_weak_match("麦乐鸡5块", "麦乐鸡"))
        self.assertTrue(rarity_mod.is_weak_match("4块麦乐鸡", "麦乐鸡"))

    def test_short_name_rejected(self):
        # 短边 <3 字不参与弱匹配（防「派」误吞所有 XX派）
        self.assertFalse(rarity_mod.is_weak_match("苹果派", "派"))

    def test_unrelated_rejected(self):
        self.assertFalse(rarity_mod.is_weak_match("薯条", "薯饼"))
        self.assertFalse(rarity_mod.is_weak_match("巨无霸", "麦辣鸡腿汉堡"))


class TestClassify(unittest.TestCase):
    def test_ur_when_off_sale(self):
        self.assertEqual(rarity_mod.classify("任意品", on_sale=False),
                         rarity_mod.RARITY_UR)

    def test_ssr_limited_keyword(self):
        for name in ["高达吉士双牛堡", "世界波牛堡", "泷盐星星麦旋风"]:
            self.assertEqual(rarity_mod.classify(name), rarity_mod.RARITY_SSR, name)

    def test_ssr_new_tag(self):
        self.assertEqual(
            rarity_mod.classify("马苏里拉拉丝芝士条", tags=["上新"]),
            rarity_mod.RARITY_SSR)

    def test_promo_tag_is_not_limited(self):
        # 「限定特惠」是打折而不是限定商品（回归: 4 款麦咖啡被打成 SSR）
        self.assertEqual(
            rarity_mod.classify("麦咖啡™美式", tags=["冷饮", "限定特惠"]),
            rarity_mod.RARITY_R)

    def test_period_does_not_affect_rarity(self):
        # 回归（项目诊断硬伤 1）: 时段只影响展示, 绝不能升档。
        # 旧规则「仅早餐时段 → SSR」让早餐册 55 款 100% 限定, SSR 占全池 55%。
        for periods in (None, {"breakfast"}, {"regular"}, {"regular", "breakfast"}):
            self.assertEqual(
                rarity_mod.classify("脆香油条", periods=periods),
                rarity_mod.RARITY_SR)
            self.assertEqual(
                rarity_mod.classify("图林根香肠早安营养卷", periods=periods),
                rarity_mod.RARITY_R)
        self.assertEqual(
            rarity_mod.classify("薯条", periods={"regular"}), rarity_mod.RARITY_SR)
        self.assertEqual(
            rarity_mod.classify("薯条", periods={"regular", "breakfast"}),
            rarity_mod.RARITY_SR)

    def test_sr_popular_tag(self):
        self.assertEqual(rarity_mod.classify("麦乐鸡", tags=["单品", "人气"]),
                         rarity_mod.RARITY_SR)
        self.assertEqual(rarity_mod.classify("麦辣鸡腿汉堡", tags=["人气经典"]),
                         rarity_mod.RARITY_SR)

    def test_sr_signature_exact_match(self):
        # 招牌经典款按归一化名称精确匹配, 规格变体不升档
        self.assertEqual(rarity_mod.classify("巨无霸"), rarity_mod.RARITY_SR)
        self.assertEqual(rarity_mod.classify("双层吉士汉堡"), rarity_mod.RARITY_SR)
        self.assertEqual(rarity_mod.classify("4块麦乐鸡"), rarity_mod.RARITY_R)
        self.assertEqual(rarity_mod.classify("迷你草莓新地"), rarity_mod.RARITY_R)

    def test_r_default(self):
        self.assertEqual(rarity_mod.classify("德式图林根香肠", tags=["小食"]),
                         rarity_mod.RARITY_R)
        self.assertEqual(rarity_mod.classify("苹果片", tags=["小食"]),
                         rarity_mod.RARITY_R)

    def test_rank_helper(self):
        self.assertLess(rarity_mod.rank_of("R"), rarity_mod.rank_of("SR"))
        self.assertLess(rarity_mod.rank_of("SR"), rarity_mod.rank_of("SSR"))
        self.assertLess(rarity_mod.rank_of("SSR"), rarity_mod.rank_of("UR"))
        self.assertEqual(rarity_mod.rank_of("未知"), 0)


class TestIsLimited(unittest.TestCase):
    def test_limited_by_name(self):
        self.assertTrue(rarity_mod.is_limited("高达吉士双牛堡"))
        self.assertTrue(rarity_mod.is_limited("泷运当头四件套"))

    def test_not_limited_for_new_tag(self):
        # 回归: 「上新」tag 的普通新品不入限定册（开发期缺陷 4）
        self.assertFalse(rarity_mod.is_limited("马苏里拉拉丝芝士条"))


# ===========================================================================
# 2. catalog.py — 册别归类 / 三通道匹配 / 池构建
# ===========================================================================
class TestBookOf(unittest.TestCase):
    def test_category_priority(self):
        self.assertEqual(catalog_mod.book_of("巨无霸", "巨无霸\n牛鱼肉堡"), "汉堡册")
        self.assertEqual(catalog_mod.book_of("猪柳蛋麦满分", "麦满分系列"), "早餐册")
        self.assertEqual(catalog_mod.book_of("鲜萃咖啡", "麦咖啡™"), "饮品册")
        self.assertEqual(catalog_mod.book_of("麦乐鸡套餐", "炸鸡"), "小食册")

    def test_name_fallback(self):
        self.assertEqual(catalog_mod.book_of("圆筒冰淇淋"), "甜品册")
        # 派属于甜品柜台（回归: 曾按「薯条/薯饼」规则误归小食册）
        self.assertEqual(catalog_mod.book_of("香芋派"), "甜品册")
        self.assertEqual(catalog_mod.book_of("优品豆浆"), "饮品册")
        self.assertEqual(catalog_mod.book_of("板烧鸡腿堡"), "汉堡册")
        self.assertEqual(catalog_mod.book_of("脆香油条"), "早餐册")

    def test_default_snack(self):
        self.assertEqual(catalog_mod.book_of("某个无法归类的餐品"), "小食册")

    def test_combo_detection(self):
        for name in ["板烧鸡腿堡三件套", "精选单人餐三件套", "全明星双人分享餐八件套",
                     "人气经典随心配", "薯条八重奏", "“我就喜欢”鸡薯双全盒"]:
            self.assertTrue(catalog_mod.combo_of(name), name)
        for name in ["板烧鸡腿堡", "薯条", "脆香油条", "纯牛奶(盒装)", "巨无霸"]:
            self.assertFalse(catalog_mod.combo_of(name), name)
        # 分类是套餐专区时, 即使名字看不出也要拦掉
        self.assertTrue(catalog_mod.combo_of("某件东西", category="精选单人餐"))

    def test_merch_detection(self):
        self.assertTrue(catalog_mod.is_merch("“葱不求人“按摩捶痒痒挠"))
        self.assertTrue(catalog_mod.is_merch("薯条脆卜卜毛绒周边"))
        self.assertFalse(catalog_mod.is_merch("薯条"))


class TestCatalogMatching(unittest.TestCase):
    def setUp(self):
        self.cat = catalog_mod.Catalog()
        self.cat.absorb_menu(_menu_payload([
            ("4810", "薯条"), ("1406", "板烧鸡腿堡"), ("1401", "麦乐鸡"),
            ("1088", "优品豆浆"), ("9900015165", "派"),
        ]), period="regular", store="T1")

    def test_channel1_code_exact(self):
        self.assertEqual(self.cat.match("4810", "随便"), ("4810", "code"))

    def test_channel2_name_normalized(self):
        # 订单侧 code 501205 不在池, 名称「中薯条」经同义词 → 薯条
        matched, how = self.cat.match("501205", "中薯条")
        self.assertEqual(matched, "4810")
        self.assertEqual(how, "name")

    def test_channel3_weak(self):
        matched, how = self.cat.match("999999", "麦乐鸡5块")
        self.assertEqual(matched, "1401")
        self.assertEqual(how, "weak")

    def test_channel_alias(self):
        # 「香芋派」经菜单别名命中通用槽位「派」
        matched, how = self.cat.match("999999", "香芋派")
        self.assertEqual(matched, "9900015165")
        self.assertEqual(how, "alias")
        self.assertTrue(self.cat.is_on_sale("999999", "菠萝派"))

    def test_miss_returns_none(self):
        self.assertEqual(self.cat.match("1", "泰式炭烤风味猪猪堡"), (None, None))

    def test_is_on_sale(self):
        self.assertTrue(self.cat.is_on_sale("999", "香芋派"))     # 同义词 → 派
        self.assertFalse(self.cat.is_on_sale("999", "泰式炭烤风味猪猪堡"))


class TestCatalogBuild(unittest.TestCase):
    def test_merge_periods(self):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("A1", "脆薯饼")]), period="regular")
        cat.absorb_menu(_menu_payload([("A1", "脆薯饼")]), period="breakfast")
        self.assertEqual(set(cat.products["A1"]["periods"]), {"regular", "breakfast"})

    def test_idempotent_size(self):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("A1", "巨无霸"), ("A2", "薯条")]))
        cat.absorb_menu(_menu_payload([("A1", "巨无霸"), ("A2", "薯条")]))
        self.assertEqual(len(cat), 2)

    def test_tags_merged(self):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("A1", "麦乐鸡")],
                                      period_tags={"A1": ["单品"]}))
        cat.absorb_menu(_menu_payload([("A1", "麦乐鸡")],
                                      period_tags={"A1": ["人气"]}),
                        period="breakfast")
        self.assertEqual(set(cat.products["A1"]["tags"]), {"单品", "人气"})

    def test_duplicate_name_multiple_codes(self):
        # 同名不同 code（真实数据里「派」「脆薯饼」都有两个编码）→ 合并成一格,
        # 否则图鉴墙会出现两个一模一样的格子, 分母也虚高。
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("A1", "脆薯饼"), ("A2", "脆薯饼")]))
        self.assertEqual(len(cat), 1)
        self.assertEqual(len(cat.name_index["脆薯饼"]), 1)
        merged = next(iter(cat.products.values()))
        self.assertEqual(merged["merged_codes"], ["A2"])

    def test_combo_excluded_from_pool(self):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([
            ("B1", "板烧鸡腿堡"), ("B2", "板烧鸡腿堡三件套"),
            ("B3", "人气经典随心配"), ("B4", "麦乐鸡泡泡机（小红帽款）"),
        ]))
        self.assertEqual(list(cat.products), ["B1"])
        self.assertIn("板烧鸡腿堡三件套", cat.last_skipped_combos)
        self.assertIn("麦乐鸡泡泡机（小红帽款）", cat.last_skipped_merch)

    def test_all_combo_payload_rejected(self):
        cat = catalog_mod.Catalog()
        with self.assertRaises(catalog_mod.CatalogPayloadError):
            cat.absorb_menu(_menu_payload([("C1", "麦乐鸡套餐")]))
        self.assertEqual(len(cat), 0)

    def test_real_snapshot_pool(self):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_load_example("menu-regular.json"), period="regular")
        cat.absorb_menu(_load_example("menu-breakfast.json"), period="breakfast")
        # 单品池: 148 个 SKU 里 70+ 个是套餐/周边, 真正的单品 76 款
        self.assertGreater(len(cat), 70)
        self.assertLess(len(cat), 110)
        pool = cat.pool_by_book()
        for book in catalog_mod.BOOKS:
            self.assertIn(book, pool)
        # 池内不得残留套餐
        for entry in cat.products.values():
            self.assertFalse(catalog_mod.combo_of(entry["name"]), entry["name"])

    def test_failed_or_empty_menu_response_is_rejected(self):
        cat = catalog_mod.Catalog()
        with self.assertRaises(catalog_mod.CatalogPayloadError):
            cat.absorb_menu({"success": False, "message": "鉴权失败"})
        with self.assertRaises(catalog_mod.CatalogPayloadError):
            cat.absorb_menu({"success": True, "data": {
                "categories": [], "meals": {}}})
        self.assertEqual(len(cat), 0)

    def test_malformed_menu_preserves_existing_state(self):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("OLD", "薯条")]))
        before = copy.deepcopy(cat.__dict__)
        valid = _menu_payload([("NEW", "巨无霸")])
        cases = [None, [], "{", {"data": []},
                 {"success": False, "data": valid["data"]},
                 {"code": 401, "data": valid["data"]}]
        for field in ("categories", "meals"):
            for value in (None, 0, "bad"):
                bad = copy.deepcopy(valid)
                bad["data"][field] = value
                cases.append(bad)
            bad = copy.deepcopy(valid)
            del bad["data"][field]
            cases.append(bad)
        for category in (None, {"name": 1}, {"name": "bad", "meals": "bad"},
                         {"name": "bad", "meals": [None]},
                         {"name": "bad", "meals": [{"code": 1}]},
                         {"name": "bad", "meals": [{"code": "NEW", "tags": [{}]}]}):
            bad = copy.deepcopy(valid)
            bad["data"]["categories"].append(category)
            cases.append(bad)
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(catalog_mod.CatalogPayloadError):
                    cat.absorb_menu(payload)
                self.assertEqual(cat.__dict__, before)

    def test_structured_response_without_status_fields_is_supported(self):
        payload = _menu_payload([("A1", "薯条")])
        del payload["success"]
        cat = catalog_mod.Catalog()
        cat.absorb_menu(payload)
        self.assertTrue(cat.is_on_sale("A1", "薯条"))

    def test_latest_snapshot_replaces_same_store_period(self):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("OLD", "旧款堡"), ("KEEP", "薯条")]),
                        period="regular", store="S1", fetched_at="2026-01-01")
        cat.absorb_menu(_menu_payload([("KEEP", "薯条"), ("NEW", "新品堡")]),
                        period="regular", store="S1", fetched_at="2026-02-01")
        self.assertNotIn("OLD", cat.products)
        self.assertIn("NEW", cat.products)
        self.assertEqual(len(cat.sources), 1)

    def test_different_store_snapshots_form_current_union(self):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("A", "甲店限定")]), store="S1")
        cat.absorb_menu(_menu_payload([("B", "乙店限定")]), store="S2")
        self.assertEqual(set(cat.products), {"A", "B"})
        cat.absorb_menu(_menu_payload([("C", "甲店新品")]), store="S1")
        self.assertEqual(set(cat.products), {"B", "C"})


# ===========================================================================
# 3. CodexStore — 收录 / 幂等 / 取消单 / 同品合并 / UR 复活
# ===========================================================================
class TestAbsorbOrder(unittest.TestCase):
    def setUp(self):
        self.cat = catalog_mod.Catalog()
        self.cat.absorb_menu(_menu_payload([
            ("4810", "薯条"), ("1401", "麦乐鸡"), ("9900008751", "可乐"),
            ("521316", "高达吉士双牛堡"), ("1088", "优品豆浆"),
            ("9900015165", "派"),
        ]), period="regular")
        self.store = codex_mod.CodexStore()

    def test_combo_expanded_to_units(self):
        order = _order("O1", "订单已完成", [
            ("9900013476", "随心配1+1", 1, [("521316", "高达吉士双牛堡", 1),
                                            ("4810", "中薯条", 1)])])
        new, _ = self.store.absorb_order(order, self.cat)
        names = sorted(i["name"] for i in new)
        self.assertEqual(names, ["薯条", "高达吉士双牛堡"])
        # 组合餐父项（随心配1+1）不应单独成条目
        self.assertNotIn("随心配1+1", [i["name"] for i in new])

    def test_single_item_without_combo(self):
        order = _order("O2", "订单已完成", [("4810", "薯条", 2, None)])
        new, _ = self.store.absorb_order(order, self.cat)
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["count"], 2)

    def test_cancelled_order_skipped(self):
        order = _order("O3", "订单已取消", [("4810", "薯条", 1, None)])
        new, _ = self.store.absorb_order(order, self.cat)
        self.assertEqual(new, [])
        self.assertEqual(len(self.store.items), 0)
        self.assertIn("O3", self.store.orders_seen)  # 记 seen 防重扫

    def test_duplicate_order_idempotent(self):
        order = _order("O4", "订单已完成", [("4810", "薯条", 1, None)])
        self.store.absorb_order(order, self.cat)
        new2, _ = self.store.absorb_order(order, self.cat)
        self.assertEqual(new2, [])
        self.assertEqual(self.store.items["4810"]["count"], 1)

    def test_count_accumulates_within_order(self):
        order = _order("O5", "订单已完成", [("4810", "薯条", 8, None)])
        self.store.absorb_order(order, self.cat)
        self.assertEqual(self.store.items["4810"]["count"], 8)

    def test_same_product_different_codes_merged(self):
        # 回归: 同品分裂（开发期缺陷 1）
        # 中薯条 501205 → 薯条(4810), 大薯条 501206 → 薯条(4810)
        order = _order("O6", "订单已完成", [
            ("P", "套餐", 1, [("501205", "中薯条", 1), ("501206", "大薯条", 1)])])
        self.store.absorb_order(order, self.cat)
        self.assertEqual(len(self.store.items), 1)
        self.assertEqual(self.store.items["4810"]["name"], "薯条")
        self.assertEqual(self.store.items["4810"]["count"], 2)

    def test_menu_slot_dedup_within_flavor(self):
        # 同一口味、两个不同订单 code → 合并为一条
        order = _order("O7", "订单已完成", [
            ("P", "套餐", 1, [("4106", "香芋派", 1), ("904106", "香芋派", 1)])])
        self.store.absorb_order(order, self.cat)
        self.assertEqual(len(self.store.items), 1)
        item = list(self.store.items.values())[0]
        self.assertEqual(item["count"], 2)
        self.assertNotEqual(item["rarity"], "UR")

    def test_flavors_merge_to_menu_slot(self):
        # 有图鉴池: 香芋派/菠萝派统一点亮菜单槽位「派」（与图鉴格位口径一致）
        order = _order("O8", "订单已完成", [
            ("P", "套餐", 1, [("4106", "香芋派", 1), ("4110", "菠萝派", 1)])])
        self.store.absorb_order(order, self.cat)
        self.assertEqual(len(self.store.items), 1)
        item = list(self.store.items.values())[0]
        self.assertEqual(item["name"], "派")
        self.assertEqual(item["count"], 2)

    def test_flavors_not_merged_without_catalog(self):
        # 无图鉴池（降级）: 口味不得混为一条, 各自保留真实名称
        store = codex_mod.CodexStore()
        order = _order("O9", "订单已完成", [
            ("P", "套餐", 1, [("4106", "香芋派", 1), ("4110", "菠萝派", 1)])])
        store.absorb_order(order, None)
        self.assertEqual(len(store.items), 2)
        self.assertEqual({i["name"] for i in store.items.values()},
                         {"香芋派", "菠萝派"})

    def test_stores_aggregated(self):
        for i in range(3):
            self.store.absorb_order(_order("S%d" % i, "订单已完成",
                                           [("4810", "薯条", 1, None)]), self.cat)
        self.assertEqual(len(self.store.stores), 1)
        self.assertEqual(list(self.store.stores.values())[0]["visits"], 3)

    def test_first_unlock_kept_on_rebuy(self):
        self.store.absorb_order(_order("T1", "订单已完成", [("4810", "薯条", 1, None)],
                                       create_time="2026-08-01 10:00:00"), self.cat)
        self.store.absorb_order(_order("T2", "订单已完成", [("4810", "薯条", 1, None)],
                                       create_time="2026-10-01 10:00:00"), self.cat)
        self.assertEqual(self.store.items["4810"]["first_unlock"], "2026-08-01 10:00:00")
        self.assertEqual(self.store.items["4810"]["count"], 2)

    def test_ur_marked_for_off_menu(self):
        order = _order("U1", "订单已完成", [("521879", "泰式炭烤风味猪猪堡", 1, None)])
        self.store.absorb_order(order, self.cat)
        self.assertEqual(self.store.items["n:泰式炭烤风味猪猪堡"]["rarity"], "UR")

    def test_no_catalog_degradation(self):
        # 无图鉴池时仍可收录（降级：按名称归一化聚合, 稀有度暂记 R）
        order = _order("N1", "订单已完成", [("4106", "香芋派", 1, None)])
        new, _ = self.store.absorb_order(order, None)
        self.assertEqual(len(new), 1)
        self.assertIn("n:香芋派", self.store.items)


class TestReclassifyRevive(unittest.TestCase):
    def test_empty_catalog_preserves_existing_rarity(self):
        store = codex_mod.CodexStore()
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("A1", "薯条")]))
        store.absorb_order(_order("O1", "订单已完成", [("A1", "薯条", 1, None)]), cat)
        before = copy.deepcopy(store.items)
        self.assertEqual(store.reclassify(catalog_mod.Catalog()), [])
        self.assertEqual(store.items, before)

    def test_ur_revives_when_menu_reappears(self):
        store = codex_mod.CodexStore()
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("4810", "薯条")]), period="regular")
        store.absorb_order(_order("R1", "订单已完成",
                                  [("521316", "高达吉士双牛堡", 1, None)]), cat)
        key = "n:高达吉士双牛堡"
        self.assertEqual(store.items[key]["rarity"], "UR")

        # 菜单池更新后该品回归，条目同时迁移到标准 catalog code。
        cat.absorb_menu(_menu_payload([("521316", "高达吉士双牛堡")]), period="regular")
        revived = store.reclassify(cat)
        self.assertIn("高达吉士双牛堡", revived)
        self.assertNotIn(key, store.items)
        self.assertEqual(store.items["521316"]["rarity"], rarity_mod.RARITY_SSR)

    def test_no_catalog_item_migrates_and_merges_without_duplication(self):
        store = codex_mod.CodexStore()
        store.absorb_order(_order("M1", "订单已完成",
                                  [("501205", "中薯条", 2, None)]), None)
        self.assertIn("n:薯条", store.items)
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("4810", "薯条")]), store="S1")
        store.reclassify(cat)
        self.assertEqual(set(store.items), {"4810"})
        store.absorb_order(_order("M2", "订单已完成",
                                  [("4810", "薯条", 1, None)]), cat)
        self.assertEqual(set(store.items), {"4810"})
        self.assertEqual(store.items["4810"]["count"], 3)

    def test_reclassify_merges_existing_standard_and_temporary_keys(self):
        store = codex_mod.CodexStore()
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("4810", "薯条")]), store="S1")
        store.absorb_order(_order("M3", "订单已完成", [("4810", "薯条", 1, None)]), cat)
        store.items["n:薯条"] = {
            "name": "中薯条", "book": "小食册", "rarity": "R",
            "first_unlock": "2025-01-01 10:00:00", "store": "旧店",
            "count": 2, "image": "", "catalog_code": "",
        }
        store.reclassify(cat)
        self.assertEqual(set(store.items), {"4810"})
        self.assertEqual(store.items["4810"]["count"], 3)
        self.assertEqual(store.items["4810"]["first_unlock"], "2025-01-01 10:00:00")


class TestStats(unittest.TestCase):
    def _store_with(self, n_items):
        store = codex_mod.CodexStore()
        for i in range(n_items):
            store.items["k%d" % i] = {
                "name": "测试品%d" % i, "book": "小食册", "rarity": "R",
                "first_unlock": "2026-10-01 12:00:00", "store": "S",
                "count": 1, "image": "", "catalog_code": ""}
        return store

    def test_level_boundaries(self):
        cases = [(0, 1, "麦门新客"), (9, 1, "麦门新客"), (10, 2, "常客"),
                 (29, 2, "常客"), (30, 3, "老饕"), (59, 3, "老饕"),
                 (60, 4, "品鉴家"), (99, 4, "品鉴家"), (100, 5, "麦门图鉴大师")]
        for n, lv, title in cases:
            s = self._store_with(n).stats()
            self.assertEqual((s["level"], s["title"]), (lv, title), "n=%d" % n)

    def test_badge_ur_hunter(self):
        store = self._store_with(1)
        store.items["k0"]["rarity"] = "UR"
        self.assertIn("💎 绝版猎人", store.stats()["badges"])

    def test_badge_limited_collector(self):
        store = self._store_with(3)
        for i in range(3):
            store.items["k%d" % i]["rarity"] = "SSR"
        self.assertIn("✨ 限定收藏家", store.stats()["badges"])

    def test_badge_route_traveller(self):
        store = self._store_with(1)
        for i in range(10):
            store.stores["s%d" % i] = {"name": "店%d" % i, "visits": 1}
        self.assertIn("🗺️ 环游麦门", store.stats()["badges"])

    def test_favorite_and_treasure(self):
        store = self._store_with(3)
        store.items["k1"]["count"] = 9
        store.items["k2"]["rarity"] = "UR"
        s = store.stats()
        self.assertEqual(s["favorite"]["name"], "测试品1")
        self.assertEqual(s["treasure"]["name"], "测试品2")


# ===========================================================================
# 4. render.py — 图鉴与分享卡
# ===========================================================================
class TestRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = codex_mod.CodexStore()
        cls.cat = catalog_mod.Catalog()
        cls.cat.absorb_menu(_load_example("menu-regular.json"), period="regular")
        cls.cat.absorb_menu(_load_example("menu-breakfast.json"), period="breakfast")
        for order in codex_mod.extract_orders(_load_example("order-list.json")):
            cls.store.absorb_order(order, cls.cat)
        cls.store.reclassify(cls.cat)

    def test_markdown_contains_sections(self):
        md = render_mod.render_markdown(self.store, self.cat)
        for book in catalog_mod.BOOKS:
            self.assertIn(book, md)
        self.assertIn("麦麦图鉴", md)
        self.assertIn("绝版", md)
        self.assertIn("???", md.replace("？？", "??").replace("??？", "???"))

    def test_share_card_placeholders_replaced(self):
        out = os.path.join(tempfile.gettempdir(), "mcd-test-card.html")
        tpl = os.path.join(ROOT, "assets", "templates", "share-card.html")
        render_mod.render_share_card(self.store, self.cat, tpl, out)
        with open(out, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("{{", html, "存在未替换的模板占位符")
        self.assertIn("麦麦图鉴", html)
        self.assertIn("常客", html)
        os.remove(out)

    def test_share_card_default_template_from_any_cwd(self):
        # 模板参数缺省/路径失效时, 按脚本相对路径回退（不依赖 cwd）
        out = os.path.join(tempfile.gettempdir(), "mcd-test-card2.html")
        old_cwd = os.getcwd()
        os.chdir(tempfile.gettempdir())
        try:
            render_mod.render_share_card(self.store, self.cat, None, out)
            render_mod.render_share_card(self.store, self.cat,
                                         "不存在的/模板.html", out)
        finally:
            os.chdir(old_cwd)
        with open(out, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("{{", html)
        os.remove(out)

    def test_default_template_path_exists(self):
        self.assertTrue(os.path.exists(render_mod.default_template_path()))

    def test_render_without_catalog(self):
        md = render_mod.render_markdown(self.store, None)
        self.assertIn("麦麦图鉴", md)

    def test_share_card_escapes_dynamic_text(self):
        store = codex_mod.CodexStore()
        store.items["x"] = {
            "name": '<script>alert("x")</script>', "book": "小食册", "rarity": "UR",
            "first_unlock": "2026-01-01 00:00:00", "store": "S", "count": 1,
            "image": "", "catalog_code": "",
        }
        out = os.path.join(tempfile.gettempdir(), "mcd-test-escape-card.html")
        render_mod.render_share_card(store, None, None, out)
        with open(out, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn('<script>alert("x")</script>', html)
        self.assertIn("&lt;script&gt;", html)
        os.remove(out)

    def test_markdown_progress_is_capped_at_100(self):
        store = codex_mod.CodexStore()
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("A", "薯条")]), store="S1")
        for i in range(2):
            store.items["x%d" % i] = {
                "name": "小食%d" % i, "book": "小食册", "rarity": "UR",
                "first_unlock": "2026-01-01 00:00:00", "store": "S", "count": 1,
                "image": "", "catalog_code": "",
            }
        md = render_mod.render_markdown(store, cat)
        self.assertIn("100%", md)
        self.assertNotIn("200%", md)


# ===========================================================================
# 5. CLI 集成 — 子命令端到端
# ===========================================================================
class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mcd-cli-")
        self.cat = os.path.join(self.tmp, "catalog.json")
        self.cdx = os.path.join(self.tmp, "codex.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, argv):
        import io
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            self.last_exit_code = codex_mod.main(argv)
        finally:
            sys.stdout = old
        return json.loads(buf.getvalue())

    def test_full_pipeline(self):
        r1 = self._run(["absorb-menu", "--menu",
                        os.path.join(EXAMPLES, "menu-regular.json"),
                        "--catalog", self.cat, "--period", "regular"])
        self.assertGreater(r1["pool_size"], 40)
        self.assertGreater(r1["skipped_combos"], 0)
        self._run(["absorb-menu", "--menu",
                   os.path.join(EXAMPLES, "menu-breakfast.json"),
                   "--catalog", self.cat, "--period", "breakfast"])
        r3 = self._run(["sync", "--orders", os.path.join(EXAMPLES, "order-list.json"),
                        "--codex", self.cdx, "--catalog", self.cat])
        self.assertGreater(len(r3["new_unlocks"]), 5)
        self.assertGreater(r3["stats"]["unlocked"], 5)
        r4 = self._run(["stats", "--codex", self.cdx, "--catalog", self.cat])
        self.assertEqual(r4["stats"]["unlocked"], r3["stats"]["unlocked"])

    def test_sync_idempotent_via_cli(self):
        self._run(["absorb-menu", "--menu",
                   os.path.join(EXAMPLES, "menu-regular.json"),
                   "--catalog", self.cat, "--period", "regular"])
        args = ["sync", "--orders", os.path.join(EXAMPLES, "order-list.json"),
                "--codex", self.cdx, "--catalog", self.cat]
        first = self._run(args)
        second = self._run(args)
        self.assertEqual(second["new_unlocks"], [])
        self.assertEqual(second["stats"]["unlocked"], first["stats"]["unlocked"])

    def test_render_outputs(self):
        self._run(["absorb-menu", "--menu",
                   os.path.join(EXAMPLES, "menu-regular.json"),
                   "--catalog", self.cat, "--period", "regular"])
        self._run(["sync", "--orders", os.path.join(EXAMPLES, "order-list.json"),
                   "--codex", self.cdx, "--catalog", self.cat])
        md = os.path.join(self.tmp, "out", "codex.md")
        card = os.path.join(self.tmp, "out", "card.html")
        wall = os.path.join(self.tmp, "out", "codex-wall.html")
        # 不传 --template, 验证默认模板回落（skill 从任意 cwd 运行的场景）
        r = self._run(["render", "--codex", self.cdx, "--catalog", self.cat,
                       "--out-md", md, "--out-card", card, "--out-wall", wall])
        self.assertTrue(os.path.exists(md) and os.path.exists(card))
        self.assertTrue(os.path.exists(wall))
        self.assertEqual(set(r["outputs"]),
                         {"markdown", "share_card", "codex_wall"})

    def test_stats_on_missing_codex(self):
        # 首次运行: codex 不存在 → 空图鉴, 不报错
        r = self._run(["stats", "--codex", self.cdx])
        self.assertEqual(r["stats"]["unlocked"], 0)
        self.assertEqual(r["stats"]["title"], "麦门新客")

    def test_sync_without_catalog_does_not_mark_items_ur(self):
        # 菜单池缺失时按降级模式收录，不能把所有历史餐品误判为绝版。
        r = self._run(["sync", "--orders", os.path.join(EXAMPLES, "order-list.json"),
                       "--codex", self.cdx, "--catalog", self.cat])
        self.assertGreater(r["stats"]["unlocked"], 0)
        self.assertEqual(r["stats"]["ur_count"], 0)
        catalog_mod.Catalog().save(self.cat)
        r = self._run(["sync", "--orders", os.path.join(EXAMPLES, "order-list.json"),
                       "--codex", os.path.join(self.tmp, "empty-pool-codex.json"),
                       "--catalog", self.cat])
        self.assertGreater(r["stats"]["unlocked"], 0)
        self.assertEqual(r["stats"]["ur_count"], 0)

    def test_cli_reports_failed_menu_without_overwriting_catalog(self):
        bad = os.path.join(self.tmp, "bad-menu.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"success": False, "message": "鉴权失败"}, f)
        r = self._run(["absorb-menu", "--menu", bad, "--catalog", self.cat])
        self.assertFalse(r["ok"])
        self.assertEqual(self.last_exit_code, 2)
        self.assertFalse(os.path.exists(self.cat))
        self._run(["absorb-menu", "--menu", os.path.join(EXAMPLES, "menu-regular.json"),
                   "--catalog", self.cat])
        with open(self.cat, "rb") as f:
            before = f.read()
        for payload in ('{"success": false}', '{', '{"data": {"categories": []}}'):
            with self.subTest(payload=payload):
                with open(bad, "w", encoding="utf-8") as f:
                    f.write(payload)
                r = self._run(["absorb-menu", "--menu", bad, "--catalog", self.cat])
                self.assertFalse(r["ok"])
                self.assertEqual(self.last_exit_code, 2)
                with open(self.cat, "rb") as f:
                    self.assertEqual(f.read(), before)

    def test_failed_breakfast_batch_preserves_catalog_and_exit_code(self):
        self._run(["absorb-menu", "--menu", os.path.join(EXAMPLES, "menu-regular.json"),
                   "--catalog", self.cat])
        with open(self.cat, "rb") as f:
            before = f.read()
        menu = os.path.join(self.tmp, "new-menu.json")
        bad = os.path.join(self.tmp, "bad-breakfast.json")
        with open(menu, "w", encoding="utf-8") as f:
            json.dump(_menu_payload([("NEW", "新餐品")]), f)
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"success": False}, f)
        result = subprocess.run([
            sys.executable, os.path.join(ROOT, "scripts", "codex.py"), "absorb-menu",
            "--menu", menu, "--breakfast-menu", bad, "--catalog", self.cat,
        ], capture_output=True, encoding="utf-8", cwd=self.tmp)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)["ok"])
        self.assertEqual(result.stderr, "")
        with open(self.cat, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_valid_menu_batch_saves_both_periods(self):
        r = self._run(["absorb-menu", "--menu", os.path.join(EXAMPLES, "menu-regular.json"),
                       "--breakfast-menu", os.path.join(EXAMPLES, "menu-breakfast.json"),
                       "--catalog", self.cat, "--store", "DEMO"])
        self.assertTrue(r["ok"])
        self.assertEqual(self.last_exit_code, 0)
        cat = catalog_mod.Catalog.load(self.cat)
        self.assertEqual({s["period"] for s in cat.sources}, {"regular", "breakfast"})
        self.assertEqual(len(cat), 76)

    def test_default_paths_rooted_at_project_root(self):
        # 回归 P2: CLI 默认路径锚定脚本上级目录, 而非 cwd
        parser = codex_mod.build_parser()
        args = parser.parse_args(["stats"])
        self.assertTrue(args.codex.startswith(codex_mod.ROOT))
        self.assertTrue(args.catalog.startswith(codex_mod.ROOT))
        args = parser.parse_args(["render"])
        self.assertTrue(args.out_md.startswith(codex_mod.ROOT))
        self.assertTrue(args.out_card.startswith(codex_mod.ROOT))

    def test_cli_runs_from_other_cwd(self):
        # 回归 P2: 从仓库以外的工作目录执行, 默认路径仍可解析（只读命令）
        old = os.getcwd()
        os.chdir(tempfile.gettempdir())
        try:
            r = self._run(["stats"])
            self.assertIn("stats", r)
        finally:
            os.chdir(old)

    def test_extract_orders_shapes(self):
        self.assertEqual(codex_mod.extract_orders({"data": {"list": [{"a": 1}]}}),
                         [{"a": 1}])
        self.assertEqual(codex_mod.extract_orders([{"b": 2}]), [{"b": 2}])
        # 单订单形态（含 orderProductList 键）→ 包成单元素列表
        single = {"orderProductList": []}
        self.assertEqual(codex_mod.extract_orders(single), [single])
        self.assertEqual(codex_mod.extract_orders({"data": {}}), [])


# ===========================================================================
# 6. 真实数据回归 — examples 全量
# ===========================================================================
class TestRealDataRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = codex_mod.CodexStore()
        cls.cat = catalog_mod.Catalog()
        cls.cat.absorb_menu(_load_example("menu-regular.json"), period="regular")
        cls.cat.absorb_menu(_load_example("menu-breakfast.json"), period="breakfast")
        cls.orders = codex_mod.extract_orders(_load_example("order-list.json"))
        for order in cls.orders:
            cls.store.absorb_order(order, cls.cat)
        cls.store.reclassify(cls.cat)
        cls.stats = cls.store.stats(cls.cat)

    def test_cancelled_order_excluded(self):
        # 取消单中的「韩式甜辣酱鸡块」「麦辣大四角」不得进入图鉴
        names = [i["name"] for i in self.store.items.values()]
        self.assertNotIn("韩式甜辣酱鸡块", names)
        self.assertNotIn("麦辣大四角", names)

    def test_ur_detection_accuracy(self):
        ur_names = {i["name"] for i in self.store.items.values()
                    if i["rarity"] == "UR"}
        self.assertIn("培根蔬萃双层牛堡", ur_names)
        self.assertIn("泰式炭烤风味猪猪堡", ur_names)
        # 早餐品不得误判 UR（回归: 开发期缺陷 3 的同类风险）
        self.assertNotIn("图林根香肠早安营养卷", ur_names)
        self.assertNotIn("脆香油条", ur_names)
        # 菜单通用名「派」不得误判 UR
        self.assertNotIn("派", ur_names)

    def test_same_product_merged(self):
        # 薯条合并: 501205 中薯条×2 + 4810 中薯条×(1+8) + 501206 大薯条×2 = 13
        self.assertIn("4810", self.store.items)
        self.assertEqual(self.store.items["4810"]["name"], "薯条")
        self.assertEqual(self.store.items["4810"]["count"], 13)

    def test_book_assignment(self):
        books = {i["name"]: i["book"] for i in self.store.items.values()}
        self.assertEqual(books["薯条"], "小食册")
        self.assertEqual(books["可乐"], "饮品册")
        self.assertEqual(books["麦辣鸡腿汉堡"], "汉堡册")
        self.assertEqual(books["图林根香肠早安营养卷"], "早餐册")
        self.assertEqual(books["高达吉士双牛堡"], "限定册")

    def test_stats_sane(self):
        self.assertEqual(self.stats["unlocked"], len(self.store.items))
        self.assertGreater(self.stats["pool_total"], 70)
        self.assertGreaterEqual(self.stats["ur_count"], 2)
        self.assertEqual(self.stats["store_count"], 5)
        self.assertIn("💎 绝版猎人", self.stats["badges"])
        self.assertIsNotNone(self.stats["favorite"])
        self.assertEqual(self.stats["treasure"]["rarity"], "UR")
        self.assertEqual(self.stats["completion"],
                         int(round(self.stats["unlocked"] * 100 /
                                   self.stats["pool_total"])))

    def test_resync_stability(self):
        before = len(self.store.items)
        for order in self.orders:
            self.store.absorb_order(order, self.cat)
        self.assertEqual(len(self.store.items), before)


# ===========================================================================
# 7. 稀有度分布 — 收集玩法的地基（越稀有越少）
# ===========================================================================
class TestRarityBalance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_load_example("menu-regular.json"), period="regular")
        cat.absorb_menu(_load_example("menu-breakfast.json"), period="breakfast")
        cls.cat = cat
        cls.pool = cat.pool_by_book()

    def test_gradient_is_monotonic(self):
        """R 最多, SR 次之, SSR 最少 —— 一旦倒挂, 「稀有」就失去意义。"""
        counts = {r: 0 for r in ("R", "SR", "SSR")}
        for entry in self.cat.products.values():
            counts[entry["rarity"]] = counts.get(entry["rarity"], 0) + 1
        self.assertGreater(counts["R"], counts["SR"], counts)
        self.assertGreater(counts["SR"], counts["SSR"], counts)

    def test_ssr_ratio_in_range(self):
        # 诊断要求: SSR 回落到 10%~15%（旧规则是 55%）
        total = len(self.cat)
        ssr = sum(1 for e in self.cat.products.values() if e["rarity"] == "SSR")
        ratio = ssr / float(total)
        self.assertGreaterEqual(ratio, 0.04)
        self.assertLessEqual(ratio, 0.18)

    def test_sr_ratio_in_range(self):
        total = len(self.cat)
        sr = sum(1 for e in self.cat.products.values() if e["rarity"] == "SR")
        ratio = sr / float(total)
        self.assertGreaterEqual(ratio, 0.15)
        self.assertLessEqual(ratio, 0.32)

    def test_breakfast_book_is_not_all_limited(self):
        # 回归（硬伤 1）: 早餐册曾 100% 是「限定款金色」
        breakfast = self.pool[catalog_mod.BOOK_BREAKFAST]
        self.assertGreater(len(breakfast), 10)
        ssr = sum(1 for e in breakfast.values() if e["rarity"] == "SSR")
        self.assertLessEqual(ssr / float(len(breakfast)), 0.2)

    def test_no_book_is_dominated_by_ssr(self):
        # 限定册按定义全是限定款, 不参与这条检查
        for book, entries in self.pool.items():
            if not entries or book == catalog_mod.BOOK_LIMITED:
                continue
            ssr = sum(1 for e in entries.values() if e["rarity"] == "SSR")
            self.assertLess(ssr / float(len(entries)), 0.4, book)

    def test_single_item_pool_has_no_combo(self):
        for entry in self.cat.products.values():
            self.assertFalse(catalog_mod.combo_of(entry["name"]), entry["name"])


# ===========================================================================
# 8. 图鉴格子墙 — 核心视觉交付物
# ===========================================================================
class TestCodexWall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = codex_mod.CodexStore()
        cls.cat = catalog_mod.Catalog()
        cls.cat.absorb_menu(_load_example("menu-regular.json"), period="regular")
        cls.cat.absorb_menu(_load_example("menu-breakfast.json"), period="breakfast")
        for order in codex_mod.extract_orders(_load_example("order-list.json")):
            cls.store.absorb_order(order, cls.cat)
        cls.store.reclassify(cls.cat)
        cls.tmp = tempfile.mkdtemp(prefix="mcd-wall-")
        cls.path = os.path.join(cls.tmp, "wall.html")
        render_mod.render_codex_wall(cls.store, cls.cat, None, cls.path)
        with open(cls.path, "r", encoding="utf-8") as f:
            cls.html = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_placeholders_replaced(self):
        self.assertNotIn("{{", self.html)

    def test_every_pool_item_gets_a_cell(self):
        self.assertEqual(self.html.count("<figure class=\"cell"),
                         len(self.cat))

    def test_lit_and_locked_partition_the_pool(self):
        lit = self.html.count("class=\"cell lit")
        locked = self.html.count("class=\"cell locked")
        self.assertEqual(lit + locked, len(self.cat))
        self.assertGreaterEqual(lit, 10)

    def test_locked_cells_show_silhouette_and_question_marks(self):
        self.assertIn("???", self.html)
        self.assertIn('class="sil"', self.html)   # 剪影用的官方图
        self.assertNotIn("??？", self.html)       # 旧版半角+全角混排 bug

    def test_products_have_real_images(self):
        self.assertIn("https://menu-img.mcd.cn", self.html)
        self.assertIn('<img class="pic"', self.html)

    def test_ur_hall_rendered(self):
        self.assertIn("绝版殿堂", self.html)
        self.assertIn("绝版款", self.html)
        self.assertEqual(self.html.count('class="ur-card"'), len(
            [i for i in self.store.items.values() if i["rarity"] == "UR"]))

    def test_book_sections_and_nav(self):
        for book in catalog_mod.BOOKS:
            self.assertIn(book, self.html)
        self.assertEqual(self.html.count("<section class=\"book\""),
                         len(catalog_mod.BOOKS))

    def test_wall_escapes_dynamic_text(self):
        store = codex_mod.CodexStore()
        store.items["x"] = {
            "name": '<img src=x onerror=alert(1)>', "book": "汉堡册",
            "rarity": "SSR", "first_unlock": "2026-01-01 00:00:00",
            "store": "S", "count": 1,
            "image": "javascript:alert(1)", "catalog_code": "",
        }
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("X", "某堡")]), store="S1")
        out = os.path.join(self.tmp, "escape-wall.html")
        render_mod.render_codex_wall(store, cat, None, out)
        with open(out, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("onerror=alert(1)", html)
        self.assertNotIn("javascript:alert(1)", html)


# ===========================================================================
# 9. Markdown 图鉴 — 进度条与图片
# ===========================================================================
class TestMarkdownVisual(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = codex_mod.CodexStore()
        cls.cat = catalog_mod.Catalog()
        cls.cat.absorb_menu(_load_example("menu-regular.json"), period="regular")
        cls.cat.absorb_menu(_load_example("menu-breakfast.json"), period="breakfast")
        for order in codex_mod.extract_orders(_load_example("order-list.json")):
            cls.store.absorb_order(order, cls.cat)
        cls.store.reclassify(cls.cat)
        cls.md = render_mod.render_markdown(cls.store, cls.cat)

    def test_no_mixed_question_marks(self):
        self.assertNotIn("??？", self.md)
        self.assertIn("???", self.md)

    def test_header_spacing(self):
        # 旧版是「已点亮 **13** 款/ 148 款」—— 斜杠前后缺空格
        self.assertNotIn("款/", self.md)
        self.assertIn(" / ", self.md)

    def test_lit_items_render_as_images(self):
        self.assertIn("<img src=\"https://menu-img.mcd.cn", self.md)
        self.assertIn("width=\"96\"", self.md)

    def test_progress_bar_has_granularity(self):
        # 旧版 progress//10 会让 5% 显示为空、15% 只有 1 格
        self.assertTrue(any(ch in render_mod._bar(5) for ch in "▏▎▍▌▋▊▉█"))
        self.assertEqual(render_mod._bar(0).count("░"), 10)
        self.assertEqual(render_mod._bar(100).count("█"), 10)
        self.assertEqual(render_mod._bar(150).count("█"), 10)

    def test_ur_section(self):
        self.assertIn("绝版殿堂", self.md)
        self.assertIn("培根蔬萃双层牛堡", self.md)


# ===========================================================================
# 10. 绝版补图 / 离线 Demo
# ===========================================================================
class TestImageBackfill(unittest.TestCase):
    def test_probe_hit_fills_image(self):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("1406", "板烧鸡腿堡")]), store="S1")
        store = codex_mod.CodexStore()
        order = _order("O-1", "订单已完成", [
            ("521879", "泰式炭烤风味猪猪堡", 1, None)])
        store.absorb_order(order, cat, probe=lambda url: "MS_521879_320.png" in url)
        item = next(iter(store.items.values()))
        self.assertEqual(item["rarity"], "UR")
        self.assertEqual(item["image"],
                         codex_mod.IMAGE_URL_TEMPLATE.format(code="521879"))

    def test_probe_miss_keeps_image_empty(self):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("1406", "板烧鸡腿堡")]), store="S1")
        store = codex_mod.CodexStore()
        order = _order("O-2", "订单已完成", [("521879", "泰式炭烤风味猪猪堡", 1, None)])
        store.absorb_order(order, cat, probe=lambda url: False)
        self.assertEqual(next(iter(store.items.values()))["image"], "")

    def test_no_probe_means_no_network(self):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("1406", "板烧鸡腿堡")]), store="S1")
        store = codex_mod.CodexStore()
        order = _order("O-3", "订单已完成", [("521879", "泰式炭烤风味猪猪堡", 1, None)])
        store.absorb_order(order, cat)
        self.assertEqual(next(iter(store.items.values()))["image"], "")


class TestOfflineDemo(unittest.TestCase):
    def test_demo_builds_all_artifacts(self):
        import demo as demo_mod
        tmp = tempfile.mkdtemp(prefix="mcd-demo-")
        try:
            stats, paths = demo_mod.build(tmp, examples_dir=EXAMPLES, quiet=True)
            for kind in ("catalog", "codex", "markdown", "card", "wall"):
                self.assertTrue(os.path.exists(paths[kind]), kind)
            self.assertGreater(stats["pool_total"], 70)
            self.assertEqual(stats["ur_count"], 2)
            with open(paths["wall"], "r", encoding="utf-8") as f:
                self.assertNotIn("{{", f.read())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 11. 统计口径
# ===========================================================================
class TestStatsExtras(unittest.TestCase):
    def test_pool_mix_and_completion(self):
        cat = catalog_mod.Catalog()
        cat.absorb_menu(_menu_payload([("A", "薯条"), ("B", "苹果片")]), store="S1")
        store = codex_mod.CodexStore()
        order = _order("O-9", "订单已完成", [("A", "薯条", 1, None)])
        store.absorb_order(order, cat)
        stats = store.stats(cat)
        self.assertEqual(stats["pool_by_rarity"]["SR"], 1)   # 薯条 = 招牌款
        self.assertEqual(stats["pool_by_rarity"]["R"], 1)    # 苹果片 = 常规款
        self.assertEqual(stats["completion"], 50)
        self.assertEqual(stats["mine_by_rarity"]["SR"], 1)
        self.assertEqual(stats["sr_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
