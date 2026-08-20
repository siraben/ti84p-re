#!/usr/bin/env python3
"""Reduce retail-boot ROM bytes and TilEm traces to stable evidence."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from bcall_tables import BOOT_TABLE_ID_RANGES, read_boot_names
from hardware_trace import ResolvedInstruction, iter_resolved_instructions
from rom_image import RomImage
from rom_signatures import TI84_PLUS_OS_255MP_SHA256


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "tools" / "rom.bin"
BOOT_PAGE = 0x3F
BOOT_VERSION_ADDRESS = 0x400F
BOOT_TABLE_FIRST_ID = 0x8018
BOOT_TABLE_LAST_ID = 0x8129
BOOT_TABLE_STUB_START = 0x40D5
BOOT_TABLE_STUB_END = 0x40E3
BOOT_CODE_ADDRESS = 0x412C
BOOT_ERASED_TAIL_ADDRESS = 0x7E4E

TILEM_SOURCE = "https://github.com/siraben/tilem-headless"
TILEM_COMMIT = "d1bdc58dd321ae462a701e556fcb62bb925a78b1"
TILEM_BINARY_SHA256 = (
    "cdd257c57b918b8f0b05df6e49f249d4f0461a7c1ed2d9b87fe76fc3d2b0e1ee"
)


@dataclass(frozen=True)
class BootPageLayout:
    """Byte-level partitions of retail Flash page ``3F``."""

    version: str
    reset_stub_start: int
    reset_stub_end: int
    metadata_start: int
    metadata_end: int
    table_first_id: int
    table_last_id: int
    table_ranges: tuple[tuple[int, int], ...]
    table_slots: int
    populated_slots: int
    empty_slots: tuple[int, ...]
    local_targets: int
    external_targets: int
    table_stub_start: int
    table_stub_end: int
    code_start: int
    code_end: int
    erased_tail_start: int
    erased_tail_bytes: int


def digest(path: Path) -> str:
    """Return one file's SHA-256 without retaining it in memory."""

    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def analyze_boot_page(rom: RomImage) -> BootPageLayout:
    """Partition page ``3F`` and classify every retail bcall-table slot."""

    expected_stub = bytes.fromhex("3E07D3043E7FD3063E03D30EC32C81")
    actual_stub = rom.bytes_at(BOOT_PAGE, 0x4000, len(expected_stub))
    if actual_stub != expected_stub:
        raise ValueError("page 3F does not contain the retail reset stub")

    version_bytes = rom.bytes_at(BOOT_PAGE, BOOT_VERSION_ADDRESS, 5)
    if version_bytes[-1] != 0:
        raise ValueError("retail boot version is not NUL terminated")
    try:
        version = version_bytes[:-1].decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("retail boot version is not ASCII") from error

    empty: list[int] = []
    local_targets = 0
    external_targets = 0
    populated = 0
    for first, last in BOOT_TABLE_ID_RANGES:
        for identifier in range(first, last + 1, 3):
            entry = rom.bytes_at(BOOT_PAGE, 0x4000 + (identifier & 0x3FFF), 3)
            if entry == b"\xFF\xFF\xFF":
                empty.append(identifier)
                continue
            populated += 1
            raw_page = entry[2]
            if raw_page & 0x3F == BOOT_PAGE:
                local_targets += 1
            else:
                external_targets += 1

    tail = rom.bytes_at(
        BOOT_PAGE,
        BOOT_ERASED_TAIL_ADDRESS,
        0x8000 - BOOT_ERASED_TAIL_ADDRESS,
    )
    if set(tail) != {0xFF}:
        raise ValueError("retail boot erased tail contains non-0xFF bytes")

    return BootPageLayout(
        version=version,
        reset_stub_start=0x4000,
        reset_stub_end=0x400E,
        metadata_start=BOOT_VERSION_ADDRESS,
        metadata_end=0x4017,
        table_first_id=BOOT_TABLE_FIRST_ID,
        table_last_id=BOOT_TABLE_LAST_ID,
        table_ranges=BOOT_TABLE_ID_RANGES,
        table_slots=sum(
            (last - first) // 3 + 1 for first, last in BOOT_TABLE_ID_RANGES
        ),
        populated_slots=populated,
        empty_slots=tuple(empty),
        local_targets=local_targets,
        external_targets=external_targets,
        table_stub_start=BOOT_TABLE_STUB_START,
        table_stub_end=BOOT_TABLE_STUB_END,
        code_start=BOOT_CODE_ADDRESS,
        code_end=BOOT_ERASED_TAIL_ADDRESS - 1,
        erased_tail_start=BOOT_ERASED_TAIL_ADDRESS,
        erased_tail_bytes=len(tail),
    )


TRACE_POINTS = {
    "reset_entry": ("page_3F", 0x4000),
    "first_key_compare": ("page_3F", 0x4230),
    "fast_os_check": ("page_3F", 0x4238),
    "fast_os_jump": ("page_3F", 0x4248),
    "stat_recovery": ("page_3F", 0x4270),
    "del_recovery": ("page_3F", 0x4279),
    "unreferenced_mode_dispatch": ("page_3F", 0x427E),
    "recovery_init": ("page_3F", 0x42B3),
    "diagnostic_entry": ("page_3F", 0x4504),
    "receive_loop": ("page_3F", 0x5C7E),
    "link_receive_wait": ("page_3F", 0x63B2),
    "usb_receive_attempt": ("page_2F", 0x4145),
    "os_handoff_vector": ("ram", 0x0053),
    "os_handoff_body": ("ram", 0x0C4F),
}

KEY_NAMES = {
    0x00: "none",
    0x20: "STAT",
    0x37: "MODE",
    0x38: "DEL",
}


@dataclass(frozen=True)
class BootTraceObservation:
    """Selected control-flow facts from one complete reset trace."""

    total_instructions: int
    page_3f_instructions: int
    first_key_code: int
    first_key_name: str
    disposition: str
    point_visits: dict[str, int]
    first_visits: dict[str, dict[str, int]]


def observe_boot_trace(events: Iterable[ResolvedInstruction]) -> BootTraceObservation:
    """Reduce one resolved trace without retaining its instruction stream."""

    names_by_point = {point: name for name, point in TRACE_POINTS.items()}
    counts: Counter[str] = Counter()
    first_visits: dict[str, dict[str, int]] = {}
    first_key_code: int | None = None
    total = 0
    page_3f = 0

    for event in events:
        total += 1
        page_3f += event.space == "page_3F"
        name = names_by_point.get((event.space, event.address))
        if name is None:
            continue
        counts[name] += 1
        first_visits.setdefault(
            name,
            {
                "instruction_index": event.instruction_index,
                "clock": event.clock,
            },
        )
        if name == "first_key_compare" and first_key_code is None:
            first_key_code = event.af >> 8

    if first_key_code is None:
        raise ValueError("trace does not reach the first retail-boot key comparison")

    if counts["del_recovery"]:
        disposition = "DEL link recovery"
    elif counts["stat_recovery"]:
        disposition = "STAT USB-first recovery"
    elif counts["os_handoff_vector"]:
        disposition = (
            "MODE ignored; OS handoff"
            if first_key_code == 0x37
            else "OS handoff"
        )
    else:
        disposition = "unclassified"

    return BootTraceObservation(
        total_instructions=total,
        page_3f_instructions=page_3f,
        first_key_code=first_key_code,
        first_key_name=KEY_NAMES.get(first_key_code, f"0x{first_key_code:02X}"),
        disposition=disposition,
        point_visits={name: counts[name] for name in TRACE_POINTS},
        first_visits=first_visits,
    )


SCENARIOS = {
    "normal": {
        "macro": "tools/macros/boot-idle.macro",
        "expected_key": 0x00,
        "expected_disposition": "OS handoff",
    },
    "del": {
        "macro": "tools/macros/boot-del-recovery.macro",
        "expected_key": 0x38,
        "expected_disposition": "DEL link recovery",
    },
    "stat": {
        "macro": "tools/macros/boot-stat-recovery.macro",
        "expected_key": 0x20,
        "expected_disposition": "STAT USB-first recovery",
    },
    "mode_ignored": {
        "macro": "tools/macros/boot-mode-ignored.macro",
        "expected_key": 0x37,
        "expected_disposition": "MODE ignored; OS handoff",
    },
}


def analyze_trace(path: Path) -> dict[str, object]:
    """Analyze a TLMT trace and attach its reproducible file identity."""

    observation = observe_boot_trace(
        iter_resolved_instructions(path, initial_mapping="ti84p-reset")
    )
    return {
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        **asdict(observation),
    }


def build_report(
    traces: dict[str, Path],
    *,
    rom_path: Path = DEFAULT_ROM,
    emulator_path: Path | None = None,
) -> dict[str, object]:
    """Build and validate the checked retail-boot evidence report."""

    if set(traces) != set(SCENARIOS):
        missing = sorted(set(SCENARIOS) - set(traces))
        extra = sorted(set(traces) - set(SCENARIOS))
        raise ValueError(f"trace scenarios differ: missing={missing}, extra={extra}")
    rom_digest = digest(rom_path)
    if rom_digest != TI84_PLUS_OS_255MP_SHA256:
        raise ValueError("ROM SHA-256 does not match TI-84 Plus OS 2.55MP")
    emulator_digest = (
        TILEM_BINARY_SHA256 if emulator_path is None else digest(emulator_path)
    )
    if emulator_digest != TILEM_BINARY_SHA256:
        raise ValueError("TilEm binary SHA-256 does not match the pinned build")

    rows: dict[str, object] = {}
    for label, path in traces.items():
        row = analyze_trace(path)
        scenario = SCENARIOS[label]
        if row["first_key_code"] != scenario["expected_key"]:
            raise ValueError(f"{label}: unexpected first key code")
        if row["disposition"] != scenario["expected_disposition"]:
            raise ValueError(f"{label}: unexpected boot disposition")
        rows[label] = {**scenario, **row}

    rom = RomImage.from_path(rom_path)
    layout = analyze_boot_page(rom)
    public_names = read_boot_names(ROOT / "tools" / "ti83plus.inc")
    unnamed_entries = []
    for first, last in BOOT_TABLE_ID_RANGES:
        for identifier in range(first, last + 1, 3):
            if identifier in public_names:
                continue
            entry = rom.bytes_at(BOOT_PAGE, 0x4000 + (identifier & 0x3FFF), 3)
            unnamed_entries.append({
                "id": f"{identifier:04X}",
                "target": f"{entry[2] & 0x3F:02X}:{int.from_bytes(entry[:2], 'little'):04X}",
            })
    return {
        "schema": 1,
        "rom": {"path": "tools/rom.bin", "sha256": rom_digest},
        "emulator": {
            "source": TILEM_SOURCE,
            "commit": TILEM_COMMIT,
            "binary_sha256": emulator_digest,
        },
        "scope": (
            "natural reset, DEL, STAT, and MODE-held startup traces; "
            "raw TLMT files remain outside the repository"
        ),
        "page_layout": asdict(layout),
        "public_table_names": len(public_names),
        "unnamed_entries": unnamed_entries,
        "entry_points": {
            name: f"{space.removeprefix('page_')}:{address:04X}"
            for name, (space, address) in TRACE_POINTS.items()
        },
        "scenarios": rows,
    }


def parse_trace(value: str) -> tuple[str, Path]:
    """Parse a ``LABEL=PATH`` trace argument."""

    try:
        label, path = value.split("=", 1)
    except ValueError:
        raise argparse.ArgumentTypeError("trace must be LABEL=PATH") from None
    if not label or not path:
        raise argparse.ArgumentTypeError("trace must be LABEL=PATH")
    return label, Path(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trace",
        action="append",
        type=parse_trace,
        required=True,
        help="scenario and TLMT path as LABEL=PATH; repeat for all scenarios",
    )
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--emulator", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    traces = dict(args.trace)
    if len(traces) != len(args.trace):
        parser.error("trace labels must be unique")
    try:
        report = build_report(
            traces,
            rom_path=args.rom,
            emulator_path=args.emulator,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"wrote {args.output}: "
        + ", ".join(
            f"{label}={row['disposition']}"
            for label, row in report["scenarios"].items()
        )
    )


if __name__ == "__main__":
    main()
