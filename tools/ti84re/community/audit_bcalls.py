#!/usr/bin/env python3
"""Find numeric bcall use in an extracted community-source corpus.

The scanner recognizes numeric ``bcall``/``b_call`` macro invocations and raw
``rst 28h`` plus ``.dw`` sequences. With ``--symbolic`` it also resolves names
from unambiguous equates in the same extracted archive. It ignores comments and
macro definitions, then compares each identifier with the main and boot maps.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import re
from typing import NamedTuple


SOURCE_SUFFIXES = {".a68", ".asm", ".inc", ".s", ".src", ".z80"}
CALL_RE = re.compile(
    r"(?i)\b(?:b_?call(?:z|nz|c|nc)?)\s*(?:\(\s*)?"
    r"(?:\$|0x)?([0-9a-f]{3,4})h?\b\s*\)?"
)
SYMBOL_CALL_RE = re.compile(
    r"(?i)\b(?:b_?call(?:z|nz|c|nc)?)\s*(?:\(\s*)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\b\s*\)?"
)
RST_RE = re.compile(r"(?i)\brst\s+(?:\$?28h?|0x28)\b")
WORD_RE = re.compile(r"(?i)\.(?:dw|word)\s+(?:\$|0x)?([0-9a-f]{3,4})h?\b")
SYMBOL_WORD_RE = re.compile(
    r"(?i)\.(?:dw|word)\s+([A-Za-z_][A-Za-z0-9_]*)\b"
)
BYTE_DIRECTIVE_RE = re.compile(r"(?i)^\s*\.(?:db|byte)\s+(.+?)\s*$")
DEFINE_RE = re.compile(r"(?i)^\s*[#.]?(?:define|defcont|macro)\b")
EQUATE_RE = re.compile(
    r"(?im)^\s*([A-Za-z_][A-Za-z0-9_]*)\s+(?:equ|=)\s*"
    r"(?:\$|0x)?([0-9a-f]{3,4})h?\b"
)


class Finding(NamedTuple):
    identifier: int
    source: Path
    line: int
    form: str
    text: str


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def code_part(line: str) -> str:
    return line.split(";", 1)[0]


def byte_literal(value: str) -> int | None:
    value = value.strip()
    try:
        if value.startswith("$"):
            result = int(value[1:], 16)
        elif value.lower().startswith("0x"):
            result = int(value[2:], 16)
        elif value.lower().endswith("h"):
            result = int(value[:-1], 16)
        else:
            result = int(value, 10)
    except ValueError:
        return None
    return result if 0 <= result <= 0xFF else None


def scan_file(path: Path, symbols: dict[str, int] | None = None) -> list[Finding]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    findings: list[Finding] = []
    for index, line in enumerate(lines):
        code = code_part(line)
        if DEFINE_RE.match(code):
            continue
        for match in CALL_RE.finditer(code):
            findings.append(
                Finding(int(match.group(1), 16), path, index + 1, "macro", line.strip())
            )
        if symbols is not None:
            for match in SYMBOL_CALL_RE.finditer(code):
                identifier = symbols.get(match.group(1).lower())
                if identifier is not None:
                    findings.append(
                        Finding(
                            identifier,
                            path,
                            index + 1,
                            "macro-symbol",
                            line.strip(),
                        )
                    )
        byte_directive = BYTE_DIRECTIVE_RE.match(code)
        if byte_directive is not None:
            values = [byte_literal(item) for item in byte_directive.group(1).split(",")]
            if len(values) == 3 and all(value is not None for value in values):
                opcode, low, high = values
                identifier = low | (high << 8)
                if opcode == 0xEF and 0x4000 <= identifier < 0x9000:
                    findings.append(
                        Finding(
                            identifier, path, index + 1, "raw-bytes", line.strip()
                        )
                    )
        if not RST_RE.search(code):
            continue
        word = WORD_RE.search(code)
        if word is None:
            for following in lines[index + 1 : index + 4]:
                following_code = code_part(following).strip()
                if not following_code:
                    continue
                word = WORD_RE.search(following_code)
                break
        if word is not None:
            findings.append(
                Finding(int(word.group(1), 16), path, index + 1, "raw-rst", line.strip())
            )
        elif symbols is not None:
            symbol_word = SYMBOL_WORD_RE.search(code)
            if symbol_word is None:
                for following in lines[index + 1 : index + 4]:
                    following_code = code_part(following).strip()
                    if not following_code:
                        continue
                    symbol_word = SYMBOL_WORD_RE.search(following_code)
                    break
            if symbol_word is not None:
                identifier = symbols.get(symbol_word.group(1).lower())
                if identifier is not None:
                    findings.append(
                        Finding(
                            identifier,
                            path,
                            index + 1,
                            "raw-rst-symbol",
                            line.strip(),
                        )
                    )
    return findings


def source_group(source: Path, corpus: Path) -> str:
    """Return the extracted archive container that owns a source file."""

    relative = source.relative_to(corpus).as_posix()
    marker = ".zip.contents/"
    if marker in relative:
        return relative.split(marker, 1)[0] + ".zip.contents"
    return source.parent.relative_to(corpus).as_posix()


def read_group_symbols(sources: list[Path], corpus: Path) -> dict[str, dict[str, int]]:
    """Resolve unambiguous equates within each extracted archive."""

    candidates: dict[str, dict[str, set[int]]] = {}
    for source in sources:
        group = source_group(source, corpus)
        group_symbols = candidates.setdefault(group, {})
        text = source.read_text(encoding="utf-8", errors="replace")
        for match in EQUATE_RE.finditer(text):
            identifier = int(match.group(2), 16)
            if 0x4000 <= identifier < 0x9000:
                group_symbols.setdefault(match.group(1).lower(), set()).add(identifier)
    return {
        group: {
            name: next(iter(values))
            for name, values in names.items()
            if len(values) == 1
        }
        for group, names in candidates.items()
    }


def read_main_names(path: Path) -> dict[int, str]:
    result: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and re.fullmatch(r"[0-9A-Fa-f]{4}", fields[0]):
            result[int(fields[0], 16)] = fields[1]
    return result


def read_target_names(path: Path) -> dict[int, str]:
    result: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and re.fullmatch(r"[0-9A-Fa-f]{4}", fields[1]):
            result[int(fields[1], 16)] = fields[0]
    return result


def read_equates(path: Path) -> dict[int, str]:
    result: dict[int, str] = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    for match in EQUATE_RE.finditer(text):
        identifier = int(match.group(2), 16)
        if 0x4000 <= identifier < 0x9000:
            result.setdefault(identifier, match.group(1))
    return result


def archive_identity(
    source: Path, corpus: Path, inventory: dict[str, str]
) -> tuple[str, str]:
    relative = source.relative_to(corpus).as_posix()
    marker = ".zip.contents/"
    if marker not in relative:
        return "", ""
    archive_path = relative.split(marker, 1)[0] + ".zip"
    return archive_path, inventory.get(archive_path, "")


def read_inventory(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as stream:
        return {
            row["archive_path"]: row["sha256"]
            for row in csv.DictReader(stream)
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--all", action="store_true", help="include mapped identifiers")
    parser.add_argument(
        "--symbolic",
        action="store_true",
        help="also resolve symbolic bcall operands from unambiguous archive-local equates",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("tools/data/community-archive-inventory.csv"),
    )
    parser.add_argument("--main-map", type=Path, default=Path("tools/symbols/bcalls.txt"))
    parser.add_argument(
        "--boot-map", type=Path, default=Path("tools/symbols/bcalls8x_targets.txt")
    )
    parser.add_argument("--include", type=Path, default=Path("tools/symbols/ti83plus.inc"))
    args = parser.parse_args()

    corpus = args.corpus.resolve()
    main_names = read_main_names(args.main_map)
    boot_names = read_target_names(args.boot_map)
    include_names = read_equates(args.include)
    inventory = read_inventory(args.inventory)

    sources = [
        source
        for source in sorted(corpus.rglob("*"))
        if source.is_file() and source.suffix.lower() in SOURCE_SUFFIXES
    ]
    symbols = read_group_symbols(sources, corpus) if args.symbolic else {}
    findings: list[Finding] = []
    for source in sources:
        findings.extend(
            scan_file(source, symbols.get(source_group(source, corpus)))
        )

    rows = []
    for finding in findings:
        if 0x4000 <= finding.identifier < 0x8000 and (
            finding.identifier - 0x4000
        ) % 3:
            status = "invalid-main-alignment"
            map_name = ""
        elif finding.identifier in main_names:
            status = "mapped-main"
            map_name = main_names[finding.identifier]
        elif finding.identifier in boot_names:
            status = "mapped-boot"
            map_name = boot_names[finding.identifier]
        elif 0x4000 <= finding.identifier < 0x8000:
            status = "unmapped-main"
            map_name = ""
        elif 0x8000 <= finding.identifier < 0x9000:
            status = "unmapped-boot"
            map_name = ""
        else:
            status = "out-of-range"
            map_name = ""
        if not args.all and status in {"mapped-main", "mapped-boot"}:
            continue
        archive_path, archive_sha256 = archive_identity(
            finding.source, corpus, inventory
        )
        rows.append(
            {
                "bcall_id": f"{finding.identifier:04X}",
                "map_status": status,
                "map_name": map_name,
                "include_name": include_names.get(finding.identifier, ""),
                "archive_path": archive_path,
                "archive_sha256": archive_sha256,
                "source_path": finding.source.relative_to(corpus).as_posix(),
                "source_sha256": digest(finding.source),
                "line": finding.line,
                "form": finding.form,
                "source_text": finding.text,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else [
        "bcall_id", "map_status", "map_name", "include_name", "archive_path",
        "archive_sha256", "source_path", "source_sha256", "line", "form",
        "source_text",
    ]
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    scope = "numeric and archive-resolved symbolic" if args.symbolic else "numeric"
    print(f"scanned {len(findings)} {scope} bcall uses; wrote {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
