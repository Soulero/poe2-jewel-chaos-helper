#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import (
    END,
    LEFT,
    MULTIPLE,
    SINGLE,
    Button,
    Entry,
    Frame,
    Label,
    Listbox,
    Radiobutton,
    Scrollbar,
    StringVar,
    Tk,
    messagebox,
)
from tkinter import ttk

import pyperclip
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import GlobalHotKeys, Key
from pynput.mouse import Button as MouseButton
from pynput.mouse import Controller as MouseController

from app.mod_matcher import (
    CraftCommand,
    any_command_satisfied,
    detect_item_name_from_clipboard,
    list_item_names,
    load_templates,
    load_variations,
    match_clipboard_mods,
    templates_for_item,
)


@dataclass(frozen=True)
class RuntimeConfig:
    click_delay: float = 0.07
    copy_delay: float = 0.08
    loop_interval: float = 0.12


def runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


class ChaosHelperApp:
    def __init__(self, root: Tk, templates_path: Path, variations_path: Path) -> None:
        self.root = root
        self.root.title("PoE2 珠宝词缀辅助")
        self.root.geometry("1180x740")

        self.templates_path = templates_path
        self.variations_path = variations_path
        self.runtime = RuntimeConfig()

        self.templates = []
        self.variations = []
        self.item_names: list[str] = []
        self.current_item_templates = []
        self.filtered_index_to_template_index: list[int] = []
        self.template_display_by_id: dict[str, str] = {}

        self.commands: list[CraftCommand] = []
        self.command_counter = 1
        self.command_presets_path = runtime_base_dir() / "command_presets.json"
        self.command_presets: dict[str, dict] = {}

        self.run_item_name: str = ""
        self.run_templates = []
        self.run_commands: list[CraftCommand] = []

        self.status_text = StringVar(value="状态: 就绪")
        self.search_text = StringVar(value="")
        self.jewel_var = StringVar(value="")
        self.command_mode_var = StringVar(value="and")
        self.count_required_var = StringVar(value="2")
        self.preset_name_var = StringVar(value="")
        self.preset_select_var = StringVar(value="")

        self.ui_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.automation_stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self.hotkey_listener: GlobalHotKeys | None = None

        self.keyboard = KeyboardController()
        self.mouse = MouseController()
        self.input_lock = threading.Lock()

        self._build_ui()
        self._load_data()
        self._load_presets_from_disk()
        self._start_hotkeys()
        self._poll_ui_queue()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        top = Frame(self.root)
        top.pack(fill="x", padx=12, pady=12)

        Label(top, text="模板 CSV:").grid(row=0, column=0, sticky="w")
        Label(top, text=str(self.templates_path)).grid(row=0, column=1, sticky="w")
        Label(top, text="变体 CSV:").grid(row=1, column=0, sticky="w")
        Label(top, text=str(self.variations_path)).grid(row=1, column=1, sticky="w")

        actions = Frame(self.root)
        actions.pack(fill="x", padx=12, pady=(0, 8))

        Label(actions, text="珠宝类型:").pack(side=LEFT)
        self.jewel_combobox = ttk.Combobox(
            actions,
            textvariable=self.jewel_var,
            state="readonly",
            width=18,
        )
        self.jewel_combobox.pack(side=LEFT, padx=(8, 14))
        self.jewel_combobox.bind("<<ComboboxSelected>>", self._on_jewel_changed)

        Label(actions, text="搜索词缀:").pack(side=LEFT)
        search_entry = Entry(actions, textvariable=self.search_text, width=30)
        search_entry.pack(side=LEFT, padx=(8, 8))
        search_entry.bind("<KeyRelease>", self._on_search)

        Button(actions, text="重载 CSV", command=self._load_data).pack(side=LEFT, padx=(0, 6))
        Button(actions, text="开始 (F9)", command=self._start_from_ui).pack(side=LEFT, padx=(0, 6))
        Button(actions, text="停止 (F10)", command=self.stop_automation).pack(side=LEFT, padx=(0, 6))
        Button(actions, text="测试剪贴板解析", command=self._debug_clipboard).pack(side=LEFT, padx=(0, 6))

        body = Frame(self.root)
        body.pack(fill="both", expand=True, padx=12)

        mod_panel = Frame(body)
        mod_panel.pack(side=LEFT, fill="both", expand=True)

        Label(mod_panel, text="当前珠宝可选词缀（可多选）").pack(anchor="w")

        mod_list_container = Frame(mod_panel)
        mod_list_container.pack(fill="both", expand=True, pady=(4, 0))

        self.mod_listbox = Listbox(mod_list_container, selectmode=MULTIPLE, exportselection=False)
        self.mod_listbox.pack(side=LEFT, fill="both", expand=True)

        mod_scrollbar = Scrollbar(mod_list_container, orient="vertical", command=self.mod_listbox.yview)
        mod_scrollbar.pack(side=LEFT, fill="y")
        self.mod_listbox.config(yscrollcommand=mod_scrollbar.set)

        command_panel = Frame(body, width=460)
        command_panel.pack(side=LEFT, fill="y", padx=(14, 0))
        command_panel.pack_propagate(False)

        Label(command_panel, text="命令配置（任意 1 条命中即停止）").pack(anchor="w")

        mode_row = Frame(command_panel)
        mode_row.pack(fill="x", pady=(8, 0))
        Radiobutton(
            mode_row,
            text="与命令（全部满足）",
            variable=self.command_mode_var,
            value="and",
        ).pack(side=LEFT)
        Radiobutton(
            mode_row,
            text="数量命令（至少命中 m 项）",
            variable=self.command_mode_var,
            value="count",
        ).pack(side=LEFT, padx=(8, 0))

        count_row = Frame(command_panel)
        count_row.pack(fill="x", pady=(8, 0))
        Label(count_row, text="数量命令 m:").pack(side=LEFT)
        Entry(count_row, textvariable=self.count_required_var, width=8).pack(side=LEFT, padx=(8, 0))

        add_row = Frame(command_panel)
        add_row.pack(fill="x", pady=(8, 0))
        Button(add_row, text="用当前选择添加命令", command=self._add_command_from_selection).pack(side=LEFT)

        Label(command_panel, text="已创建命令").pack(anchor="w", pady=(10, 0))

        command_list_container = Frame(command_panel)
        command_list_container.pack(fill="both", expand=True, pady=(4, 0))

        self.command_listbox = Listbox(command_list_container, selectmode=SINGLE, exportselection=False)
        self.command_listbox.pack(side=LEFT, fill="both", expand=True)

        command_scrollbar = Scrollbar(
            command_list_container,
            orient="vertical",
            command=self.command_listbox.yview,
        )
        command_scrollbar.pack(side=LEFT, fill="y")
        self.command_listbox.config(yscrollcommand=command_scrollbar.set)

        command_actions = Frame(command_panel)
        command_actions.pack(fill="x", pady=(8, 0))
        Button(command_actions, text="删除选中命令", command=self._remove_selected_command).pack(side=LEFT)
        Button(command_actions, text="清空命令", command=self._clear_commands).pack(side=LEFT, padx=(8, 0))

        Label(command_panel, text="本地命令预设").pack(anchor="w", pady=(10, 0))

        preset_name_row = Frame(command_panel)
        preset_name_row.pack(fill="x", pady=(6, 0))
        Label(preset_name_row, text="预设名:").pack(side=LEFT)
        Entry(preset_name_row, textvariable=self.preset_name_var, width=28).pack(side=LEFT, padx=(8, 0))

        preset_select_row = Frame(command_panel)
        preset_select_row.pack(fill="x", pady=(6, 0))
        Label(preset_select_row, text="已保存:").pack(side=LEFT)
        self.preset_combobox = ttk.Combobox(
            preset_select_row,
            textvariable=self.preset_select_var,
            state="readonly",
            width=28,
        )
        self.preset_combobox.pack(side=LEFT, padx=(8, 0))
        self.preset_combobox.bind("<<ComboboxSelected>>", self._on_preset_selected)

        preset_actions = Frame(command_panel)
        preset_actions.pack(fill="x", pady=(8, 0))
        Button(preset_actions, text="保存当前命令", command=self._save_current_preset).pack(side=LEFT)
        Button(preset_actions, text="加载选中预设", command=self._load_selected_preset).pack(side=LEFT, padx=(8, 0))
        Button(preset_actions, text="删除选中预设", command=self._delete_selected_preset).pack(side=LEFT, padx=(8, 0))

        bottom = Frame(self.root)
        bottom.pack(fill="x", padx=12, pady=12)

        Label(bottom, textvariable=self.status_text, justify="left", anchor="w").pack(fill="x")
        Label(
            bottom,
            text=(
                "流程: 先选珠宝类型 -> 选择词缀 -> 添加命令（与命令/数量命令） -> "
                "游戏内鼠标悬停物品 -> F9 启动。命中任意 1 条命令自动停止。"
            ),
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(8, 0))

    def _set_status(self, text: str) -> None:
        self.status_text.set(f"状态: {text}")

    def _enqueue_status(self, text: str) -> None:
        self.ui_queue.put(("status", text))

    def _poll_ui_queue(self) -> None:
        while not self.ui_queue.empty():
            kind, payload = self.ui_queue.get_nowait()
            if kind == "status":
                self._set_status(payload)
            elif kind == "match":
                self._set_status(payload)
                self.stop_automation(update_status=False)
                print("\a", end="", flush=True)
        self.root.after(80, self._poll_ui_queue)

    def _load_data(self) -> None:
        self.templates = load_templates(self.templates_path)
        self.variations = load_variations(self.variations_path)
        self.item_names = list_item_names(self.variations)
        self.template_display_by_id = {
            template.template_id: template.display_format for template in self.templates
        }

        if not self.item_names:
            raise RuntimeError("mod_variations.csv 未包含 item_name 数据。")

        self.jewel_combobox["values"] = self.item_names
        if self.jewel_var.get().strip() not in self.item_names:
            self.jewel_var.set(self.item_names[0])

        self._switch_active_item(reset_commands=True)
        self._refresh_preset_selector()
        self._set_status(
            f"已加载 templates={len(self.templates)}，variations={len(self.variations)}，珠宝={len(self.item_names)}。"
        )

    def _switch_active_item(self, reset_commands: bool) -> None:
        item_name = self.jewel_var.get().strip()
        self.current_item_templates = templates_for_item(
            self.templates,
            self.variations,
            item_name,
        )
        self._refresh_mod_listbox()
        if reset_commands:
            self._clear_commands(show_status=False)

    def _command_to_dict(self, command: CraftCommand) -> dict:
        return {
            "name": command.name,
            "mode": command.mode,
            "template_ids": list(command.template_ids),
            "min_required": command.min_required,
        }

    def _command_from_dict(self, data: dict, fallback_name: str) -> CraftCommand | None:
        if not isinstance(data, dict):
            return None
        template_ids = data.get("template_ids")
        if not isinstance(template_ids, list):
            return None
        cleaned_ids = [str(item).strip() for item in template_ids if str(item).strip()]
        if not cleaned_ids:
            return None

        mode = str(data.get("mode", "and")).strip()
        if mode not in {"and", "count"}:
            return None

        if mode == "and":
            min_required = len(cleaned_ids)
        else:
            raw_min = data.get("min_required", 1)
            try:
                min_required = int(raw_min)
            except (TypeError, ValueError):
                min_required = 1
            min_required = max(1, min(min_required, len(cleaned_ids)))

        command_name = str(data.get("name", fallback_name)).strip() or fallback_name
        return CraftCommand(
            name=command_name,
            mode=mode,
            template_ids=cleaned_ids,
            min_required=min_required,
        )

    def _refresh_preset_selector(self) -> None:
        names = sorted(self.command_presets.keys())
        self.preset_combobox["values"] = names
        selected = self.preset_select_var.get().strip()
        if selected not in self.command_presets:
            self.preset_select_var.set(names[0] if names else "")

    def _load_presets_from_disk(self) -> None:
        self.command_presets = {}
        if not self.command_presets_path.exists():
            self._refresh_preset_selector()
            return

        try:
            payload = json.loads(self.command_presets_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._set_status(f"读取预设文件失败: {exc}")
            self._refresh_preset_selector()
            return

        raw_presets = {}
        if isinstance(payload, dict):
            raw = payload.get("presets", {})
            if isinstance(raw, dict):
                raw_presets = raw

        for preset_name, preset_data in raw_presets.items():
            if not isinstance(preset_name, str) or not preset_name.strip():
                continue
            if not isinstance(preset_data, dict):
                continue

            item_name = str(preset_data.get("item_name", "")).strip()
            raw_commands = preset_data.get("commands", [])
            if not item_name or not isinstance(raw_commands, list):
                continue

            commands = []
            for index, command_data in enumerate(raw_commands, start=1):
                parsed = self._command_from_dict(command_data, fallback_name=f"命令{index}")
                if parsed:
                    commands.append(self._command_to_dict(parsed))

            if not commands:
                continue

            self.command_presets[preset_name.strip()] = {
                "item_name": item_name,
                "commands": commands,
            }

        self._refresh_preset_selector()

    def _save_presets_to_disk(self) -> None:
        payload = {"version": 1, "presets": self.command_presets}
        self.command_presets_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _read_preset_name_input(self) -> str:
        text = self.preset_name_var.get().strip()
        if text:
            return text
        return self.preset_select_var.get().strip()

    def _on_preset_selected(self, _event=None) -> None:
        selected = self.preset_select_var.get().strip()
        if selected:
            self.preset_name_var.set(selected)

    def _save_current_preset(self) -> None:
        preset_name = self._read_preset_name_input()
        if not preset_name:
            messagebox.showwarning("缺少预设名", "请先输入预设名称。")
            return
        if not self.commands:
            messagebox.showwarning("无命令可保存", "请先至少添加一条命令。")
            return

        item_name = self.jewel_var.get().strip()
        self.command_presets[preset_name] = {
            "item_name": item_name,
            "commands": [self._command_to_dict(command) for command in self.commands],
        }

        self._save_presets_to_disk()
        self._refresh_preset_selector()
        self.preset_select_var.set(preset_name)
        self.preset_name_var.set(preset_name)
        self._set_status(f"已保存预设: {preset_name}（珠宝: {item_name}，命令数: {len(self.commands)}）。")

    def _load_selected_preset(self) -> None:
        preset_name = self._read_preset_name_input()
        if not preset_name:
            messagebox.showwarning("未选择预设", "请先选择或输入预设名称。")
            return
        preset = self.command_presets.get(preset_name)
        if not preset:
            messagebox.showwarning("预设不存在", f"找不到预设: {preset_name}")
            return

        item_name = str(preset.get("item_name", "")).strip()
        if item_name not in self.item_names:
            messagebox.showwarning("珠宝类型不存在", f"预设珠宝类型不在当前数据中: {item_name}")
            return

        self.jewel_var.set(item_name)
        self._switch_active_item(reset_commands=True)

        allowed_ids = {template.template_id for template in self.current_item_templates}
        loaded_commands: list[CraftCommand] = []
        for index, raw_command in enumerate(preset.get("commands", []), start=1):
            parsed = self._command_from_dict(raw_command, fallback_name=f"命令{index}")
            if not parsed:
                continue

            filtered_ids = [template_id for template_id in parsed.template_ids if template_id in allowed_ids]
            if not filtered_ids:
                continue

            if parsed.mode == "and":
                min_required = len(filtered_ids)
            else:
                min_required = max(1, min(parsed.min_required, len(filtered_ids)))

            loaded_commands.append(
                CraftCommand(
                    name=parsed.name,
                    mode=parsed.mode,
                    template_ids=filtered_ids,
                    min_required=min_required,
                )
            )

        if not loaded_commands:
            messagebox.showwarning("预设无可用命令", "预设中的词缀在当前数据中均不可用。")
            self._clear_commands(show_status=False)
            return

        self.commands = loaded_commands
        self.command_counter = len(self.commands) + 1
        self._refresh_command_list()
        self.preset_select_var.set(preset_name)
        self.preset_name_var.set(preset_name)
        self._set_status(f"已加载预设: {preset_name}（珠宝: {item_name}，命令数: {len(self.commands)}）。")

    def _delete_selected_preset(self) -> None:
        preset_name = self._read_preset_name_input()
        if not preset_name:
            messagebox.showwarning("未选择预设", "请先选择或输入预设名称。")
            return
        if preset_name not in self.command_presets:
            messagebox.showwarning("预设不存在", f"找不到预设: {preset_name}")
            return

        confirm = messagebox.askyesno("删除预设", f"确认删除预设 `{preset_name}` 吗？")
        if not confirm:
            return

        del self.command_presets[preset_name]
        self._save_presets_to_disk()
        self._refresh_preset_selector()
        self.preset_name_var.set("")
        self._set_status(f"已删除预设: {preset_name}")

    def _refresh_mod_listbox(self) -> None:
        query = self.search_text.get().strip()
        self.mod_listbox.delete(0, END)
        self.filtered_index_to_template_index.clear()

        for index, template in enumerate(self.current_item_templates):
            combined = f"{template.template_id} {template.display_format} {template.detail} {template.description}"
            if query and query not in combined:
                continue
            self.filtered_index_to_template_index.append(index)
            item_text = f"{template.template_id} | {template.display_format} | {template.detail}"
            self.mod_listbox.insert(END, item_text)

    def _on_search(self, _event=None) -> None:
        self._refresh_mod_listbox()

    def _on_jewel_changed(self, _event=None) -> None:
        self._switch_active_item(reset_commands=True)
        self._set_status(f"已切换珠宝类型: {self.jewel_var.get()}，已清空旧命令。")

    def _selected_template_ids(self) -> list[str]:
        ids: list[str] = []
        for listbox_index in self.mod_listbox.curselection():
            template_index = self.filtered_index_to_template_index[listbox_index]
            ids.append(self.current_item_templates[template_index].template_id)
        return ids

    def _template_label(self, template_id: str) -> str:
        return self.template_display_by_id.get(template_id, template_id)

    def _format_command(self, command: CraftCommand) -> str:
        preview_items = [self._template_label(tid) for tid in command.template_ids[:3]]
        preview = " / ".join(preview_items)
        if len(command.template_ids) > 3:
            preview += " / ..."

        if command.mode == "and":
            return f"{command.name} [与] 全部命中 {len(command.template_ids)} 项 | {preview}"

        return (
            f"{command.name} [数量] 至少 {command.min_required}/{len(command.template_ids)} 项 | "
            f"{preview}"
        )

    def _refresh_command_list(self) -> None:
        self.command_listbox.delete(0, END)
        for command in self.commands:
            self.command_listbox.insert(END, self._format_command(command))

    def _add_command_from_selection(self) -> None:
        selected = self._selected_template_ids()
        if not selected:
            messagebox.showwarning("未选择词缀", "请先在左侧词缀列表中至少选择一项。")
            return

        mode = self.command_mode_var.get().strip()
        if mode not in {"and", "count"}:
            messagebox.showerror("命令类型错误", "命令类型仅支持 and / count。")
            return

        if mode == "and":
            min_required = len(selected)
        else:
            try:
                min_required = int(self.count_required_var.get().strip())
            except ValueError:
                messagebox.showwarning("数量命令参数错误", "m 必须是整数。")
                return
            if min_required < 1 or min_required > len(selected):
                messagebox.showwarning(
                    "数量命令参数错误",
                    f"m 必须在 1 到已选词缀数量 {len(selected)} 之间。",
                )
                return

        command_name = f"命令{self.command_counter}"
        self.command_counter += 1
        self.commands.append(
            CraftCommand(
                name=command_name,
                mode=mode,
                template_ids=selected,
                min_required=min_required,
            )
        )
        self._refresh_command_list()
        self._set_status(f"已添加 {command_name}，当前命令数: {len(self.commands)}。")

    def _remove_selected_command(self) -> None:
        selected = self.command_listbox.curselection()
        if not selected:
            messagebox.showwarning("未选择命令", "请先在右侧命令列表选择一条命令。")
            return
        index = selected[0]
        removed = self.commands.pop(index)
        self._refresh_command_list()
        self._set_status(f"已删除 {removed.name}，当前命令数: {len(self.commands)}。")

    def _clear_commands(self, show_status: bool = True) -> None:
        self.commands.clear()
        self.command_counter = 1
        self._refresh_command_list()
        if show_status:
            self._set_status("已清空全部命令。")

    def _debug_clipboard(self) -> None:
        item_name = self.jewel_var.get().strip()
        templates = templates_for_item(self.templates, self.variations, item_name)

        clip = pyperclip.paste()
        if not clip.strip():
            self._set_status("剪贴板为空，先在游戏里 Ctrl+C 复制物品。")
            return

        result = match_clipboard_mods(clip, templates)
        if not result.matched_template_ids:
            self._set_status("未识别到词缀，请确认客户端语言与 CSV 一致。")
            return

        matched, command_name = any_command_satisfied(result.matched_template_ids, self.commands)
        if matched:
            self._set_status(
                f"剪贴板识别 {len(result.matched_template_ids)} 条，命中 {command_name}。"
            )
        else:
            self._set_status(
                f"剪贴板识别 {len(result.matched_template_ids)} 条，未命中任何命令。"
            )

    def _start_hotkeys(self) -> None:
        self.hotkey_listener = GlobalHotKeys(
            {"<f9>": self._handle_hotkey_start, "<f10>": self._handle_hotkey_stop}
        )
        self.hotkey_listener.start()

    def _handle_hotkey_start(self) -> None:
        self.ui_queue.put(("status", "收到 F9，尝试启动自动化..."))
        self.root.after(0, self._start_from_ui)

    def _handle_hotkey_stop(self) -> None:
        self.root.after(0, self.stop_automation)

    def _start_from_ui(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            self._set_status("自动化已在运行中。")
            return

        if not self.commands:
            messagebox.showwarning("未配置命令", "请先添加至少一条命令。")
            return

        item_name = self.jewel_var.get().strip()
        if not item_name:
            messagebox.showwarning("未选择珠宝", "请先选择珠宝类型。")
            return

        templates = templates_for_item(self.templates, self.variations, item_name)
        if not templates:
            messagebox.showwarning("无词缀数据", f"珠宝 {item_name} 没有可用词缀数据。")
            return

        self.run_item_name = item_name
        self.run_templates = templates
        self.run_commands = list(self.commands)

        self.automation_stop_event.clear()
        self.worker_thread = threading.Thread(target=self._automation_loop, daemon=True)
        self.worker_thread.start()
        self._set_status(
            f"自动化已启动，珠宝={item_name}，命令数={len(self.run_commands)}，等待命中..."
        )

    def stop_automation(self, update_status: bool = True) -> None:
        self.automation_stop_event.set()
        if update_status:
            self._set_status("自动化已停止。")

    def _automation_loop(self) -> None:
        item_name = self.run_item_name
        templates = self.run_templates
        commands = self.run_commands

        while not self.automation_stop_event.is_set():
            self._do_shift_click()
            time.sleep(self.runtime.click_delay)

            self._do_copy_item_text()
            time.sleep(self.runtime.copy_delay)

            clipboard_text = pyperclip.paste()
            if not clipboard_text.strip():
                self._enqueue_status("剪贴板为空，继续重试...")
                time.sleep(self.runtime.loop_interval)
                continue

            detected_item = detect_item_name_from_clipboard(clipboard_text, self.item_names)
            if detected_item and detected_item != item_name:
                self._enqueue_status(
                    f"检测到当前物品为 {detected_item}，与目标珠宝 {item_name} 不一致，已跳过本轮。"
                )
                time.sleep(self.runtime.loop_interval)
                continue

            result = match_clipboard_mods(clipboard_text, templates)
            matched, command_name = any_command_satisfied(result.matched_template_ids, commands)
            if matched:
                summary = ",".join(result.matched_template_ids)
                self.ui_queue.put(
                    (
                        "match",
                        f"命中 {command_name}，已停止。识别词缀: {summary}",
                    )
                )
                return

            self._enqueue_status(
                f"未命中命令；当前识别 {len(result.matched_template_ids)} 条词缀，继续洗词缀..."
            )
            time.sleep(self.runtime.loop_interval)

    def _do_shift_click(self) -> None:
        with self.input_lock:
            self.keyboard.press(Key.shift)
            self.mouse.click(MouseButton.left, 1)
            self.keyboard.release(Key.shift)

    def _do_copy_item_text(self) -> None:
        with self.input_lock:
            self.keyboard.press(Key.ctrl)
            self.keyboard.press("c")
            self.keyboard.release("c")
            self.keyboard.release(Key.ctrl)

    def _on_close(self) -> None:
        self.stop_automation(update_status=False)
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PoE2 珠宝混沌石辅助工具（本地版）")
    root_dir = runtime_base_dir()
    parser.add_argument(
        "--templates",
        default=str(root_dir / "mod_templates.csv"),
        help="mod_templates.csv 路径",
    )
    parser.add_argument(
        "--variations",
        default=str(root_dir / "mod_variations.csv"),
        help="mod_variations.csv 路径",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    templates_path = Path(args.templates).resolve()
    variations_path = Path(args.variations).resolve()
    if not templates_path.exists():
        raise SystemExit(f"模板文件不存在: {templates_path}")
    if not variations_path.exists():
        raise SystemExit(f"变体文件不存在: {variations_path}")

    root = Tk()
    ChaosHelperApp(root, templates_path=templates_path, variations_path=variations_path)
    root.mainloop()


if __name__ == "__main__":
    main()
