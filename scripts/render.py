# -*- coding: utf-8 -*-
"""render.py — 麦麦图鉴 · 渲染层。

三种交付形态, 都由同一份「池 + 已点亮集合」驱动:

1. ``render_markdown``   Markdown 图鉴（GitHub 可视: 点亮格带官方产品图）
2. ``render_codex_wall`` **图鉴格子墙**（核心视觉: 整本图鉴一次铺开,
   点亮格 = 官方产品图 + 名称 + 稀有度边框, 未点亮格 = 灰度剪影 + ???）
3. ``render_share_card`` 个人分享卡（含餐品缩略格 + 最珍贵收藏特写）

设计约定:
    * 未点亮格用**同一张官方图**做剪影（filter 压黑）——「看得见轮廓、猜不到是谁」
      才是图鉴的收集欲来源, 而不是一行「??？」文字。
    * 稀有度用边框颜色 + 角标表达: R 墨灰 / SR 蓝 / SSR 金 / UR 全息。
    * 输出为**自包含单文件 HTML**（无外部 JS/CSS 依赖）, 双击即看、可直接截图。
"""

import datetime
import html as html_lib
import os

import catalog as catalog_mod
import rarity as rarity_mod

RARITY_BADGE = {
    rarity_mod.RARITY_R: "·",
    rarity_mod.RARITY_SR: "◆",
    rarity_mod.RARITY_SSR: "✦",
    rarity_mod.RARITY_UR: "💎",
}

# 分享卡上「我需要炫耀哪几格」的优先级
_HERO_ORDER = [rarity_mod.RARITY_UR, rarity_mod.RARITY_SSR,
               rarity_mod.RARITY_SR, rarity_mod.RARITY_R]

# Markdown 进度条: 10 格, 每格可用 1/8 块做细分（5% 也能显示出来）
_BAR_CELLS = 10
_BAR_PARTS = " ▏▎▍▌▋▊▉█"


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------
def _esc(value):
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _safe_img(url):
    """只允许 http(s) 图片地址, 其它一律降级为空（防注入 / 防坏链）。"""
    url = str(url or "").strip()
    if url.startswith("https://") or url.startswith("http://"):
        return _esc(url)
    return ""


def _short_time(value):
    return (value or "—")[:10] or "—"


def _thumb(img_url, label, locked=False, ph="🍽"):
    """缩略图: 底层放占位符, 上层叠官方产品图。

    图片加载失败时 ``onerror`` 直接移除 img, 露出占位符 —— 保证任何网络/坏链
    情况下交付物里都不会出现破图（纯内联, 无外部脚本）。
    """
    ph_html = '<span class="ph">%s</span>' % ph
    img = _safe_img(img_url)
    if not img:
        return ph_html
    return ph_html + (
        '<img class="%s" src="%s" alt="%s" loading="lazy" onerror="this.remove()">'
        % ("sil" if locked else "pic", img,
           "未点亮" if locked else _esc(label)))


def _bar(pct, cells=_BAR_CELLS):
    """Markdown 进度条: █ 满格 + 1/8 块半格 + ░ 空格。"""
    pct = max(0, min(100, int(pct)))
    filled = pct / 100.0 * cells
    full = int(filled)
    partial = int(round((filled - full) * 8))
    if partial >= 8:
        full, partial = full + 1, 0
    full = min(full, cells)
    bar = "█" * full
    if partial:
        bar += _BAR_PARTS[partial]
    return bar + "░" * max(0, cells - len(bar))


def _owned_map(store, catalog):
    """构建「池内 code → 已点亮 item」索引。

    三通道: catalog_code 精确 → 条目 key 精确 → 归一化名称。
    """
    by_code, by_name = {}, {}
    for key, item in store.items.items():
        if item.get("catalog_code"):
            by_code[str(item["catalog_code"])] = item
        by_name[rarity_mod.normalize_name(item.get("name") or "")] = item
    matched = {}
    for code, entry in (catalog.products.items() if catalog else []):
        item = by_code.get(str(code))
        if item is None:
            item = by_name.get(rarity_mod.normalize_name(entry.get("name") or ""))
        if item is not None:
            matched[code] = item
    return matched


def _book_sections(store, catalog):
    """[{book, pool_total, cells: [...]}] —— cells 已按「稀有度→点亮优先」排序。"""
    pool_by_book = catalog.pool_by_book() if catalog else {}
    owned = _owned_map(store, catalog)
    sections = []
    for book in catalog_mod.BOOKS:
        pool = pool_by_book.get(book) or {}
        cells = []
        for code, entry in pool.items():
            item = owned.get(code)
            cells.append({
                "code": code,
                "name": entry.get("name") or "",
                "image": entry.get("image") or "",
                "rarity": entry.get("rarity") or rarity_mod.RARITY_R,
                "locked": item is None,
                "count": (item or {}).get("count", 0),
                "first_unlock": (item or {}).get("first_unlock", ""),
                "periods": entry.get("periods") or [],
            })
        cells.sort(key=lambda c: (-rarity_mod.rank_of(c["rarity"]),
                                  c["locked"], c["name"]))
        sections.append({
            "book": book,
            "emoji": catalog_mod.BOOK_EMOJI[book],
            "pool_total": len(cells),
            "owned": sum(1 for c in cells if not c["locked"]),
            "cells": cells,
        })
    return sections


def _ur_items(store):
    ur = [it for it in store.items.values()
          if it.get("rarity") == rarity_mod.RARITY_UR]
    ur.sort(key=lambda x: (-x.get("count", 0), x.get("first_unlock") or "9999"))
    return ur


# ---------------------------------------------------------------------------
# 1. Markdown 图鉴
# ---------------------------------------------------------------------------
def render_markdown(store, catalog=None):
    stats = store.stats(catalog)
    lines = []
    lines.append("# 📖 麦麦图鉴 · 我的味道足迹")
    lines.append("")
    lines.append("> 每一次点单，点亮图鉴里的一页")
    lines.append("")
    pool_part = "**%d** 款（当前菜单池）" % stats["pool_total"] if stats["pool_total"] else "款"
    lines.append("**Lv.%d %s** · 已点亮 **%d** / %s · 完成度 **%d%%**" % (
        stats["level"], stats["title"], stats["unlocked"], pool_part,
        stats["completion"]))
    if stats["badges"]:
        lines.append("")
        lines.append("徽章：%s" % " ".join(stats["badges"]))
    lines.append("")

    sections = _book_sections(store, catalog) if catalog else []
    if not sections:
        # 无菜单池（降级模式）: 只按条目自身的册别列出已点亮款
        for book in catalog_mod.BOOKS:
            owned = [it for it in store.items.values() if it["book"] == book]
            if not owned:
                continue
            lines.append("## %s %s" % (catalog_mod.BOOK_EMOJI[book], book))
            lines.append("")
            for it in sorted(owned, key=lambda x: -rarity_mod.rank_of(x["rarity"])):
                lines.append("- %s **%s** `%s`" % (
                    RARITY_BADGE.get(it["rarity"], "·"), it["name"],
                    rarity_mod.RARITY_LABEL.get(it["rarity"], it["rarity"])))
            lines.append("")
    else:
        for sec in sections:
            lines.append("## %s %s · %d / %d" % (
                sec["emoji"], sec["book"], sec["owned"], sec["pool_total"]))
            lines.append("")
            pct = int(round(sec["owned"] * 100.0 / sec["pool_total"])) \
                if sec["pool_total"] else 0
            lines.append("`%s` %d%%" % (_bar(pct), pct))
            lines.append("")
            lit = [c for c in sec["cells"] if not c["locked"]]
            if lit:
                lines.extend(_md_grid(lit))
                lines.append("")
            locked = sec["pool_total"] - sec["owned"]
            if locked:
                lines.append("*未点亮剪影 × %d：%s*" % (
                    locked, " ".join(["???"] * min(locked, 30))))
                lines.append("")

    ur = _ur_items(store)
    if ur:
        lines.append("## 💎 绝版殿堂")
        lines.append("")
        lines.append("| 餐品 | 稀有度 | 首次点亮 | 门店 | 次数 |")
        lines.append("|---|:---:|---|---|:---:|")
        for it in ur:
            lines.append("| **%s** | `UR` 绝版款 | %s | %s | ×%d |" % (
                it.get("name") or "", _short_time(it.get("first_unlock")),
                it.get("store") or "—", it.get("count", 1)))
        lines.append("")
        lines.append("*买不到的，才是真的绝版。*")
        lines.append("")

    lines.append("---")
    if stats["favorite"]:
        lines.append("最爱的味道：**%s**（%d 次）" % (
            stats["favorite"]["name"], stats["favorite"]["count"]))
    if stats["treasure"]:
        lines.append("最珍贵的收藏：%s **%s**" % (
            stats["treasure"]["rarity"], stats["treasure"]["name"]))
    lines.append("")
    lines.append("*McD Codex · 麦麦图鉴 · 非麦当劳官方产品*")
    return "\n".join(lines)


def _md_grid(cells, per_row=6):
    """把已点亮格渲染成 GitHub 可显示的图片表格（每行 per_row 格）。"""
    out = []
    for start in range(0, len(cells), per_row):
        row = cells[start:start + per_row]
        out.append('<table><tr>')
        for c in row:
            img = _safe_img(c["image"])
            thumb = ('<img src="%s" width="96" height="96" alt="%s">'
                     % (img, _esc(c["name"]))) if img else "🍽"
            out.append(
                '<td align="center" width="120">%s<br><b>%s</b><br>'
                '<sub>%s %s</sub></td>'
                % (thumb, _esc(c["name"]),
                   RARITY_BADGE.get(c["rarity"], "·"),
                   rarity_mod.RARITY_LABEL.get(c["rarity"], c["rarity"])))
        out.append('</tr></table>')
    return out


# ---------------------------------------------------------------------------
# 2. 图鉴格子墙（核心视觉）
# ---------------------------------------------------------------------------
def default_template_path():
    """定位分享卡模板（相对本脚本位置, 与 cwd 无关）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(
        here, os.pardir, "assets", "templates", "share-card.html"))


def default_wall_template_path():
    """定位图鉴格子墙模板（相对本脚本位置, 与 cwd 无关）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(
        here, os.pardir, "assets", "templates", "codex-wall.html"))


def _read_template(template_path, fallback_fn, label):
    path = template_path
    if not path or not os.path.exists(path):
        path = fallback_fn()
    if not os.path.exists(path):
        raise FileNotFoundError("%s模板不存在: %s" % (label, path))
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _wall_cell(cell):
    """单个图鉴格: 点亮 = 图 + 名称 + 稀有色; 未点亮 = 剪影 + ???。"""
    img = cell["image"]
    rarity = cell["rarity"]
    label = rarity_mod.RARITY_LABEL.get(rarity, rarity)
    if cell["locked"]:
        return (
            '<figure class="cell locked r-%s" title="未点亮 · %s">'
            '<div class="thumb">%s</div>'
            '<figcaption><b>???</b><i class="chip">%s</i></figcaption>'
            '</figure>' % (rarity.lower(), _esc(label),
                           _thumb(img, "", locked=True, ph="?"), _esc(label)))

    count = cell.get("count") or 0
    count_html = '<i class="cnt">×%d</i>' % count if count > 1 else ""
    when = _short_time(cell.get("first_unlock"))
    return (
        '<figure class="cell lit r-%s" title="%s · %s 首次点亮">'
        '<div class="thumb">%s%s</div>'
        '<figcaption><b>%s</b><i class="chip">%s</i><em class="date">%s</em></figcaption>'
        '</figure>' % (rarity.lower(), _esc(cell["name"]), _esc(when),
                       _thumb(img, cell["name"]), count_html,
                       _esc(cell["name"]), _esc(label), _esc(when)))


def _wall_sections(sections):
    blocks = []
    for idx, sec in enumerate(sections, 1):
        pct = int(round(sec["owned"] * 100.0 / sec["pool_total"])) \
            if sec["pool_total"] else 0
        cells = "".join(_wall_cell(c) for c in sec["cells"])
        done = sec["pool_total"] and sec["owned"] == sec["pool_total"]
        blocks.append(
            '<section class="book" id="book-%d">'
            '<header class="book-head">'
            '<h2>%s %s%s</h2>'
            '<div class="bp"><div class="bp-bar"><i style="width:%d%%"></i></div>'
            '<span>%d / %d</span></div>'
            '</header>'
            '<div class="grid">%s</div>'
            '</section>'
            % (idx, sec["emoji"], _esc(sec["book"]),
               ' <em class="done">已集齐</em>' if done else "",
               pct, sec["owned"], sec["pool_total"], cells))
    return "".join(blocks)


def _hall_of_fame(ur_items):
    if not ur_items:
        return ('<section class="hall empty"><h2>💎 绝版殿堂</h2>'
                '<p class="hint">还没有绝版款。等你某天发现「这款怎么买不到了」，'
                '它就会自动搬进这里。</p></section>')
    cards = []
    for it in ur_items:
        cards.append(
            '<figure class="ur-card">'
            '<div class="thumb">%s<span class="holo"></span></div>'
            '<figcaption><b>%s</b>'
            '<i class="chip">绝版款</i>'
            '<em>%s · %s</em></figcaption>'
            '</figure>' % (_thumb(it.get("image"), it.get("name"), ph="💎"),
                           _esc(it.get("name") or ""),
                           _esc(_short_time(it.get("first_unlock"))),
                           _esc(it.get("store") or "—")))
    return ('<section class="hall"><h2>💎 绝版殿堂 '
            '<small>买不到的，才是真的绝版</small></h2>'
            '<div class="hall-row">%s</div></section>' % "".join(cards))


def _legend(stats):
    pool = stats.get("pool_by_rarity") or {}
    total = stats.get("pool_total") or 0
    items = []
    for r in (rarity_mod.RARITY_R, rarity_mod.RARITY_SR, rarity_mod.RARITY_SSR):
        n = pool.get(r, 0)
        pct = round(n * 100.0 / total, 1) if total else 0
        items.append('<li class="lg r-%s"><i></i>%s %s<em>%d 款 · %s%%</em></li>'
                     % (r.lower(), rarity_mod.RARITY_STARS[r],
                        rarity_mod.RARITY_LABEL[r], n, pct))
    items.append('<li class="lg r-ur"><i></i>★★★★ 绝版款<em>%d 张</em></li>'
                 % stats.get("ur_count", 0))
    return '<ul class="legend">%s</ul>' % "".join(items)


def _book_nav(sections):
    chips = "".join(
        '<a href="#book-%d">%s %s <em>%d/%d</em></a>'
        % (i, s["emoji"], _esc(s["book"]), s["owned"], s["pool_total"])
        for i, s in enumerate(sections, 1))
    return '<nav class="booknav">%s</nav>' % chips


def render_codex_wall(store, catalog, template_path, out_path):
    """渲染整本图鉴格子墙（P0 视觉主交付物）。"""
    stats = store.stats(catalog)
    sections = _book_sections(store, catalog) if catalog else []
    badges = "".join('<span class="badge">%s</span>' % _esc(b)
                     for b in stats["badges"]) \
        or '<span class="badge muted">徽章还在路上</span>'
    replacements = {
        "{{TITLE}}": "麦麦图鉴 · %s" % _esc(stats["title"]),
        "{{LEVEL}}": "Lv.%d %s" % (stats["level"], _esc(stats["title"])),
        "{{UNLOCKED}}": str(stats["unlocked"]),
        "{{POOL_TOTAL}}": str(stats["pool_total"] or "—"),
        "{{COMPLETION}}": str(stats["completion"]),
        "{{UR_COUNT}}": str(stats["ur_count"]),
        "{{SSR_COUNT}}": str(stats["ssr_count"]),
        "{{SR_COUNT}}": str(stats.get("sr_count", 0)),
        "{{BOOK_NAV}}": _book_nav(sections),
        "{{BOOK_SECTIONS}}": _wall_sections(sections)
        or '<p class="hint">图鉴池还没采样。先跑一次 absorb-menu。</p>',
        "{{HALL_OF_FAME}}": _hall_of_fame(_ur_items(store)),
        "{{LEGEND}}": _legend(stats),
        "{{BADGES}}": badges,
        "{{FAVORITE}}": _esc(stats["favorite"]["name"]) if stats["favorite"] else "—",
        "{{GENERATED_AT}}": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    html = _read_template(template_path, default_wall_template_path, "格子墙")
    for key, value in replacements.items():
        html = html.replace(key, value)
    _write(out_path, html)
    return out_path


# ---------------------------------------------------------------------------
# 3. 分享卡
# ---------------------------------------------------------------------------
def _hero_cells(store, limit=6):
    """挑出最值得炫耀的餐品（UR → SSR → SR → R, 同档内有图优先）。"""
    items = list(store.items.values())
    items.sort(key=lambda it: (
        # _HERO_ORDER 由稀有到常见, 直接取序号即为排序优先级（越小越靠前）
        _HERO_ORDER.index(it["rarity"]) if it.get("rarity") in _HERO_ORDER else 9,
        0 if it.get("image") else 1,
        it.get("first_unlock") or "9999"))
    return items[:limit]


def _card_mini_grid(items):
    if not items:
        return ('<div class="mini empty"><span>第一格还空着 —— 去点一单，'
                '图鉴就开张了。</span></div>')
    cells = []
    for it in items:
        rarity = str(it.get("rarity") or "R").lower()
        cells.append(
            '<figure class="mini-cell r-%s">'
            '<div class="thumb">%s</div>'
            '<figcaption><b>%s</b><i>%s</i></figcaption>'
            '</figure>' % (rarity,
                           _thumb(it.get("image"), it.get("name"), ph="🍽"),
                           _esc(it.get("name")),
                           _esc(rarity_mod.RARITY_LABEL.get(
                               it.get("rarity"), it.get("rarity")))))
    return '<div class="mini">%s</div>' % "".join(cells)


def _card_treasure(store):
    ur = _ur_items(store)
    if not ur:
        return ('<div class="treasure empty">'
                '<span>绝版席位空着 —— 你的旧爱还在菜单上。</span></div>')
    it = ur[0]
    return ('<div class="treasure">'
            '<div class="thumb">%s</div>'
            '<div class="tk"><i>最珍贵的收藏 · 绝版款</i>'
            '<b>%s</b><small>%s · %s</small></div></div>'
            % (_thumb(it.get("image"), it.get("name"), ph="💎"),
               _esc(it.get("name")), _esc(_short_time(it.get("first_unlock"))),
               _esc(it.get("store") or "—")))


def render_share_card(store, catalog, template_path, out_path):
    """用模板生成个人图鉴分享卡（一键晒图 → Star 增长引擎）。

    template_path 为 None 或文件不存在时, 自动回退到脚本相对路径下的默认模板,
    保证无论工作目录在哪里都能渲染成功。
    """
    stats = store.stats(catalog)
    html = _read_template(template_path, default_template_path, "分享卡")

    book_cells = []
    for book in catalog_mod.BOOKS:
        book_cells.append(
            '<div class="cell"><div class="num">%d</div><div class="cap">%s %s</div></div>'
            % (stats["by_book"].get(book, 0), catalog_mod.BOOK_EMOJI[book], book[:2]))
    pool_by_book = catalog.pool_by_book() if catalog else {}
    progress_rows = []
    for book in catalog_mod.BOOKS:
        owned = stats["by_book"].get(book, 0)
        pool_n = len(pool_by_book.get(book) or {})
        if pool_n:
            pct = min(100, int(owned / pool_n * 100))
            progress_rows.append(
                '<div class="prow"><span class="pl">%s %s</span>'
                '<div class="pbar"><div class="pfill" style="width:%d%%"></div></div>'
                '<span class="pv">%d/%d</span></div>'
                % (catalog_mod.BOOK_EMOJI[book], book, pct, owned, pool_n))

    badges_html = "".join('<span class="badge">%s</span>' % _esc(b)
                           for b in stats["badges"]) \
        or '<span class="badge muted">暂无 —— 下一枚在路上</span>'

    replacements = {
        "{{UNLOCKED}}": str(stats["unlocked"]),
        "{{POOL_TOTAL}}": str(stats["pool_total"] or "—"),
        "{{COMPLETION}}": str(stats["completion"]),
        "{{LEVEL}}": "Lv.%d %s" % (stats["level"], _esc(stats["title"])),
        "{{BOOK_CELLS}}": "".join(book_cells),
        "{{HERO_GRID}}": _card_mini_grid(_hero_cells(store)),
        "{{TREASURE_CARD}}": _card_treasure(store),
        "{{PROGRESS_ROWS}}": "".join(progress_rows)
        or '<div class="prow"><span class="pv">补充菜单采样后显示分册进度</span></div>',
        "{{BADGES}}": badges_html,
        "{{FAVORITE}}": ("%s ×%d" % (_esc(stats["favorite"]["name"]),
                                      stats["favorite"]["count"]))
        if stats["favorite"] else "—",
        "{{TREASURE}}": ("%s %s" % (_esc(stats["treasure"]["rarity"]),
                                     _esc(stats["treasure"]["name"])))
        if stats["treasure"] else "—",
        "{{UR_COUNT}}": str(stats["ur_count"]),
        "{{GENERATED_AT}}": datetime.datetime.now().strftime("%Y.%m.%d"),
    }
    for key, value in replacements.items():
        html = html.replace(key, value)
    _write(out_path, html)
    return out_path
