# -*- coding: utf-8 -*-
"""demo.py — 零 Token 离线演示：30 秒把图鉴墙跑出来。

不调用任何 MCP、不需要 Token、不需要联网（产品图走 CDN，断网时自动降级为占位符）：

    python scripts/demo.py            # 用 examples/ 的脱敏快照重建 demo/
    python scripts/demo.py --open     # 顺便在浏览器里打开图鉴墙
    python scripts/demo.py --serve    # 起一个本地静态服务器（默认 8765）

示例数据是**两个门店 × 两个时段**的菜单（1440001 / 1440040）——
单门店采样会把「别家门店在卖」的餐品误判成绝版，多门店取并集才准。

产物（全部写进 demo/）:
    demo/catalog.json   图鉴池（93 款单品）
    demo/codex.json     个人图鉴（13 款点亮，含绝版卡）
    demo/codex.md       Markdown 图鉴（GitHub 可视）
    demo/card.html      分享卡
    demo/wall.html      图鉴格子墙  ← 先看这个
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalog as catalog_mod   # noqa: E402
import codex as codex_mod       # noqa: E402
import rarity as rarity_mod     # noqa: E402
import render as render_mod     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")
DEMO = os.path.join(ROOT, "demo")

# (storeCode, 时段, 快照文件) —— 两家门店取并集
MENUS = [
    ("1440001", "regular", "menu-regular.json"),
    ("1440001", "breakfast", "menu-breakfast.json"),
    ("1440040", "regular", "menu-store2-regular.json"),
    ("1440040", "breakfast", "menu-store2-breakfast.json"),
]
ORDERS = "order-list.json"


class DemoError(RuntimeError):
    """示例数据缺失/损坏时的可读错误。"""


def _load(name, base=None):
    path = os.path.join(base or EXAMPLES, name)
    if not os.path.exists(path):
        raise DemoError("缺少示例数据: %s" % path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build(demo_dir=DEMO, examples_dir=None, quiet=False):
    """用脱敏快照重建一整套图鉴产物，返回 (stats, paths)。"""
    base = examples_dir or EXAMPLES
    os.makedirs(demo_dir, exist_ok=True)

    cat = catalog_mod.Catalog()
    for store, period, name in MENUS:
        cat.absorb_menu(_load(name, base), period=period, store=store)
    cat_path = os.path.join(demo_dir, "catalog.json")
    cat.save(cat_path)

    store_obj = codex_mod.CodexStore()
    for order in codex_mod.extract_orders(_load(ORDERS, base)):
        store_obj.absorb_order(order, cat)
    store_obj.reclassify(cat)
    codex_path = os.path.join(demo_dir, "codex.json")
    store_obj.save(codex_path)

    md_path = os.path.join(demo_dir, "codex.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_mod.render_markdown(store_obj, cat))
    card_path = render_mod.render_share_card(
        store_obj, cat, None, os.path.join(demo_dir, "card.html"))
    wall_path = render_mod.render_codex_wall(
        store_obj, cat, None, os.path.join(demo_dir, "wall.html"))

    stats = store_obj.stats(cat)
    paths = {"catalog": cat_path, "codex": codex_path, "markdown": md_path,
             "card": card_path, "wall": wall_path}
    if not quiet:
        print(_summary(stats, paths))
    return stats, paths


def _show(path):
    """相对于当前工作目录的短路径，方便直接复制执行。"""
    try:
        rel = os.path.relpath(path)
    except ValueError:          # Windows 跨盘符
        rel = path
    return rel.replace(os.sep, "/")


def _summary(stats, paths=None):
    pool = stats.get("pool_total") or 0
    mix = stats.get("pool_by_rarity") or {}
    lines = []
    lines.append("")
    lines.append("  🍟 麦麦图鉴 · 离线演示")
    lines.append("  " + "-" * 46)
    lines.append("  图鉴池   %d 款单品   R %d / SR %d / SSR %d" % (
        pool, mix.get("R", 0), mix.get("SR", 0), mix.get("SSR", 0)))
    lines.append("  已点亮   %d / %d（%d%%）  Lv.%d %s" % (
        stats["unlocked"], pool, stats["completion"],
        stats["level"], stats["title"]))
    lines.append("  稀有度   UR %d 张（绝版） / SSR %d / SR %d" % (
        stats["ur_count"], stats["ssr_count"], stats.get("sr_count", 0)))
    if stats.get("badges"):
        lines.append("  徽章     %s" % " ".join(stats["badges"]))
    if stats.get("treasure"):
        lines.append("  最珍贵   %s（%s）" % (
            stats["treasure"]["name"], stats["treasure"]["rarity"]))
    lines.append("  " + "-" * 46)
    if paths:
        rows = [(_show(paths["wall"]), "图鉴格子墙（先看这个）"),
                (_show(paths["card"]), "分享卡"),
                (_show(paths["markdown"]), "Markdown 图鉴")]
        width = max([len(p) for p, _ in rows] + [26])
        for path, label in rows:
            lines.append("  %-*s  %s" % (width, path, label))
    else:
        lines.append("  demo/wall.html    图鉴格子墙（先看这个）")
        lines.append("  demo/card.html    分享卡")
        lines.append("  demo/codex.md     Markdown 图鉴")
    lines.append("")
    return "\n".join(lines)


def _serve(directory, port):
    import functools
    import http.server
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=directory)
    print("  本地预览: http://127.0.0.1:%d/wall.html  (Ctrl+C 结束)" % port)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


def main(argv=None):
    parser = argparse.ArgumentParser(description="麦麦图鉴离线演示（零 Token）")
    parser.add_argument("--out", default=DEMO, help="产物目录（默认 demo/）")
    parser.add_argument("--open", action="store_true", help="生成后打开图鉴墙")
    parser.add_argument("--serve", action="store_true", help="起本地静态服务器预览")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    try:
        _, paths = build(args.out)
    except DemoError as exc:
        print("  ✗ %s" % exc)
        return 2

    if args.serve:
        _serve(args.out, args.port)
        return 0
    if args.open:
        import webbrowser
        webbrowser.open("file:///" + os.path.abspath(paths["wall"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
