# 🍟 McD Codex

> **每一次点单，点亮图鉴里的一页。**
>
> 中文昵称：麦麦图鉴

你吃过多少款麦当劳？我猜你答不上来。

积分会过期，优惠券会用完，但那杯深夜的可乐、那支考试周的圆筒、
那顿和朋友的八件套——它们值得被记住。

**McD Codex** 把你的麦当劳消费历史，变成一本可收集、可炫耀、可回忆的餐品图鉴。

---

## 它是什么

一个基于麦当劳 MCP 能力的 **收集型** Skill（配合 WorkBuddy 等支持 MCP 的智能体使用），
核心循环只有三步：

```
点单 → 收集 → 点亮 → 炫耀
 ↑                      ↓
 └──── 想集齐更多 ←──────┘
```

**六册图鉴**：🍔 汉堡册 · 🌅 早餐册 · 🍟 小食册 · 🍦 甜品册 · 🥤 饮品册 · ✨ 限定册

每一册都有进度环；未点亮的格位是一片剪影加问号——想知道是什么？去吃。

**稀有度四档**：

| 等级 | 含义 | 说明 |
|:---:|---|---|
| ★ R | 常规款 | 常年菜单在售 |
| ★★ SR | 人气款 | 菜单人气标签认证 |
| ★★★ SSR | 限定款 | 联名/限定（高达、世界波、泷…），或早餐限时供应 |
| ★★★★ UR | **绝版款** | 你吃过，但菜单上已经买不到了 |

> 💎 **UR 绝版款是点睛之笔**：图鉴会自动检测「历史订单里有、当前菜单已下架」的餐品。
> 你账户里躺着的「泰式炭烤风味猪猪堡」「培根蔬萃双层牛堡」——如果已下架，
> 它们将成为你图鉴里买不到的荣耀，最重的炫耀资本。

**等级 / 称号 / 徽章**：从「麦门新客」到「麦门图鉴大师」，
8 枚特质徽章等你解锁（绝版猎人 / 环游麦门 / 暴走探索者…）。

**一键分享卡**：生成麦麦红金配色的个人图鉴卡片（HTML），
晒到群里，朋友问「哪来的」——这就是图鉴的传播闭环。

## 快速开始

### 1 · 配置麦当劳 MCP

申请 Token：<https://open.mcd.cn/mcp>，然后按 `mcp-config.example.json`
配置你的 MCP 客户端（WorkBuddy / Claude Desktop 等）：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": { "Authorization": "Bearer ${MCD_MCP_TOKEN}" }
    }
  }
}
```

### 2 · 安装 Skill

把本仓库克隆到 WorkBuddy 的用户级 Skill 目录：

```bash
git clone https://github.com/juziwa/mcd-codex.git
cp -r mcd-codex ~/.workbuddy/skills/mcd-codex
```

Windows PowerShell 可使用：

```powershell
git clone https://github.com/juziwa/mcd-codex.git
Copy-Item -Recurse -Force .\mcd-codex "$HOME\.workbuddy\skills\mcd-codex"
```

配置中的 `${MCD_MCP_TOKEN}` 仅是占位符。请在本地 MCP 客户端按其文档配置环境变量，
或只在本地配置文件中替换为你申请的 Token；不要把真实 Token 写入仓库或对话。

### 3 · 打开图鉴

对智能体说：

> 打开我的麦麦图鉴

首次打开会自动补录最近订单——「发现你的 X 款历史足迹，图鉴已激活！」
保证不是空壳，开册即有收获。

### 4 · 离线验证（可选）

仓库自带脱敏示例数据（`examples/`），无需 Token 即可跑通全链路：

```bash
python scripts/codex.py absorb-menu --menu examples/menu-regular.json \
  --catalog demo/catalog.json --period regular --store DEMO
python scripts/codex.py absorb-menu --menu examples/menu-breakfast.json \
  --catalog demo/catalog.json --period breakfast --store DEMO
python scripts/codex.py sync --orders examples/order-list.json \
  --codex demo/codex.json --catalog demo/catalog.json
python scripts/codex.py render --codex demo/codex.json \
  --catalog demo/catalog.json --out-md demo/codex.md --out-card demo/card.html
```

纯 Python 标准库实现，无需安装任何依赖。

### 5 · 运行测试

```bash
python -m unittest discover -s tests -v
```

76 个用例覆盖单元（归一化/稀有度/册别）、集成（收录/CLI/渲染）、
边界（取消单/幂等/空数据/无池降级/UR 复活）与真实数据回归。
测试报告见 [docs/test-report.md](docs/test-report.md)。

## 目录结构

```
mcd-codex/
├── README.md                    # 项目介绍（本文件）
├── CONTEST_DECLARATION.md       # 参赛声明（官方原版，未改动）
├── MCP_INTEGRATION.md           # MCP Server / Tool / 调用流程 / 业务价值
├── mcp-config.example.json      # 脱敏 MCP 配置示例（仅环境变量占位符）
├── workbuddy.md                 # WorkBuddy 协作上下文（专项奖励核验）
├── SKILL.md                     # Skill 编排定义
├── scripts/                     # 核心引擎（纯标准库）
│   ├── rarity.py                #   名称归一化 + 稀有度判定
│   ├── catalog.py               #   多时段图鉴池 + 册别归类
│   ├── codex.py                 #   收录引擎 CLI
│   └── render.py                #   图鉴 / 分享卡渲染
├── assets/templates/            # 分享卡 HTML 模板
├── docs/                        # 设计文档 + 测试报告
├── tests/                       # 单元 / 集成 / 边界测试套件
└── examples/                    # 脱敏示例数据（可离线复现）
```

## MCP 集成

本项目**真实调用**麦当劳 MCP Server（`https://mcp.mcd.cn`），核心使用 5 个 Tool：

`order-list` · `query-meals` · `query-nearby-stores` · `query-meal-detail` · `query-order`

详细的调用链路与业务价值见 **[MCP_INTEGRATION.md](MCP_INTEGRATION.md)**，
Skill 编排定义见 [SKILL.md](SKILL.md)。

## 它和别的点餐工具不一样

榜单上的项目大多在帮你**省钱、选餐、规划**——工具理性。
McD Codex 是唯一把用户当**玩家**而不是顾客的：

| 维度 | 工具型项目 | McD Codex |
|---|---|---|
| 心智 | 用完即走的工具 | 越用越厚的图鉴 |
| 资产 | 无 | 图鉴 / 等级 / 徽章 / 绝版卡 |
| 情感 | 无 | 回忆、收集欲、炫耀 |
| 传播 | 弱 | 晒图是刚需 |

麦当劳本就是全球最早的「收集机制」玩家——开心乐园餐玩具、限定杯、联名周边。
McD Codex 做的，是把这套线下收集文化搬进数字世界。

## 目标用户

- **麦门常客**（每周 1-2 次+）：真实使用，形成习惯
- **收集爱好者**（图鉴党 / 盲盒党 / 成就党）：高黏性，主动传播
- **爱晒图的社交用户**：分享卡自带传播闭环

## 路线图

- [x] 双通道点亮（主动收录 + 增量补录）
- [x] 绝版款（UR）自动检测与复活机制
- [x] 等级 / 称号 / 8 枚徽章
- [x] 图鉴渲染与一键分享卡
- [ ] 营养信息扩展（`list-nutrition-foods`，卡片显示热量）
- [ ] 年度麦门报告（你的一月最爱 / 足迹地图）
- [ ] 多城市采样，区域限定品补全图鉴池

## 合规说明

- 本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，**非麦当劳官方产品**
- 参赛声明见 [CONTEST_DECLARATION.md](CONTEST_DECLARATION.md)（官方原版，内容未改动）
- 图鉴数据仅保存在用户本地；仓库中不含任何真实 Token / 个人凭证
- 餐品信息、价格及供应状态以麦当劳官方渠道实时结果为准

## License

[MIT](LICENSE)
