#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> None:
    printable = " ".join(f'"{part}"' if " " in part else part for part in cmd)
    print(f"+ {printable}")
    subprocess.run(cmd, cwd=cwd, check=True)


def infer_version() -> str:
    ref_name = os.getenv("GITHUB_REF_NAME", "").strip()
    if ref_name:
        return ref_name.lstrip("v")
    run_number = os.getenv("GITHUB_RUN_NUMBER", "").strip()
    if run_number:
        return f"build-{run_number}"
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def sanitize_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value.strip())
    cleaned = cleaned.strip("-")
    return cleaned or "build"


def find_built_exe(dist_dir: Path, exe_name: str) -> Path:
    candidates = [dist_dir / f"{exe_name}.exe", dist_dir / exe_name]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Could not find built executable in {dist_dir}. Expected one of: {candidates}"
    )


def write_release_readme(target: Path, exe_name: str) -> None:
    text = (
        "PoE2 Chaos Helper (Windows)\n"
        "===========================\n\n"
        "Files:\n"
        f"- {exe_name}\n"
        "- mod_templates.csv\n"
        "- mod_variations.csv\n"
        "- command_presets.json\n\n"
        "Usage:\n"
        "1. Keep all files in the same folder.\n"
        f"2. Double-click {exe_name} to start the GUI.\n"
        "3. Press F9 to start automation, F10 to stop.\n"
    )
    target.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Windows release ZIP with executable and data files.")
    parser.add_argument("--exe-name", default="POE2ChaosHelper", help="Executable name without extension.")
    parser.add_argument("--package-name", default="poe2-chaos-helper", help="Release folder/zip name prefix.")
    parser.add_argument("--version", default=infer_version(), help="Release version suffix.")
    parser.add_argument("--output-dir", default="release", help="Output directory for release folder and zip.")
    parser.add_argument(
        "--icon",
        default="icon.ico",
        help="Optional icon path relative to repo root. Ignored if not present.",
    )
    parser.add_argument("--no-clean", action="store_true", help="Do not remove old build/dist/release directories.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    exe_stem = sanitize_component(args.exe_name.removesuffix(".exe"))
    package_name = sanitize_component(args.package_name)
    version = sanitize_component(args.version)

    build_dir = root / "build"
    dist_dir = root / "dist"
    release_root = root / args.output_dir
    stage_name = f"{package_name}_{version}"
    stage_dir = release_root / stage_name
    zip_path = release_root / f"{stage_name}.zip"

    if not args.no_clean:
        for path in (build_dir, dist_dir, stage_dir):
            if path.exists():
                shutil.rmtree(path)
        if zip_path.exists():
            zip_path.unlink()

    release_root.mkdir(parents=True, exist_ok=True)

    entry_script = root / "app" / "poe2_chaos_helper.py"
    templates_csv = root / "mod_templates.csv"
    variations_csv = root / "mod_variations.csv"
    for required in (entry_script, templates_csv, variations_csv):
        if not required.exists():
            raise FileNotFoundError(f"Missing required file: {required}")

    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        exe_stem,
        "--collect-submodules",
        "pynput",
        "--add-data",
        f"{templates_csv}{os.pathsep}.",
        "--add-data",
        f"{variations_csv}{os.pathsep}.",
        str(entry_script),
    ]

    icon_path = root / args.icon
    if icon_path.exists():
        pyinstaller_cmd.extend(["--icon", str(icon_path)])

    run(pyinstaller_cmd, cwd=root)

    built_exe = find_built_exe(dist_dir, exe_stem)
    stage_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built_exe, stage_dir / f"{exe_stem}.exe")
    shutil.copy2(templates_csv, stage_dir / templates_csv.name)
    shutil.copy2(variations_csv, stage_dir / variations_csv.name)

    readme_md = root / "README.md"
    if readme_md.exists():
        shutil.copy2(readme_md, stage_dir / readme_md.name)

    (stage_dir / "command_presets.json").write_text(
        "{\n  \"version\": 1,\n  \"presets\": {}\n}\n",
        encoding="utf-8",
    )
    write_release_readme(stage_dir / "README.txt", exe_name=f"{exe_stem}.exe")

    shutil.make_archive(
        base_name=str(zip_path.with_suffix("")),
        format="zip",
        root_dir=release_root,
        base_dir=stage_name,
    )
    print(f"Release directory: {stage_dir}")
    print(f"Release zip: {zip_path}")


if __name__ == "__main__":
    main()
