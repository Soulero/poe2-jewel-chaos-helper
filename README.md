# PoE2 珠宝词缀数据 + 本地混沌石辅助

## 1. 生成本地 CSV 数据

```bash
python3 scripts/extract_sapphire_mods.py --output-dir .
```

脚本会先抓取 `https://poe2db.tw/cn/Modifiers`，自动定位“珠宝”分组并扩展以下 6 类：

- 红玉
- 翡翠
- 蓝宝石
- 失落的红玉
- 失落的翡翠
- 失落的蓝宝石

输出文件：

- `mod_templates.csv`：4 列（`参数名字,词缀内容,词缀详情,详细描述`）
- `mod_variations.csv`：7 列（`id,template_id,item_name,min_value1,max_value1,min_value2,max_value2`）

当前逻辑仅抓取 `ModifiersCalc` 里的 **基础前缀/基础后缀（normal）**，不包含已腐化/渎灵等额外池。

## 2. 安装依赖

```bash
python3 -m pip install -r requirements.txt
```

## 3. 启动辅助工具

```bash
python3 -m app.poe2_chaos_helper \
  --templates ./mod_templates.csv \
  --variations ./mod_variations.csv
```

## 4. GUI 使用流程

1. 在 GUI 顶部先选择珠宝类型。
2. 在左侧列表选择词缀。
3. 在右侧创建命令：
   - 与命令：选中的词缀必须全部命中。
   - 数量命令：先选 n 个词缀，再设置 `m`，命中至少 `m` 个即通过。
4. 可创建多条命令；命中任意 1 条命令即停止。
5. 可将当前命令保存为本地预设，也可加载/删除已保存预设。
6. 预设文件路径：`./command_presets.json`（项目根目录）。
7. 游戏内鼠标悬停物品，按 `F9` 启动自动化循环。
8. 程序循环执行：`Shift+左键` -> `Ctrl+C` -> 解析词缀 -> 按命令判定是否完成。
9. 按 `F10` 可随时停止。

## 5. 解析说明

- `mod_templates.csv` 的 `词缀内容` 会自动转正则（`#` 代表数值占位）。
- 匹配只在“当前选中珠宝类型”的词缀模板中进行。
- 程序会尝试从剪贴板文本识别物品底材名称；若与 GUI 选中的珠宝类型不一致，会跳过该轮。

## 6. 注意事项

- 需要给 Python 进程系统输入权限（macOS 的“辅助功能/输入监控”）。
- 本工具为本地自动化脚本，请自行确认是否符合游戏服务条款和账号风险。
- 技术细节与外部资料见 `docs/technical_materials.md`。

## 7. 生成可分享的 Windows 压缩包（exe + 运行文件）

### 方式 A：GitHub 自动构建（推荐）

1. 推送代码到 GitHub。
2. 打一个版本 tag（示例 `v1.1.0`）并推送：

   ```bash
   git tag v1.1.0
   git push origin v1.1.0
   ```

3. GitHub Actions 会自动执行 `.github/workflows/windows-release.yml`。
4. 构建完成后可在以下位置下载 ZIP：
   - Actions 的 artifact
   - 对应 tag 的 GitHub Release 附件

ZIP 内包含：

- `POE2ChaosHelper.exe`
- `mod_templates.csv`
- `mod_variations.csv`
- `command_presets.json`
- `README.txt`

### 方式 B：本地 Windows 构建

```bash
python -m pip install -r requirements.txt pyinstaller
python scripts/package_windows_release.py --version 1.1.0
```

构建后产物在：

- `release/poe2-chaos-helper_1.1.0.zip`
