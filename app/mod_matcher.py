from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

LINE_SPACE_PATTERN = re.compile(r"\s+")
NUMBER_CAPTURE = r"([+-]?\d+(?:\.\d+)?)"

META_PREFIXES = (
    "Item Class:",
    "Rarity:",
    "稀有度:",
    "品质:",
    "Quality:",
    "Quality (",
    "需求:",
    "Requires:",
    "Level:",
    "Str:",
    "Dex:",
    "Int:",
    "力量:",
    "敏捷:",
    "智慧:",
    "护甲:",
    "闪避值:",
    "能量护盾:",
    "Armour:",
    "Evasion Rating:",
    "Energy Shield:",
    "Item Level:",
    "物品等级:",
    "Spirit:",
    "灵魂:",
    "Corrupted",
    "已腐化",
    "Unidentified",
    "未鉴定",
    "Sockets:",
    "插槽:",
    "Waystone Tier:",
    "Rune Sockets:",
)

SEPARATOR = "--------"


@dataclass(frozen=True)
class ModTemplate:
    template_id: str
    display_format: str
    detail: str
    description: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class ModVariation:
    variation_id: str
    template_id: str
    item_name: str
    min_value1: str
    max_value1: str
    min_value2: str
    max_value2: str


@dataclass(frozen=True)
class MatchResult:
    matched_template_ids: list[str]
    matched_lines: list[str]
    ignored_lines: list[str]


@dataclass(frozen=True)
class CraftCommand:
    name: str
    mode: Literal["and", "count"]
    template_ids: list[str]
    min_required: int


def normalize_line(text: str) -> str:
    value = (
        text.replace("−", "-")
        .replace("—", "-")
        .replace("％", "%")
        .replace("（", "(")
        .replace("）", ")")
    )
    return LINE_SPACE_PATTERN.sub(" ", value).strip()


def template_to_regex(display_format: str) -> re.Pattern[str]:
    normalized = normalize_line(display_format)
    escaped = re.escape(normalized)
    escaped = escaped.replace(r"\#", NUMBER_CAPTURE)
    escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(rf"^{escaped}$", re.IGNORECASE)


def load_templates(path: Path) -> list[ModTemplate]:
    templates: list[ModTemplate] = []
    with path.open("r", newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        expected = {"参数名字", "词缀内容", "词缀详情", "详细描述"}
        if not expected.issubset(set(reader.fieldnames or [])):
            raise RuntimeError(f"模板 CSV 缺少必要列: {expected}")

        for row in reader:
            template_id = row["参数名字"].strip()
            display = row["词缀内容"].strip()
            if not template_id or not display:
                continue
            templates.append(
                ModTemplate(
                    template_id=template_id,
                    display_format=display,
                    detail=row["词缀详情"].strip(),
                    description=row["详细描述"].strip(),
                    regex=template_to_regex(display),
                )
            )
    return templates


def load_variations(path: Path) -> list[ModVariation]:
    variations: list[ModVariation] = []
    with path.open("r", newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        expected = {
            "id",
            "template_id",
            "item_name",
            "min_value1",
            "max_value1",
            "min_value2",
            "max_value2",
        }
        if not expected.issubset(set(reader.fieldnames or [])):
            raise RuntimeError(f"变体 CSV 缺少必要列: {expected}")

        for row in reader:
            template_id = row["template_id"].strip()
            if not template_id:
                continue
            variations.append(
                ModVariation(
                    variation_id=row["id"].strip(),
                    template_id=template_id,
                    item_name=row["item_name"].strip(),
                    min_value1=row["min_value1"].strip(),
                    max_value1=row["max_value1"].strip(),
                    min_value2=row["min_value2"].strip(),
                    max_value2=row["max_value2"].strip(),
                )
            )
    return variations


def list_item_names(variations: list[ModVariation]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for variation in variations:
        if variation.item_name and variation.item_name not in seen:
            names.append(variation.item_name)
            seen.add(variation.item_name)
    return names


def template_ids_for_item(variations: list[ModVariation], item_name: str) -> set[str]:
    return {variation.template_id for variation in variations if variation.item_name == item_name}


def templates_for_item(
    templates: list[ModTemplate],
    variations: list[ModVariation],
    item_name: str,
) -> list[ModTemplate]:
    allowed = template_ids_for_item(variations, item_name)
    return [template for template in templates if template.template_id in allowed]


def detect_item_name_from_clipboard(clipboard_text: str, item_names: list[str]) -> str | None:
    candidates = {normalize_line(name) for name in item_names if name.strip()}
    for raw_line in clipboard_text.replace("\r\n", "\n").split("\n"):
        line = normalize_line(raw_line)
        if line in candidates:
            return line
    return None


def likely_metadata_line(line: str) -> bool:
    if not line:
        return True
    if line == SEPARATOR:
        return True
    if line.startswith(META_PREFIXES):
        return True
    lower = line.lower()
    if "(implicit)" in lower or "implicit modifier" in lower:
        return True
    if "（implicit）" in line or "隐式" in line:
        return True
    return False


def candidate_mod_lines(clipboard_text: str) -> tuple[list[str], list[str]]:
    lines = [normalize_line(x) for x in clipboard_text.replace("\r\n", "\n").split("\n")]
    candidates: list[str] = []
    ignored: list[str] = []
    seen_separator = False
    for line in lines:
        if not line:
            continue
        if line == SEPARATOR:
            seen_separator = True
            continue
        if not seen_separator:
            ignored.append(line)
            continue
        if likely_metadata_line(line):
            ignored.append(line)
            continue
        candidates.append(line)
    return candidates, ignored


def _best_template_for_line(line: str, templates: Iterable[ModTemplate]) -> ModTemplate | None:
    matched = [template for template in templates if template.regex.match(line)]
    if not matched:
        return None
    matched.sort(key=lambda item: len(item.display_format), reverse=True)
    return matched[0]


def match_clipboard_mods(clipboard_text: str, templates: list[ModTemplate]) -> MatchResult:
    candidates, ignored = candidate_mod_lines(clipboard_text)
    matched_ids: list[str] = []
    matched_lines: list[str] = []
    for line in candidates:
        best = _best_template_for_line(line, templates)
        if not best:
            ignored.append(line)
            continue
        matched_ids.append(best.template_id)
        matched_lines.append(line)
    return MatchResult(matched_template_ids=matched_ids, matched_lines=matched_lines, ignored_lines=ignored)


def is_exact_target_match(found_template_ids: list[str], target_template_ids: list[str]) -> bool:
    return Counter(found_template_ids) == Counter(target_template_ids)


def is_command_satisfied(found_template_ids: list[str], command: CraftCommand) -> bool:
    found_counter = Counter(found_template_ids)
    required_counter = Counter(command.template_ids)

    if command.mode == "and":
        return all(found_counter[key] >= need for key, need in required_counter.items())

    if command.mode == "count":
        matched = sum(1 for template_id in required_counter if found_counter[template_id] > 0)
        return matched >= command.min_required

    raise ValueError(f"不支持的命令模式: {command.mode}")


def any_command_satisfied(
    found_template_ids: list[str],
    commands: list[CraftCommand],
) -> tuple[bool, str]:
    for command in commands:
        if is_command_satisfied(found_template_ids, command):
            return True, command.name
    return False, ""
