---
name: mcd-codex
description: 麦麦图鉴（McD Codex）—— 把每一次麦当劳点单，点亮成图鉴里的一页。当用户想查看「我吃过多少款麦当劳」、打开/浏览图鉴、点亮餐品、检测绝版款、查图鉴等级称号徽章、生成图鉴分享卡时使用。需配合麦当劳 MCP Server（mcd-mcp 连接器）真实调用。
---

# 麦麦图鉴 · McD Codex Skill

把用户的麦当劳消费历史变成一本**可收集、可炫耀、可回忆**的餐品图鉴：
六册图鉴（汉堡/早餐/小食/甜品/饮品/限定）、四档稀有度（R/SR/SSR/UR）、
等级称号徽章体系、绝版款检测、一键分享卡。

## 核心循环

```
点单 → 收集 → 点亮 → 炫耀 → 想集齐更多 → 点单
```

- **收集**：订单完成后，把订单里的**单品级**餐品（组合餐展开到子项）收入图鉴
- **点亮**：按册别归类；未点亮格位显示剪影 `???`，制造收集欲
- **炫耀**：生成图鉴统计 / 称号 / 分享卡

## 文件与路径约定

Skill 根目录（本 SKILL.md 所在目录）：

| 路径 | 用途 |
|---|---|
| `scripts/codex.py` | 收录引擎 CLI（absorb-menu / absorb-order / sync / stats / render） |
| `data/codex.json` | **用户个人图鉴状态**（自动生成，含个人数据，勿外传） |
| `data/catalog.json` | 图鉴池（多时段菜单合集，自动生成） |
| `data/snapshots/*.json` | MCP 响应快照（调用工具后先存这里，再交给 CLI） |
| `output/codex.md` | 渲染出的图鉴（Markdown） |
| `output/share-card.html` | 图鉴分享卡（HTML，用于晒图） |

运行 Python：优先用户环境中的 Python 3.8+；CLI 仅用标准库，无需安装依赖。

**路径规则**：CLI 的所有默认路径（`data/`、`output/`、分享卡模板）均以
**Skill 根目录**为基准自动解析，**可从任意工作目录执行**，无需先 `cd`。
跨目录调用时用脚本绝对路径更稳妥：

```bash
python "<Skill根目录>/scripts/codex.py" stats
```

下文示例统一写作 `python scripts/codex.py`（等价于在 Skill 根目录下执行）。

## MCP 工具调用链路

| 场景 | 调用链 |
|---|---|
| 首次打开 / 增量补录 | `order-list` → 存快照 → `sync` |
| 用户请求后更新图鉴池（建议每 1-2 周一次） | `now-time-info` → `query-nearby-stores`（拿常用门店 storeCode）→ 两次 `query-meals` → 存快照 → 一次事务式 `absorb-menu` |
| 下单收录（主动收录） | 走正常点单流程（`query-meals` → `calculate-price` → `create-order` → `query-order` 确认已支付）→ 存订单快照 → `absorb-order` |
| 绝版检测 | `absorb-menu` 更新池后 `sync` 自动重判（含 UR 复活） |
| 查看图鉴 / 分享 | `render` → 向用户展示 codex.md；分享卡用文件卡片呈现 |

**query-meals 参数速查**：到店自取 `beType=1, orderType=1`，不传 beCode；
早餐采样在常规参数基础上加 `reservationDate: "yyyy-MM-dd 10:00"`。先调用
`now-time-info` 获取北京时间并计算下一天日期，**不得把“次日 10:00”原样作为参数**。

## 流程编排

### 流程 A · 打开图鉴（含冷启动补录）

1. 用户明确请求打开图鉴后，调 `mcp__mcd-mcp__order-list`（无参数），把响应 JSON 完整保存到
   `data/snapshots/order-list.json`
2. 执行：
   ```bash
   python scripts/codex.py sync \
     --orders data/snapshots/order-list.json \
     --codex data/codex.json --catalog data/catalog.json
   ```
3. 若 `data/catalog.json` 不存在或超过 2 周未更新，先执行流程 C 更新图鉴池；菜单调用失败时保留旧池并停止本次重判
4. 解读 CLI 输出的 JSON：
   - `new_unlocks` → 逐条向用户播报「点亮了 XX！」
   - 冷启动首次补录 → 「发现你的 X 款历史足迹，图鉴已激活！」
   - `revived_from_ur` → 「XX 回归菜单了，绝版卡复活！」
5. 执行流程 D 展示图鉴

### 流程 B · 下单收录（主动收录，100% 可靠）

1. 按用户需求走正常点单（选门店 → 查菜单 → 算价 → 下单 → 支付确认）
2. `query-order` 确认订单状态**非取消**后，把订单详情 JSON 保存到
   `data/snapshots/order-{orderId}.json`
3. 执行：
   ```bash
   python scripts/codex.py absorb-order \
     --order data/snapshots/order-{orderId}.json \
     --codex data/codex.json --catalog data/catalog.json
   ```
4. 播报新点亮条目；订单若取消则不收录（CLI 自动跳过）

### 流程 C · 更新图鉴池（菜单采样 + 绝版检测）

1. `query-nearby-stores`（`beType=1, searchType=2, city=用户城市, keyword=位置`）
   取用户常用门店 storeCode（提示用户确认或直接用收藏门店）
2. `query-meals`（storeCode, beType=1, orderType=1）→ 存
   `data/snapshots/menu-regular.json`
3. `query-meals`（同上 + 下一天实际日期的 `reservationDate="yyyy-MM-dd 10:00"`）→ 存
   `data/snapshots/menu-breakfast.json`
4. 两份菜单快照都成功后，用一次事务式命令更新图鉴池：
   ```bash
   python scripts/codex.py absorb-menu --menu data/snapshots/menu-regular.json \
     --breakfast-menu data/snapshots/menu-breakfast.json \
     --catalog data/catalog.json --period regular --store {storeCode}
   ```
   只有常规和早餐快照都通过校验时才会写入图鉴池；任一失败都会保留旧池。
5. 再跑一次流程 A 的 sync，稀有度与绝版状态会自动重判

### 流程 D · 展示与分享

```bash
python scripts/codex.py render --codex data/codex.json \
  --catalog data/catalog.json --out-md output/codex.md --out-card output/share-card.html
```

- 向用户复述 `output/codex.md` 的核心内容（等级称号、各册进度、最爱与绝版收藏）
- 差 1-3 款集齐某册时，高亮提示「再点亮 X 款就集齐 XX 册了！」
- 用户想晒图时，用文件卡片展示 `output/share-card.html`

## 稀有度体系（判定由 rarity.py 自动完成）

| 等级 | 含义 |
|---|---|
| R 常规款 | 常年菜单在售 |
| SR 人气款 | 菜单标签含「人气」 |
| SSR 限定款 | 联名/限定关键词（高达、世界波、泷…），或仅早餐时段供应 |
| UR 绝版款 | 历史吃过、当前菜单池已下架 —— 时代眼泪，最重的炫耀资本 |

**注意**：UR 判定依赖已采样菜单池，会随采样扩充自动修正（复活机制）。
在售匹配是三通道（code 精确 → 名称归一化 → 弱匹配），请勿手工改判。

## 边界与合规

- `order-list` 仅返回最近 10 单：定位为增量补录，不承诺「导入全部历史」
- 用户绕过本 Skill 直接在官方 APP 下单：靠每次打开图鉴时的补录兜底
- 图鉴数据（codex.json）属个人消费记录，只保存在用户本地
- MCP 调用只在用户请求后按需执行，不做后台轮询、批量循环或定时自动调用；快照不得上传或分享
- 非麦当劳官方产品；餐品在售状态以麦当劳官方渠道实时结果为准
