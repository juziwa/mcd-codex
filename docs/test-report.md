# 测试报告 · 麦麦图鉴（McD Codex）

> 测试时间：2026-10-11 · 测试环境：Windows / Python 3.13.12（仅标准库）
> 运行方式：`python -m unittest discover -s tests -v`

## 一、测试结论

| 指标 | 结果 |
|---|---|
| 用例总数 | **76** |
| 通过 | **76** |
| 失败 / 错误 | 0 |
| 测试耗时 | ~0.7s |
| 测试后发现缺陷 | **5 个（均已修复并补回归用例）** |

## 二、测试范围

| 层次 | 类 | 用例数 | 覆盖点 |
|---|---|:---:|---|
| 单元 | `TestNormalize` | 5 | 规格后缀剥离、符号/引号清洗、同义词、口味别名与身份分离、空值 |
| 单元 | `TestWeakMatch` | 3 | 子串弱匹配、短名拒绝（防「派」吞并）、无关名拒绝 |
| 单元 | `TestClassify` | 7 | UR 判定、联名 SSR、上新标签 SSR、早餐限时 SSR、regular 不判限时、人气 SR、默认 R |
| 单元 | `TestIsLimited` | 2 | 联名关键词入限定册、上新普通品不入册 |
| 单元 | `TestBookOf` | 3 | 分类优先、名称兜底、默认册 |
| 单元 | `TestCatalogMatching` | 6 | 四通道匹配（code / 名称 / 别名 / 弱匹配）、未命中、在售判定 |
| 单元 | `TestCatalogBuild` | 8 | 时段合并、幂等、tags 合并、同名多 code、真实快照池规模、失败响应拒绝、原子回滚、无状态字段兼容 |
| 集成 | `TestAbsorbOrder` | 13 | 组合餐展开、单品直购、取消单、订单幂等、数量累加、同品合并、口味槽位合并、无池降级、门店聚合、首次点亮时间不变 |
| 集成 | `TestReclassifyRevive` | 2 | UR 复活机制、空池保护 |
| 单元 | `TestStats` | 5 | 等级 9 个边界值、3 类徽章、最爱/珍宝 |
| 集成 | `TestRender` | 5 | Markdown 六册与剪影、分享卡占位符零残留、无池渲染、默认模板回落、模板路径存在性 |
| 集成 | `TestCli` | 11 | 全链路 CLI、CLI 幂等、渲染产物、缺失 codex 容错、订单形态解析、默认路径锚定、跨 cwd 执行、缺失池降级、失败响应保护、双时段事务、双时段成功 |
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
| 2 | regular 单时段被误判 SSR 限时款 | `test_regular_period_is_not_limited` |
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

## 四、真实 MCP 端到端验证

| 环节 | 方式 | 结果 |
|---|---|---|
| 实时查询订单 | 真实调用 `order-list` | 成功，10 单（9 完成 / 1 取消） |
| 时间核验 | 真实调用 `now-time-info` | 成功（2026-10-11 01:59:36，GMT+8） |
| 图鉴池 | 真实 `query-meals` 双时段采样 | 148 款（汉堡 20 / 早餐 55 / 小食 34 / 甜品 7 / 饮品 29 / 限定 3） |
| 冷启动补录 | 全新建 codex 状态 | 点亮 13 款，等级 Lv.2 常客 |
| 幂等复录 | 同一批订单二次 sync | 新增 0，点亮数稳定 13 |
| 取消单排除 | 校验取消单子项 | 「韩式甜辣酱鸡块」等未入图鉴 ✓ |
| UR 检测 | 对比菜单池 | 「培根蔬萃双层牛堡」「泰式炭烤风味猪猪堡」判 UR ✓ |
| 渲染 | Markdown + 分享卡 | 占位符零残留 ✓ |
| Skill 安装完整性 | 语法编译 + frontmatter + 仓库/安装目录一致性 | PASS（0 问题） |

## 五、遗留风险与未覆盖项

| 项 | 说明 | 建议 |
|---|---|---|
| 真实下单链路 | 未执行 `create-order`（会产生真实交易） | 上线前由用户用小额订单人工验证一次 |
| MCP 字段变更 | 菜单/订单结构若调整，匹配逻辑需同步 | 已用三通道 + 弱匹配提高容错；建议每 2 周跑一次真实回归 |
| 地域菜单差异 | 图鉴池仅采样单城市单门店 | 按 SKILL.md 流程 C 多城市补充采样 |
| 前端视觉 | 分享卡 HTML 的浏览器渲染效果未做像素级校验 | 已在预览面板目视确认 |
