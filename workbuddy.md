# workbuddy.md · WorkBuddy 协作记录

> 本项目在开发过程中全程使用腾讯 WorkBuddy（AI 智能体工作台）辅助完成。
> 本文件记录关键协作上下文，用于 WorkBuddy 专项奖励核验。
> （提交前可将 WorkBuddy 完整对话导出内容追加至本文件末尾。）

## 协作概览

- **时间**：2026-10-11
- **任务**：基于《麦麦图鉴-项目方案》，开发麦当劳程序员创意开发大赛（M-CODE）参赛项目
- **形态**：WorkBuddy Skill（配合麦当劳 MCP Server 真实调用）

## WorkBuddy 在本次开发中完成的工作

### 1. 比赛规则与项目方案研读

读取并分析官方活动仓库材料（activityGuidelines.md / README.md / RANKING.md /
CONTEST_DECLARATION.md）与本地《比赛规则梳理.md》《麦麦图鉴-项目方案.md》，
确认：必须文件清单、合规红线（CONTEST_DECLARATION.md 一字不改、
配置仅环境变量占位、禁止刷 Star）、提交时间线（10.25 截止）。

### 2. 麦当劳 MCP 真实数据勘察

通过已连接的 mcd-mcp 连接器，实际调用 4 个 Tool 并分析返回结构：

- `order-list`：确认订单/商品/子项三级结构与取消单标记
- `query-nearby-stores`：获取珠海拱北 5 家门店及 storeCode
- `query-meals`（当前时段 + 早餐时段各一次）：发现菜单按餐段返回
- `query-meal-detail`：确认套餐 rounds/choices 选配结构

**关键发现**（直接决定算法设计）：

1. 订单侧与菜单侧 productCode 是两套体系
   （「板烧鸡腿堡」订单 901406 / 菜单 1406）→ 在售匹配需三通道
2. 菜单按餐段返回，早餐品仅在早餐时段出现 → 绝版检测需双时段采样
3. 同品多规格多 code（可乐大/中杯）→ 图鉴条目需归一化身份合并

### 3. 工程开发

搭建 `mcd-codex` 仓库并实现：

- `scripts/rarity.py`：名称归一化、同义词、R/SR/SSR/UR 判定
- `scripts/catalog.py`：多时段图鉴池、六册归类
- `scripts/codex.py`：双通道收录引擎 + CLI（absorb-menu/absorb-order/sync/stats/render）
- `scripts/render.py`：Markdown 图鉴 + HTML 分享卡
- `assets/templates/share-card.html`：麦麦红金配色分享卡模板
- `SKILL.md`：Skill 编排定义（已安装至 `~/.workbuddy/skills/mcd-codex`）
- 合规文件：CONTEST_DECLARATION.md（官方原版）、mcp-config.example.json（占位符）
- 交付文档：README.md、MCP_INTEGRATION.md、docs/design.md

### 4. 端到端测试与问题修复

用真实 MCP 数据全链路回归（补录 10 单 → 收录 → 稀有度判定 → 渲染），
测试中发现并修复 4 个真实缺陷：

1. 同品分裂（中薯条两个 code 形成两条目）→ 归一化身份 key
2. regular 时段单采样被误判 SSR → 时段判定规则修正
3. 「香芋派」被误判绝版（菜单通用名「派」）→ 同义词表
4. 限定册过宽（所有「上新」品入册）→ 限定册仅收联名关键词款

最终验证：148 款图鉴池、13 款点亮、2 款正确判 UR（时代眼泪）、
同品合并（薯条 ×13）、取消单正确跳过。

### 5. 脱敏与合规

- 真实 orderId 全量替换为 DEMO 前缀后生成 `examples/`（可离线复现）
- `data/codex.json`、`data/snapshots/`、`output/`、`demo/` 进 .gitignore
- 仓库不含任何真实 Token / 个人凭证

## 使用方法

在 WorkBuddy 中对智能体说「打开我的麦麦图鉴」即可触发本 Skill。
