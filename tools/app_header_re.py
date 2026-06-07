#!/usr/bin/env python3
"""Fetch and inspect TI-83+/84+ Flash App headers.

The downloaded applications are local RE samples and should live under the
gitignored tools/app-samples/ directory. The parser handles GraphLink/TIFL
.8xk files whose payload is Intel HEX text.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
import shutil
from urllib.request import urlretrieve
from zipfile import ZipFile


SAMPLE_DIR = Path("tools/app-samples")
DOWNLOAD_DIR = SAMPLE_DIR / "downloads"
APP_DIR = SAMPLE_DIR / "apps"
PAGE_BASE = 0x4000
PAGE_SIZE = 0x4000

KNOWN_ARCHIVES = [
    ("axe", "https://www.ticalc.org/pub/83plus/flash/programs/axe.zip"),
    ("mirageos", "https://www.ticalc.org/pub/83plus/flash/shells/mirageos.zip"),
    ("omnicalc", "https://www.ticalc.org/pub/83plus/flash/programs/omnicalc.zip"),
    ("zstart", "https://www.ticalc.org/pub/83plus/flash/programs/zstart.zip"),
    ("usb8x", "https://www.ticalc.org/pub/83plus/flash/programs/usb8x.zip"),
    ("calcsys", "https://www.ticalc.org/pub/83plus/flash/programs/calcsys.zip"),
    ("symbolic", "https://www.ticalc.org/pub/83plus/flash/programs/symbolic.zip"),
    ("batlib", "https://www.ticalc.org/pub/83plus/flash/libs/batlib.zip"),
]

FIELD_NAMES = {
    0x020: "date-stamp signature / app-owned payload",
    0x032: "date stamp",
    0x801: "developer/signing key",
    0x802: "program revision",
    0x803: "build number",
    0x804: "app name",
    0x807: "final field",
    0x808: "page count",
    0x809: "disable TI splash screen",
    0x80C: "lowest basecode",
}

EPOCH_1997 = datetime(1997, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Field:
    number: int
    addr: int
    size: int
    header_size: int
    data: bytes
    raw_header: bytes


@dataclass(frozen=True)
class AppHeader:
    path: Path
    page_count: int
    master_size: int
    fields: list[Field]
    entry: bytes
    notes: list[str]


def fetch_known_archives() -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    APP_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in KNOWN_ARCHIVES:
        archive_path = DOWNLOAD_DIR / f"{name}.zip"
        print(f"download {url}")
        urlretrieve(url, archive_path)
        with ZipFile(archive_path) as archive:
            members = [m for m in archive.namelist() if m.lower().endswith(".8xk")]
            for member in members:
                target = APP_DIR / f"{name}-{Path(member).name}"
                with archive.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"  wrote {target}")


def read_intel_hex_pages(path: Path) -> list[bytes]:
    data = path.read_bytes()
    start = data.find(b":")
    if start < 0:
        raise ValueError(f"{path}: no Intel HEX records found")

    pages: list[bytes] = []
    current: dict[int, int] | None = None
    for line in data[start:].decode("ascii", errors="ignore").splitlines():
        if not line.startswith(":") or len(line) < 11:
            continue
        try:
            count = int(line[1:3], 16)
            addr = int(line[3:7], 16)
            record_type = int(line[7:9], 16)
            payload = bytes.fromhex(line[9 : 9 + count * 2])
        except ValueError:
            continue

        if record_type == 0x02:
            if current:
                pages.append(page_from_records(current))
            current = {}
        elif record_type == 0x00:
            if current is None:
                current = {}
            for i, byte in enumerate(payload):
                current[addr + i] = byte
        elif record_type == 0x01:
            break

    if current:
        pages.append(page_from_records(current))
    if not pages:
        raise ValueError(f"{path}: no data pages decoded")
    return pages


def page_from_records(records: dict[int, int]) -> bytes:
    return bytes(records.get(addr, 0xFF) for addr in range(PAGE_BASE, PAGE_BASE + PAGE_SIZE))


def field_size(page: bytes, offset: int) -> tuple[int, int]:
    nibble = page[offset + 1] & 0x0F
    if nibble <= 0x0C:
        return nibble, 2
    if nibble == 0x0D:
        return page[offset + 2], 3
    if nibble == 0x0E:
        return int.from_bytes(page[offset + 2 : offset + 4], "big"), 4
    return int.from_bytes(page[offset + 2 : offset + 6], "big"), 6


def parse_fields(page: bytes) -> tuple[int, list[Field]]:
    master_size, master_header_size = field_size(page, 0)
    fields: list[Field] = []
    offset = master_header_size
    while offset < 0x200:
        if page[offset] == 0xFF:
            break
        size, header_size = field_size(page, offset)
        number = (page[offset] << 4) | (page[offset + 1] >> 4)
        data_start = offset + header_size
        # Field 807 terminates OS/app headers. Its encoded length is ignored by
        # the boot/app-header walkers, so treat its payload as empty even when
        # the following four size bytes are nonzero in a modified app.
        effective_size = 0 if number == 0x807 else size
        fields.append(
            Field(
                number=number,
                addr=PAGE_BASE + offset,
                size=effective_size,
                header_size=header_size,
                data=page[data_start : data_start + effective_size],
                raw_header=page[offset:data_start],
            )
        )
        offset = data_start + effective_size
        if number == 0x807:
            break
    return master_size, fields


def printable(data: bytes) -> str:
    out = []
    for byte in data:
        if 32 <= byte <= 126:
            out.append(chr(byte))
        elif byte == 0:
            out.append("\\0")
        else:
            out.append(".")
    return "".join(out)


def field_summary(field: Field) -> str:
    return f"{field.number:03X}@{field.addr:04X}+{field.size} {field_value(field)}"


def field_value(field: Field) -> str:
    name = FIELD_NAMES.get(field.number, "unknown")
    data = field.data
    if field.number == 0x801 and data:
        return f"{name}: {int.from_bytes(data, 'big'):04X}"
    if field.number in (0x802, 0x803, 0x808) and data:
        return f"{name}: {data[0]}"
    if field.number == 0x804:
        app = data.decode("ascii", errors="replace").rstrip("\0 ")
        return f"{name}: {app}"
    if field.number == 0x809:
        if data:
            return f"{name}; {len(data)} app-owned byte(s)"
        return f"{name}: present"
    if field.number == 0x80C and len(data) >= 2:
        return f"{name}: {data[0]}.{data[1]:02d}"
    if field.number == 0x032 and len(data) >= 5:
        seconds = int.from_bytes(data[1:5], "big")
        stamp = EPOCH_1997 + timedelta(seconds=seconds)
        return f"{name}: {stamp.date().isoformat()}"
    if field.number == 0x020:
        return f"{name}: {len(data)} byte(s)"
    if field.number == 0x807:
        return f"{name}: terminator"
    return f"{name}: {data.hex(' ').upper()}"


def final_end(fields: list[Field]) -> int | None:
    for field in fields:
        if field.number == 0x807:
            return field.addr + field.header_size + field.size
    return None


def app_name(fields: list[Field]) -> str:
    for field in fields:
        if field.number == 0x804:
            return printable(field.data).rstrip("\\0 ").strip() or "(blank)"
    return "(unknown)"


def page_count(fields: list[Field]) -> int | None:
    for field in fields:
        if field.number == 0x808 and field.data:
            return field.data[0]
    return None


def interesting_notes(page: bytes, fields: list[Field]) -> list[str]:
    notes: list[str] = []
    sig = next((field for field in fields if field.number == 0x020), None)
    if sig and bytes.fromhex("F1 C1 D1 E1 E5 D5 C5 F5") in sig.data:
        notes.append("020 payload contains the Axe register-save helper at 4037")

    zstart_field = next((field for field in fields if field.number == 0x809 and field.size == 0x0F), None)
    if zstart_field and zstart_field.data.startswith(bytes.fromhex("D5 11 00 80")):
        notes.append("809 payload is a 15-byte zStart Z80 helper")

    end = final_end(fields)
    if end is not None and end < 0x4080:
        start = end - PAGE_BASE
        pre_entry = page[start:0x80]
        runs = non_padding_runs(pre_entry, end)
        if runs:
            notes.append("; ".join(runs))
        else:
            notes.append(f"padding from {end:04X} to 4080")
    elif end == 0x4080:
        notes.append("807 ends exactly at 4080")
    elif end == 0x4070:
        notes.append("807 ends at 4070, followed by padding to 4080")
    return notes


def non_padding_runs(data: bytes, absolute_start: int) -> list[str]:
    runs: list[str] = []
    run_start: int | None = None
    previous = 0
    for i, byte in enumerate(data):
        absolute = absolute_start + i
        if byte not in (0x00, 0xFF):
            if run_start is None:
                run_start = absolute
            previous = absolute
        elif run_start is not None:
            runs.append(format_run(data, absolute_start, run_start, previous))
            run_start = None
    if run_start is not None:
        runs.append(format_run(data, absolute_start, run_start, previous))
    return runs


def format_run(data: bytes, absolute_start: int, run_start: int, run_end: int) -> str:
    offset = run_start - absolute_start
    raw = data[offset : offset + run_end - run_start + 1]
    if raw == bytes.fromhex("C3 80 41 C3 EA 42"):
        return "4049 has JP 4180h; JP 42EAh"
    return f"{run_start:04X}-{run_end:04X}: {raw.hex(' ').upper()}"


def analyze_app(path: Path) -> AppHeader:
    pages = read_intel_hex_pages(path)
    first_page = pages[0]
    master_size, fields = parse_fields(first_page)
    return AppHeader(
        path=path,
        page_count=len(pages),
        master_size=master_size,
        fields=fields,
        entry=first_page[0x80:0x88],
        notes=interesting_notes(first_page, fields),
    )


def print_markdown(headers: list[AppHeader]) -> None:
    print("| file | app name | pages | final field | entry bytes | notes |")
    print("|------|----------|-------|-------------|-------------|-------|")
    for header in headers:
        end = final_end(header.fields)
        end_text = f"{end:04X}" if end is not None else "unresolved"
        notes = "<br>".join(header.notes).replace("|", "\\|")
        print(
            f"| `{header.path.name}` | `{app_name(header.fields)}` | "
            f"{page_count(header.fields) or '?'} / {header.page_count} | "
            f"{end_text}",
            end="",
        )
        print(f" | `{header.entry.hex(' ').upper()}` | {notes} |")


def print_text(headers: list[AppHeader]) -> None:
    for header in headers:
        print(f"\n{header.path}")
        print(f"  app name: {app_name(header.fields)}")
        print(f"  decoded pages: {header.page_count}")
        print("  fields:")
        for field in header.fields:
            print(f"    {field_summary(field)}")
        end = final_end(header.fields)
        print(f"  final end: {end:04X}" if end is not None else "  final end: unresolved")
        print(f"  entry bytes: {header.entry.hex(' ').upper()}")
        for note in header.notes:
            print(f"  note: {note}")


def app_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            out.extend(sorted(path.glob("*.8xk")))
            out.extend(sorted(path.glob("*.8XK")))
        else:
            out.append(path)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[APP_DIR])
    parser.add_argument("--fetch-known", action="store_true", help="download known samples into tools/app-samples/")
    parser.add_argument("--markdown", action="store_true", help="print a Markdown table")
    args = parser.parse_args()

    if args.fetch_known:
        fetch_known_archives()

    headers = [analyze_app(path) for path in app_paths(args.paths)]
    if args.markdown:
        print_markdown(headers)
    else:
        print_text(headers)


if __name__ == "__main__":
    main()
