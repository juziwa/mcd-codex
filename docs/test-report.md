# 测试报告 · 麦麦图鉴（McD Codex）

> 版本 v2.0 · 测试时间：2026-10-20 · 测试环境：Windows / Python 3.13.12（仅标准库）
> 运行方式：`python -m unittest discover -s tests -v`

## 一、测试结论

| 指标 | 结果 |
|---|---|
| 用例总数 | **113** |
| 通过 | **113** |
| 失败 / 错误 | 0 |
| 测试耗时 | ~0.8s |
| 累计发现缺陷 | **14 个（均已修复并补回归用例）** |
| v2 新增用例 | **30 个**（稀有度梯度 / 套餐过滤 / 格子墙 / 进度条 / 绝版补图 / 离线 Demo） |

## 二、测试范围

| 层次 | 类 | 用例数 | 覆盖点 |
|---|---|:---:|---|
| 单元 | `TestNormalize` | 5 | 规格后缀剥离、符号/引号清洗、同义词、口味别名与身份分离、空值 |
| 单元 | `TestWeakMatch` | 3 | 子串弱匹配、短名拒绝（防「派」吞并）、无关名拒绝 |
| 单元 | `TestClassify` | 9 | UR、联名 SSR、上新 SSR、促销标签不升档、**时段不影响稀有度**、人气 SR、招牌款精确匹配、默认 R、档位序号 |
| 单元 | `TestIsLimited` | 2 | 联名关键词入限定册、上新普通品不入册 |
| 单元 | `TestBookOf` | 5 | 分类优先、名称兜底、默认册、套餐识别、周边识别 |
| 单元 | `TestCatalogMatching` | 6 | 四通道匹配（code / 名称 / 别名 / 弱匹配）、未命中、在售判定 |
| 单元 | `TestCatalogBuild` | 12 | 时段合并、幂等、tags 合并、同名多 code 合并、套餐剔除、全套餐响应拒绝、真实快照池规模、失败响应拒绝、原子回滚、快照替换/并集、无状态字段兼容 |
| 集成 | `TestAbsorbOrder` | 13 | 组合餐展开、单品直购、取消单、订单幂等、数量累加、同品合并、口味槽位合并、无池降级、门店聚合、首次点亮时间不变 |
| 集成 | `TestReclassifyRevive` | 5 | UR 复活、多门店并集复活（单门店误判绝版）、空池保护、临时 key 迁移、迁移时去重合并 |
| 单元 | `TestStats` | 5 | 等级 9 个边界值、3 类徽章、最爱/珍宝 |
| 单元 | `TestStatsExtras` | 1 | 池内稀有度分布、完成度、我的稀有度分布 |
| 集成 | `TestRender` | 7 | Markdown 六册与剪影、进度上限、HTML 动态文本转义、分享卡占位符零残留、无池渲染、默认模板回落、模板路径存在性 |
| 集成 | `TestCodexWall` | 8 | 格子墙占位符零残留、每款一格的完整性、点亮/未点亮分区、剪影与 `???`、官方图与 `onerror` 兜底、绝版殿堂、六册分区与导航、动态文本转义 |
| 集成 | `TestMarkdownVisual` | 5 | `??？` 混排、表头空格、点亮款图片表格、进度条 1/8 格细分、绝版章节 |
| 集成 | `TestRarityBalance` | 6 | 梯度单调、SSR 比例、SR 比例、早餐册不再全限定、单册不被 SSR 霸占、池内无套餐 |
| 集成 | `TestImageBackfill` | 3 | 绝版款补图命中/未命中、未开启探测时绝不联网 |
| 集成 | `TestOfflineDemo` | 1 | `demo.build()` 五种产物齐备、占位符零残留 |
| 集成 | `TestCli` | 11 | 全链路 CLI、CLI 幂等、渲染三产物、缺失 codex 容错、订单形态解析、默认路径锚定、跨 cwd 执行、缺失池降级、失败响应保护、双时段事务、双时段成功 |
| 回归 | `TestRealDataRegression` | 6 | 真实订单数据：取消单排除、UR 准确性、同品合并计数、册别归属、统计合理性、重复补录稳定 |

## 三、测试中发现的缺陷与修复

### 缺陷 0（高，此前轮次发现）：Skill 安装目录缺分享卡模板

- **现象**：`~/.workbuddy/skills/mcd-codex/` 仅有 `SKILL.md` 与 `scripts/`，
  缺 `assets/templates/share-card.html`，分享卡渲染直接 `FileNotFoundError`。
- **根因**：Skill 安装目录与参赛仓库是两份拷贝，首次安装漏拷资源目录。
- **修复**：补齐 `assets/`；并新增按脚本位置定位模板的回落逻辑
  （见缺陷 2 修复），双重保障。
- **回归用例**：`test_default_template_path_exists`、`test_render_outputs`

### 缺陷 1（高）：口味别名污染图鉴身份 key

- **现象**：同义词表把「香芋派→派」用于身份归一化，导致无图鉴池时
  香芋派与菠萝派被合并为一条，且显示名为「香芋派 ×2」——**数据误导**
  （用户实际吃了一次菠萝派）。
- **根因**：一张同义词表同时承担「在售匹配」与「身份合并」两个职责。
- **修复**：拆分为两级——
  `normalize_name()`（身份级：仅规格同义，如中薯条→薯条）与
  `match_name()`（匹配级：追加菜单槽位别名，如香芋派→派）；
  匹配新增独立 alias 通道。
- **效果**：有图鉴池时口味统一点亮菜单槽位「派」（与图鉴格位数口径一致）；
  无池降级时保留真实口味名、互不混淆。
- **回归用例**：`test_menu_alias_not_in_identity`、`test_channel_alias`、
  `test_flavors_merge_to_menu_slot`、`test_flavors_not_merged_without_catalog`

### 缺陷 2（中）：分享卡模板路径依赖工作目录

- **现象**：`render --template` 默认值为相对路径 `assets/templates/…`，
  Skill 从非仓库根目录运行时渲染分享卡直接抛 `FileNotFoundError`。
- **根因**：默认路径相对 cwd 解析。
- **修复**：新增 `default_template_path()` 按**脚本所在位置**定位模板，
  并在模板参数缺省/路径失效时自动回落。
- **回归用例**：`test_share_card_default_template_from_any_cwd`、
  `test_default_template_path_exists`、`test_render_outputs`（改为不传 --template）

### 开发期已修复缺陷（本次回归覆盖）

| # | 缺陷 | 对应回归用例 |
|:--:|---|---|
| 1 | 同品分裂（中薯条两个订单 code 形成两条目） | `test_same_product_different_codes_merged`、`test_same_product_merged` |
| 2 | regular 单时段被误判 SSR 限时款 | `test_period_does_not_affect_rarity` |
| 3 | 香芋派误判 UR（菜单通用名「派」） | `test_ur_detection_accuracy` |
| 4 | 限定册过宽（所有「上新」品入册） | `test_not_limited_for_new_tag` |

### 缺陷 3（中）：CLI 路径依赖工作目录（P2 问题根治）

- **现象**：所有命令行默认路径（`data/…`、`output/…`）与分享卡模板均相对
  cwd 解析；在工作区目录直接执行 `python <skill>/scripts/codex.py stats` 会
  因找不到脚本/数据文件而失败。
- **根因**：默认值与模板路径都依赖当前工作目录。
- **修复**：新增 `ROOT = scripts/ 上级目录` 常量，抽出 `build_parser()`，
  所有默认路径锚定 ROOT；分享卡模板按脚本位置回落。
  **现在从任意工作目录执行都可用，无需先 `cd`。**
- **实测**：工作目录设为 `D:/比赛材料/麦当劳`，直接调用
  `~/.workbuddy/skills/mcd-codex/scripts/codex.py stats|render` →
  正常输出，产物正确落于 Skill 根目录 `output/`。

- **回归用例**：`test_default_paths_rooted_at_project_root`、
  `test_cli_runs_from_other_cwd`、`test_share_card_default_template_from_any_cwd`

### 缺陷 5（高）：菜单接口失败时可能误判全部历史餐品为 UR

- **现象**：菜单请求失败或返回空数据时，空图鉴池会被当作有效池，历史餐品被标记为 UR。
- **修复**：校验 `success`、`data.categories` 和 `data.meals`；空菜单拒绝写入；缺失/空图鉴池按“暂无菜单池”处理，不触发 UR 重判。
- **回归覆盖**：`test_failed_or_empty_menu_response_is_rejected`、
  `test_cli_reports_failed_menu_without_overwriting_catalog`、
  `test_sync_without_catalog_does_not_mark_items_ur`

### 缺陷 6（高）：无菜单池条目补池后可能形成同款双条目

- **现象**：降级收录使用 `n:归一化名称`，后续补充菜单池只更新内容、不迁移 key；再次下单会以菜单 code 新建第二条。
- **修复**：全量重判时把可匹配条目迁移到标准 catalog code；目标已存在时合并次数并保留更早的首次点亮信息。
- **回归覆盖**：`test_no_catalog_item_migrates_and_merges_without_duplication`、`test_reclassify_merges_existing_standard_and_temporary_keys`

### 缺陷 7（高）：历史菜单只增不减导致新下架餐品无法判 UR

- **现象**：旧实现永久累加所有菜单采样，曾经出现过的餐品一直被视为在售。
- **修复**：每个“门店 + 时段”只保留最近一次成功快照，当前图鉴池由各来源最新快照取并集；同来源的新快照替换旧快照。
- **回归覆盖**：`test_latest_snapshot_replaces_same_store_period`、`test_different_store_snapshots_form_current_union`

同时增加 JSON 原子写入、HTML 动态文本转义和 Markdown 进度 100% 上限保护。

### v2（2026-10-20）修复的 7 个交付级缺陷

> 来源：《项目诊断》的 5 个硬伤 + 重构过程中暴露的 2 个新问题。全部补了回归用例。

| # | 缺陷 | 根因 | 修复 | 回归用例 |
|:--:|---|---|---|---|
| 8（高） | SSR 占全池 55%、早餐册 100% 限定 | 「仅早餐时段供应」被判 SSR | 稀有度改按限定属性分层，时段退出判定 | `test_period_does_not_affect_rarity`、`test_breakfast_book_is_not_all_limited`、`test_ssr_ratio_in_range` |
| 9（高） | 「限定特惠」打折被当成限定商品 | 标签子串匹配过宽 | 促销标签白名单排除 | `test_promo_tag_is_not_limited` |
| 10（高） | 图鉴池混入 99 款套餐，分母虚高 | 采样未做单品过滤，与「原子单位=单品」自相矛盾 | `combo_of()` 三重判定 + 周边过滤 + 无名条目过滤 | `test_combo_excluded_from_pool`、`test_all_combo_payload_rejected`、`test_single_item_pool_has_no_combo` |
| 10b（高） | 单门店采样把在售餐品误判为绝版 | 池只来自一家门店 | 多门店菜单取并集 + 复活机制重判 | `test_ur_revives_with_second_store` |
| 11（中） | 同名多编码重复占格（派 / 脆薯饼） | 图鉴池按 code 存储，未按身份去重 | `_merge_duplicate_names()` | `test_duplicate_name_multiple_codes` |
| 12（中） | 视觉层缺失：只有数字与进度条 | 渲染层只输出统计卡 | 新增 `render_codex_wall()` + 重做分享卡 + Markdown 图片表格 | `TestCodexWall`、`TestMarkdownVisual` |
| 13（中） | `??？` 半角全角混排、5% 进度显示为空 | `progress//10` 只取整十格 | 统一 `???`；进度条支持 1/8 格 | `test_no_mixed_question_marks`、`test_progress_bar_has_granularity` |
| 14（低） | 绝版款没有产品图（已下架，无菜单图） | 池外餐品 image 字段为空 | 按商品编码回查官方图 CDN + HEAD 校验 | `TestImageBackfill` |

### 真实 MCP 实测追加发现（2026-10-20 第二轮）

> 前 7 个缺陷靠构造数据就能发现；这 2 个只有接真实 MCP、真实菜单图才会暴露。

| # | 缺陷 | 根因 | 修复 |
|:--:|---|---|---|
| 15（中） | 未点亮格的剪影上能看清官方图角标（「100% 纯牛肉」「限时特惠」），等于把答案写在 `???` 上 | 剪影只用 `grayscale + opacity` 去色，没处理图片自带的角标文字 | `img.sil` 加 `blur(.9px)` 糊掉角标；`.thumb::after` 压一层纸色径向渐变盖住右上角（`z-index:2`，高于图片）；点亮格不受影响 |
| 16（高，文档级） | 照 `SKILL.md` 把 MCP 响应「完整保存」成 `.json`，`absorb-menu` 直接报 `不是有效 JSON` | `mcd-mcp` 返回的 `content[0].text` 是「字段说明 markdown + `## Original Response` + 原始 JSON」，文档写的是「保存响应 JSON」，实现只吃裸 JSON | `SKILL.md` 与 `MCP_INTEGRATION.md` 增补「存快照前先剥壳」章节：只保留 `## Original Response` 之后的内容，并校验 `success/code/json.load` 三关 |

## 四、真实 MCP 端到端验证

| 环节 | 方式 | 结果 |
|---|---|---|
| 实时查询订单 | 真实调用 `order-list` | 成功，10 单（9 完成 / 1 取消） |
| 时间核验 | 真实调用 `now-time-info` | 成功（2026-10-11 01:59:36，GMT+8） |
| 图鉴池 | 真实 `query-meals` 两门店 × 双时段采样 | 208 个菜单编码 → 剔除 99 套餐 / 2 周边 / 1 无名 → 合并同名后 **93 款单品**（汉堡 15 / 早餐 22 / 小食 18 / 甜品 9 / 饮品 27 / 限定 2） |
| 稀有度梯度 | 池内分布统计 | R 56 (60%) / SR 21 (23%) / SSR 16 (17%)，单调递减 ✓ |
| 冷启动补录 | 全新建 codex 状态 | 点亮 13 款，等级 Lv.2 常客 |
| 幂等复录 | 同一批订单二次 sync | 新增 0，点亮数稳定 13 |
| 取消单排除 | 校验取消单子项 | 「韩式甜辣酱鸡块」等未入图鉴 ✓ |
| UR 检测 | 对比菜单池 | 「泰式炭烤风味猪猪堡」判 UR ✓ |
| UR 复活 | 单门店 → 双门店采样 | 「培根蔬萃双层牛堡」由 UR 复活为常规款 ✓ |
| UR 补图 | `--probe-images` HEAD 校验 | 命中 MS_521879，写入后浏览器渲染正常 ✓ |
| 渲染 | 格子墙 + 分享卡 + Markdown | 占位符零残留、页面 1280px / 460px 两档截图目视确认 ✓ |
| 离线 Demo | `python scripts/demo.py` | 5 个产物齐备，全程无 MCP 调用 ✓ |
| Skill 安装完整性 | 语法编译 + frontmatter + 仓库/安装目录一致性 | PASS（0 问题） |

### 第二轮真实回归（2026-10-20 10:06，4 门店）

用真实 MCP 重跑了一遍完整链路，门店从 2 家扩到订单实际覆盖的 4 家珠海门店
（1440040 唐家福乐购 / 1440037 唐家宝龙城 / 1440019 虹晖一路 / 1440034 金湾商都）。
菜单均以 `## Original Response` 之后的原始 JSON 落盘，8 份快照（4 店 × 双时段）。

| 环节 | 结果 |
|---|---|
| 门店并集 | 66 → 94 → 95 → **97 款单品**（第 3/4 家各补 1~2 款本店独家），跳过套餐 409 条（含重复门店） |
| 稀有度梯度 | R 58 (59.8%) / SR 21 (21.6%) / SSR 18 (18.6%)，单调递减 ✓ |
| 订单补录 | 10 单 → 点亮 13 款，Lv.2 常客；取消单子项（麦辣鸡翅/大四角/山葵酱/牧场酱）全部未收录 ✓ |
| UR 判定 | 4 店并集下「泰式炭烤风味猪猪堡」仍判 UR —— 确认是真实下架，不是采样不足的误判 ✓ |
| 图片加载 | Playwright 断言：98 张 `<img>` 全部 `naturalWidth > 0`，**破图 0** ✓ |
| 剪影 | 85 格未点亮全部灰度剪影 + `???`，点亮 12 格 + UR 1 格 = 13 ✓ |
| 渲染 | 97 格 / 分享卡 6 格实物缩略 / Markdown 12 图，无占位符残留 ✓ |

## 五、遗留风险与未覆盖项

| 项 | 说明 | 建议 |
|---|---|---|
| 真实下单链路 | 未执行 `create-order`（会产生真实交易） | 上线前由用户用小额订单人工验证一次 |
| MCP 字段变更 | 菜单/订单结构若调整，匹配逻辑需同步 | 已用三通道 + 弱匹配提高容错；建议每 2 周跑一次真实回归 |
| 地域菜单差异 | 图鉴池只采样珠海一地 4 家门店（97 款单品）；跨城市/机场店/景区店的区域限定款未覆盖 | 按 SKILL.md 流程 C 多城市补充采样；池越大收集感越强，但 UR 语义要求「所有已采样门店都没有」，跨城市采样前需先确认不会误判 |
| 菜品口径的人为取舍 | 「4块麦乐鸡」「迷你新地」等规格变体按常规款处理 | 属于设计取舍，已在 `SIGNATURE_NAMES` 注释说明 |
| 截图非自动化 | `assets/preview/` 的 PNG 由开发者本地 Chromium 生成 | 若要进 CI，可加 Playwright 任务（会引入第三方依赖，与「零依赖」目标冲突） |
