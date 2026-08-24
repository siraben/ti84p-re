#!/usr/bin/env python3
"""Validate community VAT/recovery traces and write observation CSV."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import sha256
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tilem_trace_resolve import IDX_PC, iter_records, read_header  # noqa: E402


FIELDS = (
    "scenario", "artifact", "input_state", "observed_result", "target",
    "target_type", "target_page", "target_address", "trace_anchors",
    "trace_sha256", "snapshot_sha256", "input_rom_sha256",
    "output_rom_sha256", "emulator_sha256", "evidence_limit",
)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def logical_ram(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) < 0x8000:
        raise SystemExit(f"logical RAM dump is truncated: {path}")
    return data[:0x8000]


def named_vat(data: bytes, stored_name: bytes) -> dict[str, int]:
    ascending = stored_name[::-1]
    offset = data.find(ascending)
    if offset < 0:
        raise SystemExit(f"VAT name {stored_name.hex()} not found")
    tail = offset + len(stored_name)
    if data[tail] != len(stored_name):
        raise SystemExit(f"VAT name at 0x{offset + 0x8000:04X} lacks length")
    return {
        "type": data[tail + 6],
        "page": data[tail + 1],
        "address": data[tail + 2] << 8 | data[tail + 3],
    }


def payload(data: bytes, vat: dict[str, int], size: int = 4) -> bytes:
    if vat["page"]:
        raise SystemExit("cannot read archived payload from a RAM dump")
    start = vat["address"] - 0x8000
    return data[start:start + size]


def pc_counts(path: Path, wanted: set[int]) -> Counter[int]:
    counts: Counter[int] = Counter()
    with path.open("rb") as stream:
        read_header(stream)
        for record_type, record in iter_records(stream):
            if record_type == 0x01 and record[IDX_PC] in wanted:
                counts[record[IDX_PC]] += 1
    return counts


def anchors(counts: Counter[int], addresses: tuple[int, ...]) -> str:
    return ";".join(f"0x{address:04X}={counts[address]}" for address in addresses)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("/tmp"))
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.input_dir
    rom_hash = digest(args.rom)
    emulator_hash = digest(args.emulator)
    fixture_rom = args.fixture_dir / "archive-live-dead.rom"
    fixture_hash = digest(fixture_rom)
    rows: list[dict[str, str]] = []

    def add(
        scenario: str,
        artifact: str,
        input_state: str,
        result: str,
        target: str,
        vat: dict[str, int],
        trace: Path,
        snapshot: Path,
        trace_anchors: str,
        *,
        input_hash: str = "",
        output_hash: str = "",
        limit: str,
    ) -> None:
        rows.append({
            "scenario": scenario,
            "artifact": artifact,
            "input_state": input_state,
            "observed_result": result,
            "target": target,
            "target_type": f"0x{vat['type']:02X}",
            "target_page": f"0x{vat['page']:02X}",
            "target_address": f"0x{vat['address']:04X}",
            "trace_anchors": trace_anchors,
            "trace_sha256": digest(trace),
            "snapshot_sha256": digest(snapshot),
            "input_rom_sha256": input_hash,
            "output_rom_sha256": output_hash,
            "emulator_sha256": emulator_hash,
            "evidence_limit": limit,
        })

    # PRGMHIDE: local write, archive, and cold-reset VAT rebuild.
    hide_trace = root / "community-prgmhide-final.trace"
    hide_counts = pc_counts(hide_trace, {0x9F22, 0x9F2E, 0x1785, 0x491A, 0x6248})
    for address in (0x9F22, 0x9F2E, 0x1785, 0x491A, 0x6248):
        if hide_counts[address] == 0:
            raise SystemExit(f"PRGMHIDE trace misses 0x{address:04X}")
    toggled_path = root / "community-prgmhide-toggle.ram"
    archived_path = root / "community-prgmhide-archive.ram"
    hidden_name = b"\x1aTARGET"
    toggled = named_vat(logical_ram(toggled_path), hidden_name)
    archived = named_vat(logical_ram(archived_path), hidden_name)
    if toggled != {"type": 0x05, "page": 0, "address": 0xA1E7}:
        # The exact RAM address can move with transfer ordering; only its class
        # and residency are stable.
        if toggled["type"] != 0x05 or toggled["page"] != 0:
            raise SystemExit(f"unexpected toggled PRGMHIDE target: {toggled}")
    if archived != {"type": 0x05, "page": 0x08, "address": 0x4001}:
        raise SystemExit(f"unexpected archived PRGMHIDE target: {archived}")
    archive_rom = root / "community-prgmhide-archive.rom"
    add(
        "prgmhide_toggle_archive", "PRGMHIDE.8xp", "RAM ProgObj ZTARGET",
        "first stored name byte 0x5A -> 0x1A; archive retained changed name",
        "1ATARGET", archived, hide_trace, archived_path,
        anchors(hide_counts, (0x9F22, 0x9F2E, 0x6248, 0x1785, 0x491A)),
        input_hash=rom_hash, output_hash=digest(archive_rom),
        limit="TilEm reset and accepted Flash commands; no physical calculator",
    )
    cold_path = root / "community-prgmhide-cold-reset.ram"
    cold = named_vat(logical_ram(cold_path), hidden_name)
    if cold != archived:
        raise SystemExit(f"cold-reset hidden VAT differs: {cold} != {archived}")
    cold_trace = root / "community-prgmhide-cold-reset.trace"
    add(
        "prgmhide_cold_reset", "PRGMHIDE archive output", "fresh RAM reset",
        "archive VAT rebuild retained hidden name; ordinary PRGM menu was empty",
        "1ATARGET", cold, cold_trace, cold_path, "cold-reset VAT rebuild",
        input_hash=digest(archive_rom), output_hash=digest(archive_rom),
        limit="menu result is a captured TilEm LCD frame, not physical-key testing",
    )

    # PRGMAPPV copy/delete and archived refusal.
    convert_trace = root / "community-prgmappv-convert.trace"
    convert_counts = pc_counts(convert_trace, {0x9F31, 0x9F5E, 0x9F64, 0x9F6A})
    if not convert_counts[0x9F31] or not convert_counts[0x9F5E]:
        raise SystemExit(f"PRGMAPPV conversion misses create/delete: {convert_counts}")
    convert_path = root / "community-prgmappv-convert.ram"
    converted = named_vat(logical_ram(convert_path), b"ZTARGET")
    if converted["type"] != 0x15 or converted["page"] != 0:
        raise SystemExit(f"unexpected PRGMAPPV conversion: {converted}")
    add(
        "prgmappv_convert", "PRGMAPPV.8XP", "RAM ProgObj ZTARGET",
        "created RAM AppVar and deleted source", "ZTARGET", converted,
        convert_trace, convert_path, anchors(convert_counts, (0x9F64, 0x9F31, 0x9F5E)),
        input_hash=rom_hash,
        limit="one small ordinary program; allocation-error path not forced",
    )
    refusal_trace = root / "community-prgmappv-refusal.trace"
    refusal_counts = pc_counts(refusal_trace, {0x9F31, 0x9F5E, 0x9F64, 0x9F6A})
    if not refusal_counts[0x9F64] or not refusal_counts[0x9F6A]:
        raise SystemExit(f"PRGMAPPV refusal branch missing: {refusal_counts}")
    if refusal_counts[0x9F31] or refusal_counts[0x9F5E]:
        raise SystemExit(f"archived refusal reached create/delete: {refusal_counts}")
    refusal_path = root / "community-prgmappv-refusal.ram"
    refused = named_vat(logical_ram(refusal_path), b"ZARCH")
    if refused != {"type": 0x05, "page": 0x08, "address": 0x4001}:
        raise SystemExit(f"unexpected archived refusal result: {refused}")
    add(
        "prgmappv_archived_refusal", "PRGMAPPV.8XP", "archived ProgObj ZARCH",
        "returned to selector without create/delete", "ZARCH", refused,
        refusal_trace, refusal_path, anchors(refusal_counts, (0x9F64, 0x9F6A, 0x9F31, 0x9F5E)),
        input_hash=rom_hash,
        limit="one archived program; lock-toggle refusal uses the same source gate but was not keyed separately",
    )

    # HIDE's direct type-byte replacement.
    type_trace = root / "community-hide.trace"
    type_counts = pc_counts(type_trace, {0x9E1B, 0x9E23, 0x9E29})
    if any(type_counts[address] == 0 for address in (0x9E1B, 0x9E23, 0x9E29)):
        raise SystemExit(f"HIDE write path missing: {type_counts}")
    type_path = root / "community-hide-type.ram"
    type_result = named_vat(logical_ram(type_path), b"ZTARGET")
    if type_result["type"] != 0x15 or type_result["page"] != 0:
        raise SystemExit(f"unexpected HIDE type result: {type_result}")
    add(
        "hide_type_write", "HIDE.8XP", "RAM ProgObj named by Str0",
        "replaced complete VAT type byte with AppVarObj", "ZTARGET", type_result,
        type_trace, type_path, anchors(type_counts, (0x9E1B, 0x9E23, 0x9E29)),
        input_hash=rom_hash,
        limit="unsafe archived-target variant was not executed because it can create an inconsistent VAT",
    )

    # Archive Utility scan and live/dead extraction.
    scan_trace = root / "community-archive-scan.trace"
    scan_counts = pc_counts(scan_trace, {0x9E68, 0x9EB2, 0x9EBF})
    if scan_counts[0x9E68] != 2 or scan_counts[0x9EBF] != 1:
        raise SystemExit(f"Archive Utility scan did not classify live+dead: {scan_counts}")
    scan_path = root / "community-archive-scan.ram"
    scan_ram = logical_ram(scan_path)
    if int.from_bytes(scan_ram[0x1878:0x187A], "little") != 2:
        raise SystemExit("Archive Utility object counter is not two")
    live_vat = named_vat(scan_ram, b"LIVE")
    add(
        "archive_utility_scan", "ARCHUTIL.8XP", "0xFC LIVE + 0xF0 DEAD records",
        "displayed and counted both records", "LIVE", live_vat,
        scan_trace, scan_path, anchors(scan_counts, (0x9E68, 0x9EB2, 0x9EBF)),
        input_hash=fixture_hash,
        limit="fresh-sector controlled fixture; scan display is TilEm LCD output",
    )
    for kind, name, expected_type, address in (
        ("live", b"RCVLIVE", 0x05, 0x4001),
        ("dead", b"RCVDEAD", 0x06, 0x4013),
    ):
        trace = root / f"community-archive-extract-{kind}-final.trace"
        counts = pc_counts(trace, {0x9EAA, 0x9EBF, 0x9FD0, 0x9FE7})
        if not counts[0x9FD0] or not counts[0x9FE7]:
            raise SystemExit(f"Archive Utility {kind} extraction misses copy: {counts}")
        snapshot = root / f"community-archive-extract-{kind}.ram"
        result = named_vat(logical_ram(snapshot), name)
        if result["type"] != expected_type or result["page"] != 0:
            raise SystemExit(f"unexpected {kind} extraction VAT: {result}")
        if payload(logical_ram(snapshot), result) != b"\x02\x00\x31\x3f":
            raise SystemExit(f"unexpected {kind} extraction payload")
        output_rom = root / f"community-archive-extract-{kind}.rom"
        if digest(output_rom) != fixture_hash:
            raise SystemExit(f"Archive Utility {kind} extraction changed Flash")
        add(
            f"archive_utility_extract_{kind}", "ARCHUTIL.8XP",
            f"record 08:{address:04X} status {'0xFC' if kind == 'live' else '0xF0'}",
            f"created RAM {'ProgObj' if expected_type == 5 else 'ProtProgObj'} and copied payload; Flash unchanged",
            name.decode(), result, trace, snapshot,
            anchors(counts, (0x9EAA, 0x9EBF, 0x9FD0, 0x9FE7)),
            input_hash=fixture_hash, output_hash=digest(output_rom),
            limit="controlled record layout under TilEm; no pre-GC timing measurement on hardware",
        )

    cross_fixture = args.fixture_dir / "archive-cross-page.rom"
    cross_hash = digest(cross_fixture)
    cross_trace = root / "community-archive-extract-cross-page.trace"
    cross_counts = pc_counts(cross_trace, {0x9EAA, 0x9EBF, 0x9FD0, 0x9FE7})
    if not cross_counts[0x9FD0] or not cross_counts[0x9FE7]:
        raise SystemExit(f"Archive Utility cross-page extraction misses copy: {cross_counts}")
    cross_path = root / "community-archive-extract-cross-page.ram"
    cross_result = named_vat(logical_ram(cross_path), b"RCVCROSS")
    if cross_result["type"] != 0x05 or cross_result["page"] != 0:
        raise SystemExit(f"unexpected cross-page extraction VAT: {cross_result}")
    expected_cross_payload = (32).to_bytes(2, "little") + bytes(range(32))
    if payload(logical_ram(cross_path), cross_result, 34) != expected_cross_payload:
        raise SystemExit("unexpected cross-page extraction payload")
    cross_output_rom = root / "community-archive-extract-cross-page.rom"
    if digest(cross_output_rom) != cross_hash:
        raise SystemExit("Archive Utility cross-page extraction changed Flash")
    add(
        "archive_utility_extract_cross_page", "ARCHUTIL.8XP",
        "record 08:7FE0; 34-byte size+data field crosses into page 09",
        "created RAM ProgObj and copied complete payload; Flash unchanged",
        "RCVCROSS", cross_result, cross_trace, cross_path,
        anchors(cross_counts, (0x9EAA, 0x9EBF, 0x9FD0, 0x9FE7)),
        input_hash=cross_hash, output_hash=digest(cross_output_rom),
        limit="controlled page-boundary layout under TilEm; no physical calculator",
    )

    # Safe numeric-bcall execution found while auditing the community sources.
    numeric_trace = root / "community-numeric-bcalls.trace"
    numeric_counts = pc_counts(numeric_trace, {0x2692, 0x61AF, 0x9D9F, 0x9DA2})
    if numeric_counts[0x9D9F] != 1 or numeric_counts[0x9DA2] != 1:
        raise SystemExit(f"numeric bcall fixture sites mismatch: {numeric_counts}")
    if not numeric_counts[0x2692] or not numeric_counts[0x61AF]:
        raise SystemExit(f"numeric bcall targets missing: {numeric_counts}")
    numeric_path = root / "community-numeric-bcalls.ram"
    numeric_ram = logical_ram(numeric_path)
    marker = numeric_ram[0x1872:0x187A]
    if marker[:2] != b"\xA1\xBC" or marker[-2:] != b"\x0D\x60":
        raise SystemExit(f"numeric bcall fixture did not return: {marker.hex()}")
    rows.append({
        "scenario": "numeric_bcalls_safe",
        "artifact": "source-built numeric-bcalls.asm",
        "input_state": "ordinary Asm execution",
        "observed_result": "5011h and 5014h returned; ArcChk words captured from 0x839F",
        "target": "5011h,5014h",
        "target_type": "",
        "target_page": "",
        "target_address": "",
        "trace_anchors": anchors(
            numeric_counts, (0x9D9F, 0x9DA2, 0x2692, 0x61AF)
        ),
        "trace_sha256": digest(numeric_trace),
        "snapshot_sha256": digest(numeric_path),
        "input_rom_sha256": rom_hash,
        "output_rom_sha256": "",
        "emulator_sha256": emulator_hash,
        "evidence_limit": "50C8h _UngroupVar was not called without an authentic GroupObj and caller state",
    })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} observations to {args.output}")


if __name__ == "__main__":
    main()
