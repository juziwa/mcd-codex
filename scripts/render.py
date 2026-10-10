# -*- coding: utf-8 -*-
"""render.py — 麦麦图鉴 · 渲染层（Markdown 图鉴 + HTML 分享卡）。

未点亮状态: 黑白剪影 + 问号（Markdown 中以「??？」剪影行表达,
HTML 分享卡中以灰阶卡片表达）, 制造「想知道是什么」的收集欲。
"""

import os

import catalog as catalog_mod
import rarity as rarity_mod

RARITY_BADGE = {
    rarity_mod.RARITY_R: "·",
    rarity_mod.RARITY_SR: "◆",
    rarity_mod.RARITY_SSR: "✦",
    rarity_mod.RARITY_UR: "💎",
}


# ---------------------------------------------------------------------------
# Markdown 图鉴
# ---------------------------------------------------------------------------
def render_markdown(store, catalog=None):
    stats = store.stats(catalog)
    lines = []
    lines.append("# 📖 麦麦图鉴 · 我的味道足迹")
    lines.append("")
    lines.append("> 每一次点单，点亮图鉴里的一页")
    lines.append("")
    lines.append("**Lv.%d %s** · 已点亮 **%d** 款%s" % (
        stats["level"], stats["title"], stats["unlocked"],
        ("/ %d 款（当前菜单池）" % stats["pool_total"]) if stats["pool_total"] else ""))
    if stats["badges"]:
        lines.append("")
        lines.append("徽章：%s" % " ".join(stats["badges"]))
    lines.append("")

    # 按册渲染
    pool_by_book = catalog.pool_by_book() if catalog else {}
    for book in catalog_mod.BOOKS:
        emoji = catalog_mod.BOOK_EMOJI[book]
        owned = [it for it in store.items.values() if it["book"] == book]
        pool = pool_by_book.get(book) or {}
        lines.append("## %s %s" % (emoji, book))
        pool_note = "（池内 %d 款，已点亮 %d）" % (len(pool), len(owned)) if catalog else ""
        lines.append("")
        if pool_note:
            progress = int(len(owned) / len(pool) * 100) if pool else 0
            lines.append("进度 %s %d%% %s" % ("▓" * (progress // 10), progress, pool_note))
            lines.append("")
        if not owned:
            lines.append("*（暂未点亮 —— 图鉴的下一页，等你来翻。）*")
            lines.append("")
            continue
        # 已点亮：稀有度高的在前
        owned.sort(key=lambda x: (
            -_rarity_order(x["rarity"]), x.get("first_unlock") or "9999"))
        for it in owned:
            lines.append("- %s **%s** %s%s" % (
                RARITY_BADGE.get(it["rarity"], "·"),
                it["name"],
                _rarity_tag(it["rarity"]),
                "（×%d）" % it["count"] if it.get("count", 1) > 1 else ""))
            lines.append("  首次点亮 %s · %s" % (
                it.get("first_unlock") or "—", it.get("store") or "—"))
        # 池内未点亮 → 剪影
        owned = set(store.items.keys()) | {
            it.get("catalog_code") for it in store.items.values()
            if it.get("catalog_code")}
        shadows = [entry for code, entry in pool.items() if code not in owned]
        if shadows:
            lines.append("")
            lines.append("*未点亮剪影：%s*" % "、".join(
                ["??？" for _ in shadows[:30]]))
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


def _rarity_order(r):
    return {rarity_mod.RARITY_R: 0, rarity_mod.RARITY_SR: 1,
            rarity_mod.RARITY_SSR: 2, rarity_mod.RARITY_UR: 3}.get(r, 0)


def _rarity_tag(r):
    return "`%s`" % rarity_mod.RARITY_LABEL.get(r, r)


# ---------------------------------------------------------------------------
# HTML 分享卡
# ---------------------------------------------------------------------------
def default_template_path():
    """定位分享卡模板（相对本脚本位置, 与 cwd 无关）。

    仓库/Skill 安装目录结构均为 <root>/scripts/render.py 与
    <root>/assets/templates/share-card.html 同级。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(
        here, os.pardir, "assets", "templates", "share-card.html"))


def render_share_card(store, catalog, template_path, out_path):
    """用模板生成个人图鉴分享卡（一键晒图 → Star 增长引擎）。

    template_path 为 None 或文件不存在时, 自动回退到脚本相对路径下的默认模板,
    保证无论工作目录在哪里都能渲染成功。
    """
    stats = store.stats(catalog)
    if not template_path or not os.path.exists(template_path):
        template_path = default_template_path()
    if not os.path.exists(template_path):
        raise FileNotFoundError("分享卡模板不存在: %s" % template_path)
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

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

    badges_html = "".join('<span class="badge">%s</span>' % b for b in stats["badges"]) \
        or '<span class="badge muted">暂无 —— 下一枚在路上</span>'

    replacements = {
        "{{UNLOCKED}}": str(stats["unlocked"]),
        "{{POOL_TOTAL}}": str(stats["pool_total"] or "—"),
        "{{LEVEL}}": "Lv.%d %s" % (stats["level"], stats["title"]),
        "{{BOOK_CELLS}}": "".join(book_cells),
        "{{PROGRESS_ROWS}}": "".join(progress_rows)
        or '<div class="prow"><span class="pv">补充菜单采样后显示分册进度</span></div>',
        "{{BADGES}}": badges_html,
        "{{FAVORITE}}": ("%s ×%d" % (stats["favorite"]["name"], stats["favorite"]["count"]))
        if stats["favorite"] else "—",
        "{{TREASURE}}": ("%s %s" % (stats["treasure"]["rarity"], stats["treasure"]["name"]))
        if stats["treasure"] else "—",
        "{{UR_COUNT}}": str(stats["ur_count"]),
    }
    for key, value in replacements.items():
        html = html.replace(key, value)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
