# PoE2 珠宝辅助制作 - 技术数据材料

## 1. 当前数据文件

- `/Users/zhangqingquan/Desktop/poe/mod_templates.csv`
  - 列：`参数名字,词缀内容,词缀详情,详细描述`
  - 作用：词缀模板库（GUI 展示 + 正则匹配模板）
- `/Users/zhangqingquan/Desktop/poe/mod_variations.csv`
  - 列：`id,template_id,item_name,min_value1,max_value1,min_value2,max_value2`
  - 作用：珠宝维度映射 + 数值范围

## 2. 抓取范围

- 来源入口：`https://poe2db.tw/cn/Modifiers`
- 自动定位“珠宝”分组并抓取以下 6 个页面：
  - `/cn/Ruby#ModifiersCalc`（红玉）
  - `/cn/Emerald#ModifiersCalc`（翡翠）
  - `/cn/Sapphire#ModifiersCalc`（蓝宝石）
  - `/cn/Time-Lost_Ruby#ModifiersCalc`（失落的红玉）
  - `/cn/Time-Lost_Emerald#ModifiersCalc`（失落的翡翠）
  - `/cn/Time-Lost_Sapphire#ModifiersCalc`（失落的蓝宝石）

过滤规则：仅写入 `new ModsView({...})` 中 `normal` 里的 `ModGenerationTypeID in {1,2}`（基础前/后缀）。

## 3. GUI 命令系统

命令类型：

- 与命令（`and`）：命令内全部词缀都出现才算命中。
- 数量命令（`count`）：命令内词缀集合命中数 `>= m` 即算命中。

组合规则：

- 可创建多条命令。
- 判定采用 OR：只要命中任意 1 条命令，自动化即停止。

预设持久化：

- GUI 支持保存/加载/删除命令预设。
- 本地文件：`/Users/zhangqingquan/Desktop/poe/command_presets.json`
- 预设结构包含：`预设名`、`珠宝类型`、`命令列表`。

## 4. 匹配与判定细节

- `词缀内容` 的 `#` 在运行时转换为数字占位正则。
- 从 `Ctrl+C` 文本中提取候选词缀行并逐行匹配模板。
- 匹配时按 GUI 当前“珠宝类型”过滤模板，避免跨珠宝误匹配。
- 若剪贴板检测到的底材名与 GUI 选中的珠宝不一致，该轮会跳过。

## 5. PoE2 复制文本相关外部资料

1. 2025-01-25 官方论坛反馈：PoE2 场景下 `Ctrl+Alt+C` 可能无文本输出。建议核心流程优先 `Ctrl+C`。  
   来源：`https://www.pathofexile.com/forum/view-thread/3731592`
2. 2025-04-05 PoB issue 记录：PoE2 0.2.0 文本结构新增 `Requires:` 行，解析器应容忍元数据变化。  
   来源：`https://github.com/PathOfBuildingCommunity/PathOfBuilding/issues/8577`
