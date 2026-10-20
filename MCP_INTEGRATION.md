# MCP Integration · 麦当劳 MCP 集成说明

## MCP Server

| 项目 | 内容 |
|---|---|
| Server | 麦当劳官方 MCP Server |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权 | `Authorization: Bearer YOUR_MCP_TOKEN` |
| Token 申请 | <https://open.mcd.cn/mcp> |
| 配置示例 | 见 [`mcp-config.example.json`](mcp-config.example.json)（仅环境变量占位符） |

## 使用的 MCP Tools（5 个图鉴核心工具）

| Tool | 用途 | 在本项目中的角色 |
|---|---|---|
| `order-list` | 查询历史订单（最近 10 单） | **用户请求后的增量补录通道**：打开图鉴时按需补录，兜底防漏 |
| `query-nearby-stores` | 查询附近门店 | 定位用户常用门店，获取 `storeCode` 供菜单采样 |
| `query-meals` | 查询当前可售餐品列表 | **图鉴池构建**：双时段采样（当前时段 + 早餐时段），获取 code/name/image/tags，支撑稀有度判定与绝版检测 |
| `query-meal-detail` | 查询餐品详情及套餐组成 | 套餐拆解参考：理解组合餐结构，保证「单品级收录」口径一致 |
| `query-order` | 查询订单详情 | **主动收录通道**：Skill 内下单后确认订单状态（已支付/未取消）再收录 |

辅助工具：菜单采样使用 `now-time-info` 计算早餐预约日期；下单流程使用
`calculate-price` → `create-order`。调用 `create-order` 前必须展示门店、商品、数量与金额，
并取得用户对本次订单的明确确认。

## ⚠️ 响应要先剥壳再落盘

`mcd-mcp` 返回的 `content[0].text` **不是裸 JSON**，而是：

```
# API Response Information
## Response Structure        ← 字段说明（markdown）
...
## Original Response
{"success":true,"code":200,"data":{...}}    ← 真正要存的部分
```

本项目所有 CLI 只吃**原始 JSON**。把整段 text 存成 `.json` 会得到
`query-meals 响应不是有效 JSON`。落盘规则：

1. 取 `## Original Response` 之后的那一段（或最后一个能完整解析的 JSON 对象）
2. 校验 `json.load` 能解析、`success === true`、`code === 200`
3. 任一不满足 → 本次采样作废，**不要覆盖已有快照**（旧池比脏池安全）

`order-list` / `query-meals` / `query-order` 都有这层包装，一视同仁。

## 核心调用流程

### ① 首次打开 / 增量补录

```
order-list
  └→ 保存快照 data/snapshots/order-list.json
       └→ scripts/codex.py sync
            ├─ 展开 orderProductList[].comboItemList → 单品级收录
            ├─ 跳过「订单已取消」
            ├─ 同品合并（code / 归一化名称三通道匹配）
            └─ 输出 new_unlocks（新点亮）+ stats（等级/徽章）
```

### ② 图鉴池构建（每 1-2 周更新）

```
now-time-info → 计算北京时间的下一天日期
query-nearby-stores (beType=1, searchType=2, city, keyword)
  └→ 取常用门店 storeCode
query-meals (storeCode, beType=1, orderType=1)              ← 当前时段菜单
query-meals (storeCode, beType=1, orderType=1,
             reservationDate="yyyy-MM-dd 10:00")              ← 早餐时段菜单
  └→ 保存两份快照 → scripts/codex.py absorb-menu（一次事务式合并）
       └→ 合并为多时段菜单池 data/catalog.json（76 款单品 / 148 个菜单编码）
```

**为什么要双时段采样**：麦当劳菜单按餐段返回，早餐品（麦满分、营养卷、油条）
仅出现在早餐时段菜单。只采当前时段会把大量早餐品误判为绝版（UR）。

**为什么池里只有单品**：148 个菜单编码里近一半是「二件套 / 三件套 / 随心选 /
分享餐」等套餐。图鉴的收录原子单位是订单子项（单品级），套餐会被展开成单品再收录，
若同时进池就会让同一个汉堡占两格、让分母虚高。因此 `absorb-menu` 会跳过套餐
（`skipped_combos`）、周边玩具（`skipped_merch`）和无名条目（`skipped_unknown`），
并把同名多编码（「派」「脆薯饼」）合并成一格。

MCP 调用仅在用户明确请求后按需执行；本项目不做后台轮询、批量循环或定时自动调用。
如果任一菜单响应失败或不含有效餐品，本次不会覆盖已有图鉴池，也不会触发 UR 重判。
同一门店同一时段只保留最近一次成功快照；图鉴池是各门店/时段最新快照的并集，
因此餐品从所有当前快照消失后可被识别为下架，而不是永久残留在历史并集中。

### ③ 下单收录（主动收录，100% 可靠）

```
query-meals → calculate-price → 展示订单并取得明确确认 → create-order
  → query-order（仅接受已支付/制作中/已完成等明确成功状态）
  └→ 保存订单快照 → scripts/codex.py absorb-order
```

### ④ 绝版检测与复活

```
absorb-menu 更新菜单池 → sync 全量重判
  ├─ 池外历史餐品 → UR 绝版款（时代眼泪 💎）
  └─ 菜单池扩充后 UR 回到在售 → 自动降级（复活机制）
```

## 真实数据勘察驱动的关键设计

开发期对真实 MCP 数据的勘察发现，直接决定了收录算法的设计：

1. **订单侧 code 与菜单侧 code 是两套体系**
   实例：订单子项「板烧鸡腿堡」code=901406，菜单单品「板烧鸡腿堡」code=1406；
   套餐内「中薯条」code=501205，菜单单品「薯条」code=4810。
   → 在售匹配采用三通道：code 精确 → 名称归一化（去规格后缀 + 同义词表）→ 名称弱匹配，
     绝版判定保守而准确。

2. **同品多规格多 code**
   「可口可乐大杯/中杯/可乐中杯」三个不同 code 指向同一款「可乐」。
   → 图鉴条目 key 使用归一化身份，同品自动合并计数，杜绝图鉴条目分裂。

3. **`realTotalAmount` 可能为 "0"（用券单）**
   → 不作为消费凭证，收录只看餐品本身。

4. **`order-list` 仅返回最近 10 单、不支持分页**
   → 定位为「增量补录」，主机制走主动收录，不承诺导入全部历史。

## 业务价值

- **用户价值**：消费记忆的资产化——图鉴、等级、绝版卡是 McDonald's 数字生态里
  独一无二的情感沉淀；绝版检测让老账户的历史订单变成炫耀资本。
- **品牌价值**：把麦当劳线下的收集文化 DNA（乐园餐玩具、限定杯、联名周边）
  搬进数字点单场景，天然驱动新品尝试（SSR 限时款）与复购（集齐进度环）。
