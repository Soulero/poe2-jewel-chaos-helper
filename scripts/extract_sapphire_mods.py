#!/usr/bin/env python3
"""Extract six jewel base prefix/suffix mods into local CSV files."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

BASE_URL = "https://poe2db.tw"
MODIFIERS_URL = f"{BASE_URL}/cn/Modifiers"
TARGET_JEWEL_NAMES = (
    "红玉",
    "翡翠",
    "蓝宝石",
    "失落的红玉",
    "失落的翡翠",
    "失落的蓝宝石",
)

MODS_VIEW_PATTERN = re.compile(r"new\s+ModsView\((\{.*?\})\);", re.S)
JEWEL_SECTION_PATTERN = re.compile(r"<li><span class=\"disabled\">珠宝</span></li>(.*?)</div>", re.S)
ANCHOR_PATTERN = re.compile(r"<a\s+[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", re.S)
TAG_PATTERN = re.compile(r"<[^>]+>")
MOD_VALUE_PATTERN = re.compile(
    r"<span[^>]*class=['\"]mod-value['\"][^>]*>(.*?)</span>", re.I | re.S
)
RANGE_PATTERN = re.compile(r"\(\s*([+-]?\d+(?:\.\d+)?)\s*[—-]\s*([+-]?\d+(?:\.\d+)?)\s*\)")
NUMBER_PATTERN = re.compile(r"([+-]?\d+(?:\.\d+)?)")
ID_CLEAN_PATTERN = re.compile(r"[^\w]+", re.UNICODE)


@dataclass(frozen=True)
class JewelTarget:
    item_name: str
    code: str
    url: str


def fetch_page(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError:
        result = subprocess.run(
            ["curl", "-L", url],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout


def html_to_text(value: str) -> str:
    text = (
        value.replace("<br>", "\\n")
        .replace("<br/>", "\\n")
        .replace("<br />", "\\n")
        .replace("\xa0", " ")
    )
    text = TAG_PATTERN.sub("", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def detect_jewel_targets(modifiers_html: str) -> list[JewelTarget]:
    section_match = JEWEL_SECTION_PATTERN.search(modifiers_html)
    if not section_match:
        raise RuntimeError("在 Modifiers 页面找不到“珠宝”分组。")

    by_name: dict[str, JewelTarget] = {}
    for href, label in ANCHOR_PATTERN.findall(section_match.group(1)):
        item_name = html_to_text(label)
        if item_name not in TARGET_JEWEL_NAMES:
            continue

        page_url = urljoin(BASE_URL, href)
        if "#" not in page_url:
            page_url = f"{page_url}#ModifiersCalc"
        code = page_url.split("/cn/")[-1].split("#")[0]
        by_name[item_name] = JewelTarget(item_name=item_name, code=code, url=page_url)

    missing = [name for name in TARGET_JEWEL_NAMES if name not in by_name]
    if missing:
        raise RuntimeError(f"缺少珠宝链接: {missing}")

    return [by_name[name] for name in TARGET_JEWEL_NAMES]


def extract_mods_payload(page_html: str) -> dict:
    match = MODS_VIEW_PATTERN.search(page_html)
    if not match:
        raise RuntimeError("未找到 `new ModsView(...)` 数据，页面结构可能已变化。")
    return json.loads(match.group(1))


def normalize_number(value: str) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def extract_ranges(raw_html: str) -> list[tuple[str, str]]:
    ranges: list[tuple[str, str]] = []
    for fragment in MOD_VALUE_PATTERN.findall(raw_html):
        cleaned = html_to_text(fragment).replace("—", "-")
        range_match = RANGE_PATTERN.search(cleaned)
        if range_match:
            ranges.append(
                (
                    normalize_number(range_match.group(1)),
                    normalize_number(range_match.group(2)),
                )
            )
            continue
        numbers = NUMBER_PATTERN.findall(cleaned)
        if numbers:
            number = normalize_number(numbers[0])
            ranges.append((number, number))
    if ranges:
        return ranges

    fallback = html_to_text(raw_html).replace("—", "-")
    for lo, hi in RANGE_PATTERN.findall(fallback):
        ranges.append((normalize_number(lo), normalize_number(hi)))
    return ranges


def build_display_format(raw_html: str) -> str:
    with_placeholder = MOD_VALUE_PATTERN.sub("#", raw_html)
    return html_to_text(with_placeholder)


def build_param_name(base_name: str, affix_type: str, used: set[str]) -> str:
    candidate = f"{affix_type}_{base_name}".lower()
    candidate = ID_CLEAN_PATTERN.sub("_", candidate).strip("_")
    if not candidate:
        candidate = f"{affix_type}_mod"

    if candidate not in used:
        used.add(candidate)
        return candidate

    suffix = 2
    while True:
        next_candidate = f"{candidate}_{suffix}"
        if next_candidate not in used:
            used.add(next_candidate)
            return next_candidate
        suffix += 1


def extract_badges(mod: dict) -> str:
    badges = [html_to_text(item) for item in mod.get("mod_no", [])]
    badges = [item for item in badges if item]
    return ",".join(badges)


def base_mods(payload: dict) -> Iterable[dict]:
    for mod in payload.get("normal", []):
        generation = str(mod.get("ModGenerationTypeID", ""))
        if generation not in {"1", "2"}:
            continue
        yield mod


def write_templates_csv(path: Path, rows: list[dict]) -> None:
    columns = ["参数名字", "词缀内容", "词缀详情", "详细描述"]
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_variations_csv(path: Path, rows: list[dict]) -> None:
    columns = [
        "id",
        "template_id",
        "item_name",
        "min_value1",
        "max_value1",
        "min_value2",
        "max_value2",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def build_rows(jewels: list[JewelTarget]) -> tuple[list[dict], list[dict], dict[str, dict[str, int]]]:
    templates: list[dict] = []
    variations: list[dict] = []
    used_template_ids: set[str] = set()
    template_key_to_id: dict[tuple[str, str, str], str] = {}
    used_variation_ids: set[str] = set()
    counts: dict[str, dict[str, int]] = {}

    for jewel in jewels:
        page_html = fetch_page(jewel.url)
        payload = extract_mods_payload(page_html)
        prefix_count = 0
        suffix_count = 0

        for mod in base_mods(payload):
            affix_type = "前缀" if str(mod["ModGenerationTypeID"]) == "1" else "后缀"
            display = build_display_format(mod["str"])
            text = html_to_text(mod["str"])
            families = ",".join(mod.get("ModFamilyList", []))
            badges = extract_badges(mod)

            template_key = (affix_type, display, families)
            if template_key in template_key_to_id:
                template_id = template_key_to_id[template_key]
            else:
                template_id = build_param_name(mod.get("Name", "未命名词缀"), affix_type, used_template_ids)
                template_key_to_id[template_key] = template_id
                detail = f"{affix_type};词族:{families or '-'};标签:{badges or '-'}"
                description = f"词缀名:{mod.get('Name', '-')};原文:{text};来源珠宝:{jewel.item_name}"
                templates.append(
                    {
                        "参数名字": template_id,
                        "词缀内容": display,
                        "词缀详情": detail,
                        "详细描述": description,
                    }
                )

            ranges = extract_ranges(mod["str"])
            first = ranges[0] if len(ranges) >= 1 else ("", "")
            second = ranges[1] if len(ranges) >= 2 else ("", "")

            variation_id = f"{template_id}_{jewel.code.lower()}"
            if variation_id in used_variation_ids:
                suffix = 2
                while True:
                    candidate = f"{variation_id}_{suffix}"
                    if candidate not in used_variation_ids:
                        variation_id = candidate
                        break
                    suffix += 1
            used_variation_ids.add(variation_id)

            variations.append(
                {
                    "id": variation_id,
                    "template_id": template_id,
                    "item_name": jewel.item_name,
                    "min_value1": first[0],
                    "max_value1": first[1],
                    "min_value2": second[0],
                    "max_value2": second[1],
                }
            )

            if affix_type == "前缀":
                prefix_count += 1
            else:
                suffix_count += 1

        counts[jewel.item_name] = {
            "prefix": prefix_count,
            "suffix": suffix_count,
            "total": prefix_count + suffix_count,
        }

    return templates, variations, counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取 6 种珠宝基础前/后缀词缀并导出 CSV")
    parser.add_argument(
        "--output-dir",
        default=".",
        help="CSV 输出目录，默认当前目录",
    )
    parser.add_argument(
        "--modifiers-url",
        default=MODIFIERS_URL,
        help="Modifiers 页面 URL",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    modifiers_html = fetch_page(args.modifiers_url)
    jewels = detect_jewel_targets(modifiers_html)
    templates, variations, counts = build_rows(jewels)

    templates_path = output_dir / "mod_templates.csv"
    variations_path = output_dir / "mod_variations.csv"
    write_templates_csv(templates_path, templates)
    write_variations_csv(variations_path, variations)

    print(f"已输出: {templates_path}")
    print(f"已输出: {variations_path}")
    print(f"珠宝种类: {len(jewels)}")
    for jewel in jewels:
        data = counts[jewel.item_name]
        print(
            f"- {jewel.item_name}: 前缀 {data['prefix']} 条, "
            f"后缀 {data['suffix']} 条, 合计 {data['total']} 条"
        )
    print(f"模板总数: {len(templates)}")
    print(f"变体总数: {len(variations)}")


if __name__ == "__main__":
    main()
