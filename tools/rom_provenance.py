#!/usr/bin/env python3
"""Generate ROM provenance manifests and reject mismatched result artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Iterable

from bcall_tables import classify_boot_page
from rom_image import RomImage
from rom_signatures import (
    BOOTFREE_11259_PAGE_SHA256,
    D84PBE1_APPVAR_SHA256,
    D84PBE1_PAGE_SHA256,
    D84PBE2_APPVAR_SHA256,
    D84PBE2_PAGE_SHA256,
    TI84_PLUS_OS_255MP_BOOTFREE_SHA256,
    TI84_PLUS_OS_255MP_SHA256,
    TI84_PLUS_PATCHED_BASE_SHA256,
)


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
PAGE_SIZE = 0x4000
ANALYSIS_SUFFIXES = {".java", ".py", ".sh", ".txt"}
ANALYSIS_NAMES = {"ti83plus.inc"}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def analysis_files() -> list[Path]:
    files = []
    for path in TOOLS.iterdir():
        if not path.is_file():
            continue
        if path.name in ANALYSIS_NAMES or path.suffix in ANALYSIS_SUFFIXES:
            files.append(path)
    return sorted(files)


def combined_digest(paths: Iterable[Path]) -> str:
    result = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        data = path.read_bytes()
        result.update(len(relative).to_bytes(4, "big"))
        result.update(relative)
        result.update(len(data).to_bytes(8, "big"))
        result.update(data)
    return result.hexdigest()


def git_state() -> tuple[str, bool]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT, check=True, text=True, capture_output=True,
    ).stdout)
    return revision, dirty


def component_map(rom_hash: str) -> list[dict[str, object]]:
    if rom_hash == TI84_PLUS_OS_255MP_SHA256:
        return [
            {
                "name": "ti84plus_patched.rom",
                "sha256": TI84_PLUS_PATCHED_BASE_SHA256,
                "page_ranges": ["00-2E", "30-3E"],
            },
            {
                "name": "D84PBE2.8Xv",
                "sha256": D84PBE2_APPVAR_SHA256,
                "decoded_page": "2F",
                "decoded_page_sha256": D84PBE2_PAGE_SHA256,
            },
            {
                "name": "D84PBE1.8Xv",
                "sha256": D84PBE1_APPVAR_SHA256,
                "decoded_page": "3F",
                "decoded_page_sha256": D84PBE1_PAGE_SHA256,
                "note": "byte-identical to page 3F in the patched base",
            },
        ]
    if rom_hash == TI84_PLUS_OS_255MP_BOOTFREE_SHA256:
        return [
            {
                "name": "ti84plus_patched.rom",
                "sha256": TI84_PLUS_PATCHED_BASE_SHA256,
                "page_ranges": ["00-3E"],
                "note": "page 2F is the patched-base page, not D84PBE2",
            },
            {
                "name": "BootFree 11.259 page",
                "decoded_page": "3F",
                "decoded_page_sha256": BOOTFREE_11259_PAGE_SHA256,
                "note": "page identity is known; acquisition artifact is not pinned",
            },
        ]
    return [{"name": "unclassified complete image", "page_ranges": ["00-3F"]}]


def build_manifest(
    rom_path: Path,
    *,
    model: str,
    asic: str,
    os_version: str,
    ghidra_version: str,
) -> dict[str, object]:
    rom = RomImage.from_path(rom_path)
    rom_hash = digest(rom_path)
    scripts = analysis_files()
    revision, dirty = git_state()
    include = TOOLS / "ti83plus.inc"
    return {
        "schema": "ti84p-re.provenance.v1",
        "target": {
            "model": model,
            "asic_revision": asic,
            "os_version": os_version,
        },
        "rom": {
            "path": str(rom_path),
            "sha256": rom_hash,
            "bytes": rom_path.stat().st_size,
            "page_size": PAGE_SIZE,
            "page_count": rom.page_count,
            "boot_page_kind": classify_boot_page(rom),
            "components": component_map(rom_hash),
        },
        "include": {
            "path": "tools/ti83plus.inc",
            "version": "TI-83 Plus Include File 2007-05-07",
            "sha256": digest(include),
        },
        "analysis": {
            "ghidra_version": ghidra_version,
            "git_revision": revision,
            "git_dirty": dirty,
            "script_tree_sha256": combined_digest(scripts),
            "script_file_count": len(scripts),
        },
        "source_command": (
            "python3 tools/rom_provenance.py manifest --rom "
            + str(rom_path)
        ),
    }


def recursive_rom_hashes(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "rom_sha256" and isinstance(item, str):
                found.add(item.lower())
            elif key == "rom" and isinstance(item, dict):
                digest_value = item.get("sha256")
                if isinstance(digest_value, str):
                    found.add(digest_value.lower())
            found.update(recursive_rom_hashes(item))
    elif isinstance(value, list):
        for item in value:
            found.update(recursive_rom_hashes(item))
    return found


def artifact_rom_hashes(path: Path) -> set[str]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as stream:
            rows = csv.DictReader(stream)
            return {
                row["rom_sha256"].lower()
                for row in rows
                if row.get("rom_sha256")
            }
    if path.suffix.lower() == ".json":
        return recursive_rom_hashes(json.loads(path.read_text(encoding="utf-8")))
    raise ValueError(
        f"{path}: raw traces require a JSON provenance sidecar; "
        "pass the sidecar instead"
    )


def manifest_rom_hash(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        value = data["rom"]["sha256"]
    except (KeyError, TypeError) as error:
        raise ValueError(f"{path}: missing rom.sha256") from error
    if not isinstance(value, str):
        raise ValueError(f"{path}: rom.sha256 is not a string")
    return value.lower()


def write_json(value: object, output: Path | None) -> None:
    rendered = json.dumps(value, indent=2) + "\n"
    if output is None:
        print(rendered, end="")
    else:
        output.write_text(rendered, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    manifest = commands.add_parser("manifest")
    manifest.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    manifest.add_argument("--model", default="TI-84 Plus")
    manifest.add_argument("--asic", default="unknown")
    manifest.add_argument("--os-version", default="2.55MP")
    manifest.add_argument("--ghidra-version", default="12.1.2")
    manifest.add_argument("--output", type=Path)

    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("artifacts", type=Path, nargs="+")
    args = parser.parse_args()

    try:
        if args.command == "manifest":
            value = build_manifest(
                args.rom,
                model=args.model,
                asic=args.asic,
                os_version=args.os_version,
                ghidra_version=args.ghidra_version,
            )
            write_json(value, args.output)
            return

        expected = manifest_rom_hash(args.manifest)
        for artifact in args.artifacts:
            observed = artifact_rom_hashes(artifact)
            if not observed:
                raise ValueError(f"{artifact}: no ROM provenance found")
            if observed != {expected}:
                rendered = ", ".join(sorted(observed))
                raise ValueError(
                    f"{artifact}: ROM provenance {rendered} does not match "
                    f"manifest {expected}"
                )
            print(f"{artifact}: ROM provenance matches")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
