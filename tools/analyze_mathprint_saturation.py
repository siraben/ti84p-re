#!/usr/bin/env python3
"""Audit scoped MathPrint control-flow, dispatch, and trace saturation.

This is a lightweight symbolic-execution aid, not a whole-Z80 theorem prover.
It recursively follows direct control flow from a declared set of subsystem
entries, decodes fixed ROM table rows, collapses selected stateful
predicates into symbolic path classes, and overlays resolved TLMT instruction
traces. Computed dispatches, bcall and bjump bodies, and state outside the model
remain explicit in the report.

Run through the development shell so ``z80dasm`` is available::

    nix develop -c python tools/analyze_mathprint_saturation.py \
      --trace scalar=/tmp/mp-render-types-mku5nyij/scalar_2.trace \
      --output tools/mathprint-saturation.json

The checked-in report is evidence about the pinned ROM, the declared code
universe, and the named trace corpus.  It is not a claim that every MathPrint
entry state or arbitrary token stream has been explored.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable, Iterator, Sequence

from hardware_trace import make_banker
from rom_image import RomImage, RomLocation
from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from tilem_trace_resolve import iter_records, read_header, resolve_instruction
from tilem_trace_resolve import (
    IDX_AF, IDX_BC, IDX_DE, IDX_HL, IDX_IX, IDX_IY, IDX_SP,
)
from z80_disassembly import (
    Z80Instruction, direct_target, disassemble_page, parse_z80dasm,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "tools" / "rom.bin"
DEFAULT_OUTPUT = ROOT / "tools" / "mathprint-saturation.json"
TRACE_CACHE_SCHEMA = 6
EXHAUSTIVE_COVER_LIMIT = 24
TRACE_PROVENANCE_NATURAL = "natural_calculator_input"
TRACE_PROVENANCE_SYNTHETIC = "synthetic_state_injection"
TRACE_PROVENANCE_VALUES = frozenset({
    TRACE_PROVENANCE_NATURAL,
    TRACE_PROVENANCE_SYNTHETIC,
})
NATIVE_TWO_BYTE_TOKEN_LEADS = frozenset({
    0x5C, 0x5D, 0x5E, 0x60, 0x61, 0x62, 0x63, 0x7E, 0xBB, 0xAA, 0xEF,
})


@dataclass(frozen=True)
class Region:
    page: int
    start: int
    end: int

    def contains(self, location: RomLocation) -> bool:
        return (
            location.page == self.page
            and self.start <= location.address < self.end
        )

    def text(self) -> str:
        return f"{self.page:02X}:{self.start:04X}–{self.end - 1:04X}"


@dataclass(frozen=True)
class Component:
    name: str
    purpose: str
    regions: tuple[Region, ...]
    entries: tuple[RomLocation, ...]


@dataclass(frozen=True)
class Branch:
    location: RomLocation
    instruction: str
    kind: str
    target: RomLocation | None
    fallthrough: RomLocation | None

    @property
    def key(self) -> tuple[str, int]:
        return trace_key(self.location)


@dataclass(frozen=True)
class ComponentCfg:
    component: Component
    instructions: tuple[Z80Instruction, ...]
    branches: tuple[Branch, ...]
    block_leaders: tuple[RomLocation, ...]
    unresolved: tuple[dict[str, object], ...]
    external_direct_targets: tuple[RomLocation, ...]


# The ranges bound the claim. Entries include table destinations because the
# common dispatcher reaches them through the ROM's LD HL,(HL); PUSH HL; RET
# idiom, which a direct-edge walker cannot discover on its own.
COMPONENTS = (
    Component(
        "settled_construction",
        "source scanning, record allocation, child construction, and embedding",
        (Region(0x34, 0x4690, 0x5D03),),
        tuple(
            RomLocation(0x34, address)
            for address in (
                0x4690, 0x473A, 0x4862, 0x4900, 0x5678, 0x5699,
                0x56DF, 0x56E3, 0x56EC, 0x5795, 0x58F9, 0x5935,
                0x5996, 0x5A05, 0x5A99,
            )
        ),
    ),
    Component(
        "settled_render",
        "record-program traversal, structural handlers, leaf output, and primitives",
        (Region(0x34, 0x5D07, 0x6D80), Region(0x34, 0x700C, 0x7200)),
        tuple(
            RomLocation(0x34, address)
            for address in (
                0x5D07, 0x5D1A, 0x5D96, 0x5DA6, 0x5E85, 0x5FE7,
                0x6016, 0x6105, 0x6143, 0x620A, 0x622F, 0x62A1,
                0x6315, 0x6347, 0x6375, 0x637E, 0x63AD, 0x63B2,
                0x640E, 0x6504, 0x65AA, 0x660A, 0x6873, 0x6C37,
                0x6CCD, 0x700C, 0x6D0C, 0x706A, 0x70B8, 0x702C,
                0x7133, 0x70A0, 0x70E2, 0x7087, 0x7102, 0x717E,
                0x70C1, 0x71C6,
            )
        ),
    ),
    Component(
        "settled_metrics_geometry",
        "record metric and geometry dispatch passes",
        (Region(0x34, 0x737A, 0x77A0),),
        tuple(
            RomLocation(0x34, address)
            for address in (
                0x737A, 0x7393, 0x7609,
                0x73B9, 0x740B, 0x744F, 0x73D6, 0x7485, 0x743F,
                0x73DB, 0x7436, 0x745A, 0x74AA, 0x7455, 0x74F5,
                0x764A, 0x7632, 0x7647, 0x7661, 0x76C2, 0x762B,
                0x76A4, 0x76A9, 0x76F1, 0x773D,
            )
        ),
    ),
    Component(
        "record_allocator",
        "settled-record sizing and arena allocation",
        (Region(0x33, 0x4F23, 0x4FC0),),
        (RomLocation(0x33, 0x4F23), RomLocation(0x33, 0x4F42)),
    ),
    Component(
        "editor_layout",
        "editor class selection, handler rows, operand walking, and template geometry",
        (Region(0x39, 0x49A8, 0x5D50), Region(0x39, 0x672E, 0x6B90)),
        tuple(
            RomLocation(0x39, address)
            for address in (
                0x49A8, 0x4A56, 0x4A74, 0x4C27, 0x4C5A, 0x4CA4,
                0x4CE9, 0x4DCA, 0x4DE6, 0x4E8E, 0x4F1A, 0x4F9A,
                0x5167, 0x5949, 0x59E0, 0x59F9, 0x5B10, 0x5B1D,
                0x672E, 0x683D, 0x68AE, 0x69C8, 0x6ABF,
            )
        ),
    ),
    Component(
        "small_font_lcd",
        "small-font lookup, byte composition, and LCD data output",
        (Region(0x01, 0x5A59, 0x5B00), Region(0x01, 0x624C, 0x68D0)),
        tuple(
            RomLocation(0x01, address)
            for address in (
                0x5A59, 0x5A60, 0x5A89, 0x624C, 0x6297, 0x6431,
                0x6453, 0x66E5, 0x66EA, 0x6702,
            )
        ),
    ),
    Component(
        "point_line_primitives",
        "point and clipped horizontal or vertical line emission",
        (Region(0x04, 0x4025, 0x4400),),
        tuple(
            RomLocation(0x04, address)
            for address in (0x4025, 0x4029, 0x4155, 0x4157, 0x431D, 0x4382)
        ),
    ),
    Component(
        "large_glyph",
        "display-code remapping and fixed large-glyph output",
        (Region(0x07, 0x44DE, 0x4630), Region(0x07, 0x5417, 0x5450)),
        tuple(
            RomLocation(0x07, address)
            for address in (0x44DE, 0x4588, 0x45B6, 0x5417, 0x542B, 0x5443)
        ),
    ),
)


TABLES = {
    "source_token_to_type": (0x34, 0x594D, 16, 3),
    "record_metadata": (0x34, 0x59AC, 13, 5),
    "render_handlers": (0x34, 0x6119, 13, 2),
    "metric_handlers": (0x34, 0x739F, 13, 2),
    "geometry_handlers": (0x34, 0x7611, 13, 2),
    "allocator_geometry": (0x33, 0x4F82, 13, 3),
    "editor_class_handlers": (0x39, 0x5E45, 0x44, 2),
}


TRANSLATION_SURFACES = (
    {
        "name": "native token reader and parse-ahead",
        "rom": ["34:58F9", "34:5911", "34:5A05", "34:5A99–5CAC"],
        "javascript": [
            "settledReadPackedToken", "settledParseAheadFunctionToken",
            "settledParseAhead",
        ],
        "tests": ["tools/test-mathprint.js"],
        "scope": "translated predicate families; arbitrary-stream path saturation remains open",
    },
    {
        "name": "structural argument selection",
        "rom": ["34:5678–57C2", "34:59AC"],
        "javascript": [
            "settledStructuralArgumentScan", "settledRaisedOperandScan",
            "settledFractionOperandScan", "settledMatrixContainerScan",
        ],
        "tests": ["tools/test-mathprint.js", "tools/mathprint-*-oracles.json"],
        "scope": "all nonzero metadata scan kinds have captured record oracles",
    },
    {
        "name": "settled record construction",
        "rom": ["34:4900", "34:5935", "34:7393", "34:7609"],
        "javascript": [
            "constructSettledProgramFromTokens",
            "constructSettledExpressionProgram",
        ],
        "tests": ["tools/test-mathprint.js", "tools/mathprint-*-oracles.json"],
        "scope": "supported expression grammar; not the in-progress editor representation",
    },
    {
        "name": "settled record graph and leaf program",
        "rom": ["34:6105", "34:660A", "34:6CCD"],
        "javascript": ["executeSettledRecordGraph", "executeSettledRecordProgram"],
        "tests": ["tools/test-mathprint.js", "tools/mathprint-*-oracles.json"],
        "scope": (
            "types 20h–2Bh translated with oracles; the type-1Fh table ABI "
            "is fixed, but lacks a captured record oracle"
        ),
    },
    {
        "name": "font, primitive, and LCD emission",
        "rom": ["01:6297", "01:6702", "04:4155", "04:431D", "04:4382", "07:4588"],
        "javascript": [
            "settledOperationPixels", "settledBlits", "settledOperationWrites",
        ],
        "tests": ["tools/test-mathprint.js", "tools/test_mathprint_draw_trace.py"],
        "scope": "synchronous accepted LCD writes, including unchanged writes",
    },
)


# Classifications are admitted only when ROM-local dataflow or an entry
# invariant proves them.  All other unobserved outcomes remain unresolved.
OUTCOME_CLASSIFICATIONS = {
    ("page_33", 0x4F4E, "fallthrough"): {
        "status": "infeasible_under_entry_invariant",
        "scope": "valid calculator-created type-0x2B settled matrix records",
        "precondition": (
            "record offsets +0x13 and +0x12 contain the nonzero row and "
            "column dimensions accepted by matrix creation at 02:5DCF"
        ),
        "reason": (
            "the type-0x2B path loads rows from record +13h and columns from "
            "record +12h, then _HTimesL returns rows*columns; matrix creation "
            "at 02:5DCF rejects either zero dimension before a valid settled "
            "matrix record exists"
        ),
    },
    ("page_34", 0x73CD, "fallthrough"): {
        "status": "infeasible_under_calculator_abi",
        "scope": "metric dispatch through calculator entries 34:7377, 34:737A, and 34:7380",
        "precondition": "34:7386 seeds B=0 and recursive dispatch restores that saved B",
        "reason": (
            "calculator entries 34:737A, 34:7380, and 34:7377 pass through "
            "34:7386, which loads B=0; the only recursive dispatcher path at "
            "34:75F4 reloads the same saved zero before 34:7606"
        ),
    },
    ("page_34", 0x765D, "returned"): {
        "status": "infeasible_under_calculator_abi",
        "scope": "geometry dispatch through calculator entries 34:7377, 34:737A, and 34:7380",
        "precondition": "34:7386 seeds B=0 and recursive dispatch restores that saved B",
        "reason": (
            "calculator entries 34:737A, 34:7380, and 34:7377 pass through "
            "34:7386, which loads B=0; the only recursive dispatcher path at "
            "34:75F4 reloads the same saved zero before 34:7606"
        ),
    },
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def page_from_space(space: str) -> int:
    if space == "ram":
        return 0
    if space.startswith("page_"):
        return int(space.removeprefix("page_"), 16)
    raise ValueError(f"unsupported Ghidra address space: {space}")


def load_ghidra_instructions(
    path: Path, rom: RomImage
) -> dict[int, dict[int, Z80Instruction]]:
    """Load Ghidra's instruction boundaries and rendered instructions."""

    starts: dict[int, dict[int, bytes]] = defaultdict(dict)
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t", 3)
        if len(fields) != 4:
            raise ValueError(f"{path}:{line_number}: expected four tab-separated fields")
        space, raw_address, raw_bytes, text = fields
        page = page_from_space(space)
        address = int(raw_address, 16)
        data = bytes.fromhex(raw_bytes)
        if address in starts[page]:
            raise ValueError(f"{path}:{line_number}: duplicate instruction {page:02X}:{address:04X}")
        starts[page][address] = data

    result: dict[int, dict[int, Z80Instruction]] = defaultdict(dict)
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        space, raw_address, raw_bytes, text = line.split("\t", 3)
        page = page_from_space(space)
        address = int(raw_address, 16)
        data = bytes.fromhex(raw_bytes)
        if rom.bytes_at(page, address, len(data)) != data:
            raise ValueError(
                f"{path}:{line_number}: instruction bytes disagree with the pinned ROM"
            )
        result[page][address] = Z80Instruction(
            RomLocation(page, address), data, text.strip().lower()
        )
    return dict(result)


def direct_instruction_target(instruction: Z80Instruction) -> int | None:
    """Accept either z80dasm's ``1234h`` or Ghidra's ``0x1234`` syntax."""

    result = direct_target(instruction)
    if result is not None:
        return result
    if instruction.mnemonic not in {"call", "jp"}:
        return None
    matches = re.findall(r"0x([0-9a-f]+)", instruction.operands)
    return int(matches[-1], 16) if matches else None


def decode_instruction_at(rom: RomImage, location: RomLocation) -> Z80Instruction:
    """Decode one Ghidra flow target without inheriting a data-table boundary."""

    # Six bytes cover every Z80 instruction. Supplying a short file makes the
    # requested address the first decoder boundary even when a preceding ROM
    # table confuses whole-page linear disassembly.
    data = rom.bytes_at(location.page, location.address, 6)
    with tempfile.NamedTemporaryFile(prefix="mathprint-instruction-") as stream:
        stream.write(data)
        stream.flush()
        result = subprocess.run(
            ["z80dasm", "-a", "-t", "-g", f"0x{location.address:X}", stream.name],
            check=False, capture_output=True, text=True,
        )
    if result.returncode:
        raise ValueError(
            f"z80dasm failed at {location}: {result.stderr.strip()}"
        )
    decoded = tuple(parse_z80dasm(result.stdout, location.page))
    if not decoded or decoded[0].location.address != location.address:
        raise ValueError(f"z80dasm did not decode requested instruction {location}")
    return decoded[0]


def trace_space(page: int) -> str:
    return "ram" if page == 0 else f"page_{page:02X}"


def trace_key(location: RomLocation) -> tuple[str, int]:
    return trace_space(location.page), location.address


def location_json(location: RomLocation | None) -> str | None:
    return None if location is None else str(location)


def target_location(instruction: Z80Instruction, address: int) -> RomLocation:
    page = 0 if address < 0x4000 else instruction.location.page
    return RomLocation(page, address)


def relative_target(instruction: Z80Instruction) -> RomLocation:
    """Decode the signed displacement of JR or DJNZ from raw bytes."""

    if instruction.mnemonic not in {"jr", "djnz"} or len(instruction.data) != 2:
        raise ValueError("relative target requires a two-byte JR or DJNZ")
    displacement = instruction.data[1]
    if displacement & 0x80:
        displacement -= 0x100
    address = (instruction.end_address + displacement) & 0xFFFF
    return target_location(instruction, address)


def is_conditional(instruction: Z80Instruction) -> bool:
    if instruction.mnemonic in {"jr", "jp", "call"}:
        return "," in instruction.operands
    if instruction.mnemonic == "ret":
        return bool(instruction.operands)
    return instruction.mnemonic == "djnz"


def branch_for(instruction: Z80Instruction) -> Branch | None:
    mnemonic = instruction.mnemonic
    if not is_conditional(instruction):
        return None
    fallthrough = target_location(instruction, instruction.end_address)
    if mnemonic in {"jr", "djnz"}:
        target = relative_target(instruction)
    elif mnemonic in {"jp", "call"}:
        direct = direct_instruction_target(instruction)
        target = None if direct is None else target_location(instruction, direct)
    elif mnemonic == "ret":
        target = None
    else:
        return None
    return Branch(instruction.location, instruction.text, mnemonic, target, fallthrough)


def in_component(component: Component, location: RomLocation) -> bool:
    return any(region.contains(location) for region in component.regions)


def build_component_cfg(
    component: Component,
    instruction_maps: dict[int, dict[int, Z80Instruction]],
    rom: RomImage,
) -> ComponentCfg:
    pending = deque(component.entries)
    reachable: dict[RomLocation, Z80Instruction] = {}
    unresolved: dict[tuple[str, str], dict[str, object]] = {}
    external: set[RomLocation] = set()

    def enqueue(location: RomLocation) -> None:
        if in_component(component, location) and location not in reachable:
            pending.append(location)

    while pending:
        location = pending.popleft()
        if location in reachable or not in_component(component, location):
            continue
        instruction = instruction_maps.get(location.page, {}).get(location.address)
        if instruction is None:
            instruction = decode_instruction_at(rom, location)
            instruction_maps.setdefault(location.page, {})[location.address] = instruction
        reachable[location] = instruction
        mnemonic = instruction.mnemonic
        fallthrough = target_location(instruction, instruction.end_address)

        if mnemonic in {"jr", "djnz"}:
            enqueue(relative_target(instruction))
            if is_conditional(instruction):
                enqueue(fallthrough)
            continue
        if mnemonic == "rst":
            # RST is a one-byte call. A bcall (RST 28h) owns the following
            # little-endian ID word, which is inline data rather than Z80 code.
            next_address = instruction.end_address + (2 if instruction.data == b"\xEF" else 0)
            enqueue(target_location(instruction, next_address))
            continue
        if mnemonic in {"jp", "call"}:
            direct = direct_instruction_target(instruction)
            if direct is None:
                unresolved[(str(location), mnemonic)] = {
                    "location": str(location),
                    "kind": f"indirect_{mnemonic}",
                    "instruction": instruction.text,
                }
            elif mnemonic == "call" and direct == 0x2B09:
                descriptor = instruction.end_address
                target_address = rom.u16le(instruction.location.page, descriptor)
                raw_page = rom.bytes_at(instruction.location.page, descriptor + 2, 1)[0]
                target = RomLocation(raw_page & 0x3F, target_address)
                if in_component(component, target):
                    enqueue(target)
                else:
                    external.add(target)
                # cross_page_jump consumes the inline word/page descriptor and
                # resumes after it when the banked target returns.
                enqueue(target_location(instruction, descriptor + 3))
                continue
            else:
                target = target_location(instruction, direct)
                if in_component(component, target):
                    enqueue(target)
                else:
                    external.add(target)
            if mnemonic == "call" or is_conditional(instruction):
                enqueue(fallthrough)
            continue
        if mnemonic == "ret":
            if is_conditional(instruction):
                enqueue(fallthrough)
            continue
        if mnemonic in {"reti", "retn", "halt"}:
            continue
        enqueue(fallthrough)

    ordered = tuple(
        sorted(reachable.values(), key=lambda item: (item.location.page, item.location.address))
    )
    branches = tuple(branch for item in ordered if (branch := branch_for(item)))
    leaders = set(component.entries) & set(reachable)
    for branch in branches:
        if branch.target in reachable:
            leaders.add(branch.target)
        if branch.fallthrough in reachable:
            leaders.add(branch.fallthrough)
    for instruction in ordered:
        if instruction.mnemonic in {"call", "rst"}:
            next_location = target_location(instruction, instruction.end_address)
            if next_location in reachable:
                leaders.add(next_location)
    return ComponentCfg(
        component=component,
        instructions=ordered,
        branches=branches,
        block_leaders=tuple(sorted(leaders, key=lambda item: (item.page, item.address))),
        unresolved=tuple(unresolved[key] for key in sorted(unresolved)),
        external_direct_targets=tuple(sorted(external, key=lambda item: (item.page, item.address))),
    )


def decode_rows(rom: RomImage, definition: tuple[int, int, int, int]) -> list[list[int]]:
    page, address, count, width = definition
    data = rom.bytes_at(page, address, count * width)
    return [list(data[offset : offset + width]) for offset in range(0, len(data), width)]


def word_rows(rows: Sequence[Sequence[int]]) -> list[int]:
    return [row[0] | row[1] << 8 for row in rows]


def source_lookup_domain(rows: Sequence[Sequence[int]]) -> dict[str, object]:
    """Partition 34:5935 by first matching row plus its no-match class."""

    first_rows: dict[tuple[int, int], int] = {}
    shadowed = []
    decoded = []
    for index, (low, high, render_type) in enumerate(rows):
        packed = (high << 8) | low
        key = (low, high)
        if key in first_rows:
            status = "shadowed_duplicate"
            shadowed.append({
                "row_index": index,
                "shadowed_by": first_rows[key],
                "token": f"{packed:04X}h",
                "render_type": f"0x{render_type:02X}",
            })
        else:
            status = "first_match"
            first_rows[key] = index
        decoded.append({
            "row_index": index,
            "token": f"{packed:04X}h",
            "render_type": f"0x{render_type:02X}",
            "lookup_status": status,
        })
    return {
        "routine": "34:5935",
        "input_domain": "all 65,536 packed D:E values",
        "first_match_classes": len(first_rows),
        "no_match_input_count": 0x10000 - len(first_rows),
        "rows": decoded,
        "shadowed_rows": shadowed,
    }


def indexed_table_domain(
    rom: RomImage,
    *,
    name: str,
    page: int,
    address: int,
    row_count: int,
    row_width: int,
    index_bias: int = 0,
) -> dict[str, object]:
    """Decode all 8-bit index results, including adjacent-byte overreads."""

    rows = []
    for incoming in range(0x100):
        index = (incoming - index_bias) & 0xFF
        offset = index * row_width
        value = list(rom.bytes_at(page, address + offset, row_width))
        rows.append({
            "incoming_value": f"0x{incoming:02X}",
            "index": index,
            "status": "table_row" if index < row_count else "adjacent_rom_bytes",
            "rom_address": f"{page:02X}:{address + offset:04X}",
            "bytes": value,
        })
    return {
        "name": name,
        "table": f"{page:02X}:{address:04X}",
        "row_count": row_count,
        "row_width": row_width,
        "index_bias": f"0x{index_bias:02X}",
        "projected_input_domain": 0x100,
        "valid_row_inputs": row_count,
        "adjacent_byte_inputs": 0x100 - row_count,
        "rows": rows,
    }


def iter_oracle_cases(document: object) -> Iterator[dict[str, object]]:
    if not isinstance(document, dict):
        return
    for value in document.values():
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("nodes"), list):
                yield item


def oracle_trace_features(paths: Iterable[Path]) -> dict[str, set[str]]:
    """Map captured trace hashes to record, LCD, and corpus-family tags."""

    features: dict[str, set[str]] = defaultdict(set)
    for path in sorted(paths):
        document = json.loads(path.read_text())
        if not isinstance(document, dict):
            continue
        for family, raw_cases in document.items():
            if not isinstance(raw_cases, list):
                continue
            for case in raw_cases:
                if not isinstance(case, dict) or not isinstance(case.get("nodes"), list):
                    continue
                trace_sha256 = case.get("trace_sha256")
                if not isinstance(trace_sha256, str):
                    continue
                tags = features[trace_sha256]
                case_key = (
                    case.get("accepted_write_sha256")
                    or case.get("final_lcd_sha256")
                    or trace_sha256
                )
                tags.add(f"oracle_case:{path.stem}:{family}:{case_key}")
                for node in case["nodes"]:
                    render_type = node.get("render_type") if isinstance(node, dict) else None
                    if not isinstance(render_type, int):
                        continue
                    tags.add(f"record_oracle:type=0x{render_type:02X}")
                    if isinstance(case.get("accepted_write_sha256"), str):
                        tags.add(f"lcd_oracle:type=0x{render_type:02X}")
    return dict(features)


def oracle_coverage(paths: Iterable[Path]) -> dict[str, object]:
    types: Counter[int] = Counter()
    expressions: set[str] = set()
    files: list[dict[str, object]] = []
    case_count = 0
    for path in sorted(paths):
        document = json.loads(path.read_text())
        cases = list(iter_oracle_cases(document))
        if not cases:
            continue
        local: Counter[int] = Counter()
        for case in cases:
            case_count += 1
            expression = case.get("expression")
            if isinstance(expression, str):
                expressions.add(expression)
            for node in case["nodes"]:
                if isinstance(node, dict) and isinstance(node.get("render_type"), int):
                    local[node["render_type"]] += 1
                    types[node["render_type"]] += 1
        files.append(
            {
                "path": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
                "cases": len(cases),
                "record_types": {f"0x{key:02X}": value for key, value in sorted(local.items())},
            }
        )
    return {
        "files": files,
        "cases": case_count,
        "unique_expressions": len(expressions),
        "record_types": {f"0x{key:02X}": value for key, value in sorted(types.items())},
    }


def type1f_terminal(a: int, iy44_bit3: int, value_8520: int) -> str:
    """Collapse the state tested by 34:6143 into one terminal action."""

    if a == 0x27:
        return "bitmap_630C" if iy44_bit3 else "bitmap_6304"
    if a in {0x21, 0x22}:
        return "glyph_7C_set_iy32_bit2"
    if a == 0x25:
        return "glyph_DB_set_iy32_bit2"
    if a == 0x2B:
        high, low = value_8520 >> 8, value_8520 & 0xFF
        bound = 8 if iy44_bit3 else 6
        if high or low >= bound:
            return "glyph_7C_set_iy32_bit2"
        if iy44_bit3:
            return "glyph_C1"
        return "bitmap_61C7_clear_iy_minus1_bit0"
    if a == 0x26:
        return "glyph_1D_set_iy32_bit2"
    if a == 0x28:
        return "glyph_6C"
    if a == 0x29:
        return "glyph_C6"
    return "bitmap_61BE"


def scan_kind_path(scan_kind: int) -> dict[str, object]:
    """Partition the complete 8-bit dispatch input at 34:5678."""

    value = scan_kind & 0xFF
    outcomes = []

    def branch(address: int, taken: bool) -> None:
        outcomes.append(f"34:{address:04X}:{'taken' if taken else 'fallthrough'}")

    branch(0x567A, value < 1)
    if value < 1:
        return {"terminal": "generic_scan", "branch_outcomes": outcomes}
    branch(0x567C, value == 1)
    if value == 1:
        return {"terminal": "raised_operand_scan", "branch_outcomes": outcomes}
    branch(0x5680, value < 3)
    if value < 3:
        return {"terminal": "fraction_operand_scan", "branch_outcomes": outcomes}
    branch(0x5682, value == 3)
    if value == 3:
        return {"terminal": "single_argument_scan", "branch_outcomes": outcomes}
    branch(0x5686, value < 5)
    if value < 5:
        return {"terminal": "multi_argument_scan", "branch_outcomes": outcomes}
    branch(0x5688, value == 5)
    return {
        "terminal": "kind_5_scan" if value == 5 else "kind_6_or_greater_scan",
        "branch_outcomes": outcomes,
    }


def symbolic_scan_kind_paths(
    observed_outcomes: Counter[tuple[str, int, str]] | None = None,
) -> list[dict[str, object]]:
    """Collapse all 256 scan-kind bytes into dispatch path classes."""

    classes: dict[tuple[str, tuple[str, ...]], list[int]] = defaultdict(list)
    for value in range(0x100):
        result = scan_kind_path(value)
        classes[(
            str(result["terminal"]),
            tuple(str(item) for item in result["branch_outcomes"]),
        )].append(value)
    paths = [
        {
            "terminal": terminal,
            "branch_outcomes": list(outcomes),
            "projected_input_count": len(values),
            "scan_kind_values": values,
        }
        for (terminal, outcomes), values in sorted(classes.items())
    ]
    return annotate_symbolic_outcome_coverage(paths, observed_outcomes)


def editor_action03_controller_path(
    argument_index: int,
    argument_count: int,
    editor_flag_bit0: int,
) -> dict[str, object]:
    """Return the complete outer-controller path for action 03 at 39:51F1."""

    argument_index &= 0xFF
    argument_count &= 0xFF
    editor_flag_bit0 = int(bool(editor_flag_bit0))
    outcomes = ["39:51F3:fallthrough"]
    outcomes.append(
        f"39:51FB:{'taken' if argument_index else 'fallthrough'}"
    )
    if argument_index:
        return {
            "terminal": "reverse_walker",
            "iterations": None,
            "branch_outcomes": outcomes,
        }
    outcomes.append(
        f"39:5201:{'taken' if editor_flag_bit0 else 'fallthrough'}"
    )
    if editor_flag_bit0:
        return {
            "terminal": "row_token_tail",
            "iterations": 0,
            "branch_outcomes": outcomes,
        }
    short = argument_count < 8
    outcomes.append(f"39:5208:{'taken' if short else 'fallthrough'}")
    if not short:
        return {
            "terminal": "wide_list",
            "iterations": 0,
            "branch_outcomes": outcomes,
        }
    iterations = 0x100 if argument_count == 0 else argument_count
    outcomes.extend("39:50AB:taken" for _step in range(iterations - 1))
    outcomes.append("39:50AB:fallthrough")
    return {
        "terminal": (
            "zero_count_loop" if argument_count == 0
            else f"short_list_loop_{argument_count}"
        ),
        "iterations": iterations,
        "branch_outcomes": outcomes,
    }


def symbolic_editor_action03_paths() -> list[dict[str, object]]:
    """Partition all count/index/flag tuples for action 03."""

    classes: dict[
        tuple[str, int | None, tuple[str, ...]], dict[str, object]
    ] = {}
    for editor_flag_bit0 in (0, 1):
        for argument_count in range(0x100):
            for argument_index in range(0x100):
                result = editor_action03_controller_path(
                    argument_index, argument_count, editor_flag_bit0
                )
                key = (
                    str(result["terminal"]),
                    result["iterations"],
                    tuple(str(item) for item in result["branch_outcomes"]),
                )
                row = classes.setdefault(key, {
                    "projected_input_count": 0,
                    "representative_states": [],
                })
                row["projected_input_count"] += 1
                states = row["representative_states"]
                if len(states) < 4:
                    states.append({
                        "argument_index": argument_index,
                        "argument_count": argument_count,
                        "editor_flag_bit0": editor_flag_bit0,
                    })
    return [
        {
            "terminal": terminal,
            "iterations": iterations,
            "branch_outcomes": list(outcomes),
            **classes[(terminal, iterations, outcomes)],
        }
        for terminal, iterations, outcomes in sorted(
            classes,
            key=lambda item: (
                item[0], -1 if item[1] is None else item[1], item[2]
            ),
        )
    ]


def editor_action04_controller_path(
    argument_index: int,
    argument_count: int,
    editor_flag_bit0: int,
) -> dict[str, object]:
    """Return the action-04 path, including the delegated call class."""

    argument_index &= 0xFF
    argument_count &= 0xFF
    editor_flag_bit0 = int(bool(editor_flag_bit0))
    last_argument = (argument_count - 1) & 0xFF
    delta = (last_argument - argument_index) & 0xFF
    outcomes = ["39:52A7:fallthrough"]
    outcomes.append(f"39:52B1:{'taken' if delta == 0 else 'fallthrough'}")
    if delta:
        if argument_count == 0:
            delegate_class = "empty"
        elif argument_index < last_argument:
            delegate_class = "advancing"
        else:
            delegate_class = "at_or_past_last"
        return {
            "terminal": f"advance_once_{delegate_class}",
            "delta_nonzero": True,
            "delegate_class": delegate_class,
            "branch_outcomes": outcomes,
        }
    outcomes.append(
        f"39:52BC:{'taken' if editor_flag_bit0 else 'fallthrough'}"
    )
    return {
        "terminal": (
            "row_token_tail" if editor_flag_bit0 else "layout_argument_zero"
        ),
        "delta_nonzero": False,
        "delegate_class": None,
        "branch_outcomes": outcomes,
    }


def symbolic_editor_action04_paths() -> list[dict[str, object]]:
    """Partition all count/index/flag tuples for action 04."""

    classes: dict[
        tuple[str, str | None, tuple[str, ...]], dict[str, object]
    ] = {}
    for editor_flag_bit0 in (0, 1):
        for argument_count in range(0x100):
            for argument_index in range(0x100):
                result = editor_action04_controller_path(
                    argument_index, argument_count, editor_flag_bit0
                )
                key = (
                    str(result["terminal"]),
                    result["delegate_class"],
                    tuple(str(item) for item in result["branch_outcomes"]),
                )
                row = classes.setdefault(key, {
                    "projected_input_count": 0,
                    "representative_states": [],
                })
                row["projected_input_count"] += 1
                states = row["representative_states"]
                if len(states) < 4:
                    states.append({
                        "argument_index": argument_index,
                        "argument_count": argument_count,
                        "editor_flag_bit0": editor_flag_bit0,
                    })
    return [
        {
            "terminal": terminal,
            "delegate_class": delegate_class,
            "branch_outcomes": list(outcomes),
            **classes[(terminal, delegate_class, outcomes)],
        }
        for terminal, delegate_class, outcomes in sorted(
            classes, key=lambda item: (item[0], item[1] or "", item[2])
        )
    ]


def editor_reverse_overflow_cue_path(
    argument_index: int,
    argument_count: int,
) -> dict[str, object]:
    """Return the byte-domain path through the reverse cue at 39:66E9."""

    argument_index &= 0xFF
    argument_count &= 0xFF
    remaining_arguments = (argument_count - argument_index) & 0xFF
    returns = remaining_arguments < 8
    return {
        "terminal": "return" if returns else "emit_window_bottom_cue",
        "remaining_arguments": remaining_arguments,
        "branch_outcomes": [
            f"39:66F2:{'taken' if returns else 'fallthrough'}"
        ],
    }


def symbolic_editor_reverse_overflow_cue_paths() -> list[dict[str, object]]:
    """Partition all count/index byte pairs for the reverse overflow cue."""

    classes: dict[
        tuple[str, tuple[str, ...]], dict[str, object]
    ] = {}
    for argument_count in range(0x100):
        for argument_index in range(0x100):
            result = editor_reverse_overflow_cue_path(
                argument_index, argument_count
            )
            key = (
                str(result["terminal"]),
                tuple(str(item) for item in result["branch_outcomes"]),
            )
            row = classes.setdefault(key, {
                "projected_input_count": 0,
                "representative_states": [],
            })
            row["projected_input_count"] += 1
            states = row["representative_states"]
            if len(states) < 4:
                states.append({
                    "argument_index": argument_index,
                    "argument_count": argument_count,
                })
    return [
        {
            "terminal": terminal,
            "branch_outcomes": list(outcomes),
            **classes[(terminal, outcomes)],
        }
        for terminal, outcomes in sorted(classes)
    ]


def raised_extended_token_path(a: int, e: int) -> dict[str, object]:
    """Partition the packed-token classifier at 34:580C.

    ``A`` is the value selected by 34:56A4: the lead byte for a packed
    two-byte token and the token byte otherwise. ``E`` is the low byte of the
    packed token. The bounded name loops entered for 5Fh and EBh depend on
    following source bytes, so this model stops at their loop entry.
    """

    a &= 0xFF
    e &= 0xFF
    outcomes = []

    def branch(address: int, taken: bool) -> None:
        outcomes.append(f"34:{address:04X}:{'taken' if taken else 'fallthrough'}")

    branch(0x580E, a < 0x40)
    if a >= 0x40:
        branch(0x5812, a < 0x5C)
        if a < 0x5C:
            branch(0x585F, a == 0x5F)
            return {
                "terminal": "bounded_name_scan_8" if a == 0x5F else "advance_one_token",
                "name_byte_limit": 8 if a == 0x5F else 0,
                "branch_outcomes": outcomes,
            }
        branch(0x5816, a < 0x64)
        if a < 0x64:
            branch(0x585F, a == 0x5F)
            return {
                "terminal": "bounded_name_scan_8" if a == 0x5F else "advance_one_token",
                "name_byte_limit": 8 if a == 0x5F else 0,
                "branch_outcomes": outcomes,
            }

    branch(0x581B, a == 0x72)
    if a == 0x72:
        return {
            "terminal": "advance_one_token", "name_byte_limit": 0,
            "branch_outcomes": outcomes,
        }
    branch(0x581F, a == 0xAA)
    if a == 0xAA:
        return {
            "terminal": "advance_one_token", "name_byte_limit": 0,
            "branch_outcomes": outcomes,
        }
    branch(0x5823, a == 0xEB)
    if a == 0xEB:
        return {
            "terminal": "bounded_name_scan_5", "name_byte_limit": 5,
            "branch_outcomes": outcomes,
        }
    branch(0x5827, a == 0x2C)
    if a == 0x2C:
        return {
            "terminal": "advance_one_token", "name_byte_limit": 0,
            "branch_outcomes": outcomes,
        }
    branch(0x582B, a == 0xAC)
    if a == 0xAC:
        return {
            "terminal": "advance_one_token", "name_byte_limit": 0,
            "branch_outcomes": outcomes,
        }
    branch(0x582F, a != 0xBB)
    if a != 0xBB:
        return {
            "terminal": "rejected", "name_byte_limit": 0,
            "branch_outcomes": outcomes,
        }
    branch(0x5833, e == 0x31)
    return {
        "terminal": "advance_one_token" if e == 0x31 else "rejected",
        "name_byte_limit": 0,
        "branch_outcomes": outcomes,
    }


def raised_classifier_caller_states() -> Iterator[tuple[int, int, str]]:
    """Yield every packed-token state admitted by the 34:58F9 caller ABI."""

    for token in range(0x100):
        if (
            token not in NATIVE_TWO_BYTE_TOKEN_LEADS
            and token != 0xB0
            and not 0x30 <= token < 0x3C
        ):
            yield token, token, f"{token:02X}h"
    for lead in sorted(NATIVE_TWO_BYTE_TOKEN_LEADS):
        for second in range(0x100):
            if lead == 0xEF and second == 0x1E:
                continue
            yield lead, second, f"{lead:02X}{second:02X}h"


def symbolic_raised_extended_token_paths(
    observed_outcomes: Counter[tuple[str, int, str]] | None = None,
) -> list[dict[str, object]]:
    """Partition every valid packed-token input to 34:580C by complete path."""

    classes: dict[
        tuple[str, int, tuple[str, ...]], dict[str, object]
    ] = {}
    for a, e, token in raised_classifier_caller_states():
        result = raised_extended_token_path(a, e)
        key = (
            str(result["terminal"]), int(result["name_byte_limit"]),
            tuple(str(item) for item in result["branch_outcomes"]),
        )
        row = classes.setdefault(key, {
            "projected_input_count": 0,
            "representative_tokens": [],
        })
        row["projected_input_count"] += 1
        representatives = row["representative_tokens"]
        if len(representatives) < 4:
            representatives.append(token)
    paths = [
        {
            "terminal": terminal,
            "name_byte_limit": name_limit,
            "branch_outcomes": list(outcomes),
            **classes[(terminal, name_limit, outcomes)],
        }
        for terminal, name_limit, outcomes in sorted(classes)
    ]
    return annotate_symbolic_outcome_coverage(paths, observed_outcomes)


RAISED_NAME_BYTE_CLASSES = {
    "digit": {"count": 10, "representative": 0x30},
    "letter": {"count": 27, "representative": 0x41},
    "non_name_below_41h": {"count": 55, "representative": 0x00},
    "non_name_at_or_above_5ch": {"count": 164, "representative": 0x5C},
}


def raised_name_loop_path(
    prefix_classes: Sequence[str],
    stop_class: str,
    limit: int,
) -> dict[str, object]:
    """Model one complete 34:583D bounded-name loop path."""

    if limit not in {5, 8}:
        raise ValueError("34:583D has only the five- and eight-byte entry ABIs")
    if len(prefix_classes) > limit:
        raise ValueError("accepted name prefix exceeds the loop counter")
    if any(value not in {"digit", "letter"} for value in prefix_classes):
        raise ValueError("accepted prefix classes must be digits or letters")
    if len(prefix_classes) == limit:
        if stop_class != "byte_limit":
            raise ValueError("a full accepted prefix stops at the byte limit")
    elif stop_class not in {
        "source_boundary", "non_name_below_41h", "non_name_at_or_above_5ch",
    }:
        raise ValueError("a short accepted prefix needs a ROM stop class")

    outcomes: list[str] = []
    for index, value in enumerate(prefix_classes):
        outcomes.append("34:5840:fallthrough")
        outcomes.append(
            f"34:5845:{'taken' if value == 'digit' else 'fallthrough'}"
        )
        if value == "letter":
            outcomes.extend(("34:5849:fallthrough", "34:584D:fallthrough"))
        outcomes.append(
            f"34:5853:{'fallthrough' if index + 1 == limit else 'taken'}"
        )

    if len(prefix_classes) < limit:
        if stop_class == "source_boundary":
            outcomes.append("34:5840:taken")
        else:
            outcomes.extend(("34:5840:fallthrough", "34:5845:fallthrough"))
            if stop_class == "non_name_below_41h":
                outcomes.append("34:5849:taken")
            else:
                outcomes.extend(("34:5849:fallthrough", "34:584D:taken"))

    multiplicity = 1
    representative = []
    for value in prefix_classes:
        info = RAISED_NAME_BYTE_CLASSES[value]
        multiplicity *= int(info["count"])
        representative.append(int(info["representative"]))
    if stop_class in RAISED_NAME_BYTE_CLASSES:
        info = RAISED_NAME_BYTE_CLASSES[stop_class]
        multiplicity *= int(info["count"])
        representative.append(int(info["representative"]))

    return {
        "accepted_prefix_classes": list(prefix_classes),
        "accepted_prefix_length": len(prefix_classes),
        "stop_class": stop_class,
        "projected_input_count": multiplicity,
        "representative_source_bytes": representative,
        "branch_outcomes": outcomes,
    }


def symbolic_raised_name_loop_paths(limit: int) -> list[dict[str, object]]:
    """Partition every bounded byte-class projection through 34:583D."""

    rows = []
    for length in range(limit):
        for mask in range(1 << length):
            prefix = tuple(
                "letter" if mask & (1 << index) else "digit"
                for index in range(length)
            )
            for stop in (
                "source_boundary", "non_name_below_41h",
                "non_name_at_or_above_5ch",
            ):
                rows.append(raised_name_loop_path(prefix, stop, limit))
    for mask in range(1 << limit):
        prefix = tuple(
            "letter" if mask & (1 << index) else "digit"
            for index in range(limit)
        )
        rows.append(raised_name_loop_path(prefix, "byte_limit", limit))
    return rows


def type1f_path(a: int, iy44_bit3: int, value_8520: int) -> dict[str, object]:
    """Return the exact conditional path through the shared 34:6143 helper."""

    a &= 0xFF
    iy44_bit3 = int(bool(iy44_bit3))
    value_8520 &= 0xFFFF
    outcomes = []

    def branch(address: int, taken: bool) -> None:
        outcomes.append(f"34:{address:04X}:{'taken' if taken else 'fallthrough'}")

    branch(0x6145, a != 0x27)
    if a == 0x27:
        branch(0x614E, bool(iy44_bit3))
        return {
            "terminal": type1f_terminal(a, iy44_bit3, value_8520),
            "branch_outcomes": outcomes,
        }

    branch(0x6157, a != 0x22)
    if a == 0x22:
        return {
            "terminal": type1f_terminal(a, iy44_bit3, value_8520),
            "branch_outcomes": outcomes,
        }
    branch(0x6166, a == 0x21)
    if a == 0x21:
        return {
            "terminal": type1f_terminal(a, iy44_bit3, value_8520),
            "branch_outcomes": outcomes,
        }
    branch(0x616C, a == 0x25)
    if a == 0x25:
        return {
            "terminal": type1f_terminal(a, iy44_bit3, value_8520),
            "branch_outcomes": outcomes,
        }
    branch(0x6170, a != 0x2B)
    if a == 0x2B:
        high, low = value_8520 >> 8, value_8520 & 0xFF
        branch(0x6178, bool(high))
        if high:
            return {
                "terminal": type1f_terminal(a, iy44_bit3, value_8520),
                "branch_outcomes": outcomes,
            }
        branch(0x6181, not iy44_bit3)
        bound = 8 if iy44_bit3 else 6
        branch(0x6186, low >= bound)
        if low >= bound:
            return {
                "terminal": type1f_terminal(a, iy44_bit3, value_8520),
                "branch_outcomes": outcomes,
            }
        branch(0x618E, bool(iy44_bit3))
        return {
            "terminal": type1f_terminal(a, iy44_bit3, value_8520),
            "branch_outcomes": outcomes,
        }

    branch(0x619F, a == 0x26)
    if a == 0x26:
        return {
            "terminal": type1f_terminal(a, iy44_bit3, value_8520),
            "branch_outcomes": outcomes,
        }
    branch(0x61A5, a == 0x28)
    if a == 0x28:
        return {
            "terminal": type1f_terminal(a, iy44_bit3, value_8520),
            "branch_outcomes": outcomes,
        }
    branch(0x61AB, a == 0x29)
    return {
        "terminal": type1f_terminal(a, iy44_bit3, value_8520),
        "branch_outcomes": outcomes,
    }


def symbolic_type1f_paths(
    a_values: Iterable[int] = range(0x100),
    observed_outcomes: Counter[tuple[str, int, str]] | None = None,
) -> list[dict[str, object]]:
    """Partition the helper state by complete branch path and terminal action."""

    classes: dict[
        tuple[str, tuple[str, ...]], dict[str, object]
    ] = {}
    for a in a_values:
        # Only A=2Bh reads 8520h. Its path classes split the low byte at 6/8
        # and the high byte at zero. Every other A treats the word as free.
        weighted_states = (
            (
                (0, 0, 6), (0, 6, 250),
                (1, 0, 8), (1, 8, 248),
                (0, 0x0100, 0xFF00), (1, 0x0100, 0xFF00),
            ) if a == 0x2B else (
                (0, 0, 0x10000), (1, 0, 0x10000),
            )
        )
        for bit, value, state_count in weighted_states:
            result = type1f_path(a, bit, value)
            key = (
                str(result["terminal"]),
                tuple(str(item) for item in result["branch_outcomes"]),
            )
            row = classes.setdefault(key, {
                "projected_input_count": 0,
                "representative_states": [],
            })
            row["projected_input_count"] += state_count
            states = row["representative_states"]
            if len(states) < 4:
                states.append({"A": a, "iy44_bit3": bit, "word_8520": value})
    paths = [
        {
            "terminal": terminal,
            "branch_outcomes": list(outcomes),
            **classes[(terminal, outcomes)],
        }
        for terminal, outcomes in sorted(classes)
    ]
    return annotate_symbolic_outcome_coverage(paths, observed_outcomes)


def symbolic_outcome_key(identifier: str) -> tuple[str, int, str]:
    """Convert a symbolic pp:addr:outcome identifier to a trace key."""

    page, address, outcome = identifier.split(":")
    return (f"page_{page}", int(address, 16), outcome)


def annotate_symbolic_outcome_coverage(
    paths: list[dict[str, object]],
    observed_outcomes: Counter[tuple[str, int, str]] | None,
) -> list[dict[str, object]]:
    """Overlay branch-outcome witnesses without claiming a path witness.

    Outcomes on one symbolic path can occur in different dynamic invocations.
    This annotation therefore reports outcome coverage only.  Exact path
    witnesses belong in the entry-ABI observations.
    """

    if observed_outcomes is None:
        return paths
    for row in paths:
        identifiers = [str(item) for item in row["branch_outcomes"]]
        exercised = [
            item for item in identifiers
            if observed_outcomes[symbolic_outcome_key(item)]
        ]
        unresolved = [item for item in identifiers if item not in exercised]
        row["branch_outcome_coverage"] = {
            "scope": "all observed entries to this routine in the trace corpus",
            "status": (
                "all_outcomes_observed" if not unresolved
                else "some_outcomes_observed" if exercised
                else "no_outcomes_observed"
            ),
            "exercised_outcomes": exercised,
            "unresolved_outcomes": unresolved,
        }
    return paths


def annotate_dynamic_path_witnesses(
    paths: list[dict[str, object]],
    observed_branch_paths: Iterable[Iterable[str]],
) -> list[dict[str, object]]:
    """Mark complete symbolic paths that one invocation traversed."""

    observed = {tuple(path) for path in observed_branch_paths}
    for row in paths:
        row["dynamic_path_observed"] = tuple(row["branch_outcomes"]) in observed
    return paths


def type1f_entry_abis(
    rom: RomImage,
    outcomes: Counter[tuple[str, int, str]],
    witnesses: dict[tuple[str, int, str], dict[str, object]],
) -> list[dict[str, object]]:
    """Describe the two ROM-proven callers that share 34:6143."""

    table_pointer = rom.u16le(0x34, 0x6119)
    table_a = table_pointer & 0xFF
    observed = []
    discriminators = (
        (0x27, 0x614E, "fallthrough", 0),
        (0x27, 0x614E, "taken", 1),
        (0x22, 0x6157, "fallthrough", 0),
        (0x21, 0x6166, "taken", 0),
        (0x25, 0x616C, "taken", 0),
        (0x26, 0x619F, "taken", 0),
        (0x28, 0x61A5, "taken", 0),
        (0x29, 0x61AB, "taken", 0),
    )
    for a, address, outcome, bit in discriminators:
        witness = witnesses.get(("page_34", address, outcome))
        if not witness or witness["state"]["A"] != a:
            continue
        path = type1f_path(a, bit, 0)
        observed.append({
            "A": a,
            "iy44_bit3": bit if a == 0x27 else "not read",
            "word_8520": "not read",
            "terminal": path["terminal"],
            "branch_outcomes": path["branch_outcomes"],
            "trace": witness["trace"],
            "discriminator_outcome": f"34:{address:04X}:{outcome}",
            "discriminator_instruction_index": witness["instruction_index"],
        })
    table_paths = symbolic_type1f_paths((table_a,))
    for row in table_paths:
        row["entry_path_status"] = "rom_fixed"
    editor_domain = range(0x1F, 0x2D)
    editor_paths = annotate_dynamic_path_witnesses(
        symbolic_type1f_paths(editor_domain, outcomes),
        (row["branch_outcomes"] for row in observed),
    )
    return [
        {
            "origin": "settled type-0x1F render-table dispatch",
            "caller": "34:6105",
            "entry_chain": "34:6105 → table 34:6119 → _LdHLind 00:0033 → 34:6143",
            "rom_bytes": {
                "table_entry": rom.bytes_at(0x34, 0x6119, 2).hex().upper(),
                "pointer_loader": rom.bytes_at(0x00, 0x0033, 5).hex().upper(),
            },
            "incoming_A": f"0x{table_a:02X}",
            "state_dependencies": [],
            "terminal": type1f_terminal(table_a, 0, 0),
            "path_classes": table_paths,
            "dynamic_entry_observed": False,
            "dynamic_record_oracle": False,
        },
        {
            "origin": "live editor cursor feedback",
            "caller": "06:7F29–7F2E",
            "entry_chain": "06:7F2E → bjump descriptor ram:30BD → 34:6143",
            "entry_domain": {
                "incoming_A": "0x1F–0x2C structural and exceptional marker types",
                "projected_input_domain": len(editor_domain) * 2 * 0x10000,
            },
            "rom_bytes": {
                "caller": rom.bytes_at(0x06, 0x7F29, 8).hex().upper(),
                "bjump_descriptor": rom.bytes_at(0x00, 0x30BD, 6).hex().upper(),
            },
            "incoming_A": "byte at editTail + 1",
            "state_dependencies": ["A", "(IY+44h).3", "word 0x8520 when A=0x2B"],
            "path_classes": editor_paths,
            "dynamic_entry_observed": bool(observed),
            "observed_entry_states": observed,
        },
    ]


def metric_marker_path(
    at_tail_boundary: int,
    yequ_table_flag: int,
    marker_class: str,
    nested: int,
) -> dict[str, object]:
    """Collapse the abstract predicate state tested by 34:759C–75C1."""

    outcomes = []
    if not at_tail_boundary:
        return {
            "terminal": "return_nz_pointer_mismatch",
            "returned_flags": "NZ",
            "branch_outcomes": ["34:75A5:returned"],
        }
    outcomes.append("34:75A5:fallthrough")
    if yequ_table_flag:
        outcomes.append("34:75A9:taken")
        return {
            "terminal": "return_nz_yequ_table",
            "returned_flags": "NZ",
            "branch_outcomes": outcomes,
        }
    outcomes.append("34:75A9:fallthrough")
    if marker_class == "other":
        outcomes.append("34:75B0:fallthrough")
        return {
            "terminal": "return_nz_other_marker",
            "returned_flags": "NZ",
            "branch_outcomes": outcomes,
        }
    outcomes.extend((
        "34:75B0:taken",
        f"34:75BB:{'fallthrough' if nested else 'taken'}",
    ))
    return {
        "terminal": f"return_z_special_marker_{'nested' if nested else 'top_level'}",
        "returned_flags": "Z",
        "branch_outcomes": outcomes,
    }


def symbolic_metric_marker_paths(
    observed_outcomes: Counter[tuple[str, int, str]] | None = None,
) -> list[dict[str, object]]:
    """Partition every predicate combination in the marker-tail gate."""

    classes: dict[tuple[str, tuple[str, ...]], list[dict[str, object]]] = defaultdict(list)
    for at_tail in (0, 1):
        for yequ_table in (0, 1):
            for marker_class in ("fraction_nthroot_power", "other"):
                for nested in (0, 1):
                    result = metric_marker_path(
                        at_tail, yequ_table, marker_class, nested
                    )
                    key = (
                        str(result["terminal"]),
                        tuple(str(item) for item in result["branch_outcomes"]),
                    )
                    classes[key].append({
                        "at_edit_tail_plus_6": at_tail,
                        "yequ_and_tblflags_bit0": yequ_table,
                        "marker_class": marker_class,
                        "nesting_nonzero": nested,
                    })
    path_discriminators = {
        "return_nz_pointer_mismatch": "34:75A5:returned",
        "return_nz_yequ_table": "34:75A9:taken",
        "return_nz_other_marker": "34:75B0:fallthrough",
        "return_z_special_marker_nested": "34:75BB:fallthrough",
        "return_z_special_marker_top_level": "34:75BB:taken",
    }
    paths = [
        {
            "terminal": terminal,
            "branch_outcomes": list(outcomes),
            "path_witness_outcome": path_discriminators[terminal],
            "predicate_valuation_count": len(states),
            "representative_states": states[:4],
        }
        for (terminal, outcomes), states in sorted(classes.items())
    ]
    annotate_symbolic_outcome_coverage(paths, observed_outcomes)
    if observed_outcomes is not None:
        for row in paths:
            key = symbolic_outcome_key(str(row["path_witness_outcome"]))
            row["dynamic_path_observed"] = bool(observed_outcomes[key])
    return paths


def metric_marker_callers(
    outcomes: Counter[tuple[str, int, str]],
) -> list[dict[str, object]]:
    """Describe each ROM-proven continuation after the 34:759C callee."""

    rows = []
    for caller, continuation in ((0x755C, 0x755F), (0x6FC6, 0x6FC9)):
        observed = [
            outcome for outcome in ("taken", "fallthrough")
            if outcomes[("page_34", continuation, outcome)]
        ]
        rows.append({
            "caller": f"34:{caller:04X}",
            "continuation": f"34:{continuation:04X}",
            "returned_NZ": f"34:{continuation:04X}:taken",
            "returned_Z": f"34:{continuation:04X}:fallthrough",
            "observed_continuation_outcomes": observed,
        })
    rows.append({
        "caller": "05:785F",
        "continuation": "tail jump; caller inherits the returned flags and A",
    })
    return rows


def _symbolic_case_representative(row: dict[str, object]) -> dict[str, object]:
    """Select one deterministic concrete representative for a path class."""

    if "scan_kind_values" in row:
        return {"scan_kind": row["scan_kind_values"][0]}
    if "representative_tokens" in row:
        return {"packed_token": row["representative_tokens"][0]}
    if "representative_source_bytes" in row:
        return {
            "source_bytes": row["representative_source_bytes"],
            "accepted_prefix_classes": row["accepted_prefix_classes"],
            "stop_class": row["stop_class"],
        }
    if "representative_states" in row:
        return dict(row["representative_states"][0])
    raise ValueError("symbolic path class has no representative input")


def _exact_symbolic_outcome_cover(
    cases: Sequence[dict[str, object]],
) -> list[int]:
    """Return an exact minimum case cover using outcome-subset dynamic programming."""

    universe = sorted({
        str(outcome)
        for case in cases
        for outcome in case["branch_outcomes"]
    })
    bits = {outcome: 1 << index for index, outcome in enumerate(universe)}
    masks = [
        sum(bits[str(outcome)] for outcome in set(case["branch_outcomes"]))
        for case in cases
    ]
    encoded_sizes = [
        len(json.dumps(
            case["representative_state"], sort_keys=True,
            separators=(",", ":"),
        ).encode())
        for case in cases
    ]
    # mask -> (case count, serialized representative bytes, class indices)
    best: dict[int, tuple[int, int, tuple[int, ...]]] = {0: (0, 0, ())}
    for index, (case_mask, encoded_size) in enumerate(zip(masks, encoded_sizes)):
        updates = dict(best)
        for mask, rank in best.items():
            combined = mask | case_mask
            candidate = (
                rank[0] + 1,
                rank[1] + encoded_size,
                rank[2] + (index,),
            )
            if combined not in updates or candidate < updates[combined]:
                updates[combined] = candidate
        best = updates
    target = (1 << len(universe)) - 1
    if target not in best:
        raise AssertionError("symbolic case set does not cover its own outcomes")
    return list(best[target][2])


def symbolic_model_corpus() -> dict[str, object]:
    """Build minimal representatives for every declared symbolic path domain."""

    definitions = (
        (
            "structural_scan_kind_dispatch",
            "34:5678",
            0x100,
            symbolic_scan_kind_paths(),
        ),
        (
            "raised_extended_token_classifier",
            "34:580C",
            sum(1 for _state in raised_classifier_caller_states()),
            symbolic_raised_extended_token_paths(),
        ),
        (
            "raised_name_loop_5",
            "34:583D",
            None,
            symbolic_raised_name_loop_paths(5),
        ),
        (
            "raised_name_loop_8",
            "34:583D",
            None,
            symbolic_raised_name_loop_paths(8),
        ),
        (
            "shared_marker_draw_helper",
            "34:6143",
            0x100 * 2 * 0x10000,
            symbolic_type1f_paths(),
        ),
        (
            "metric_marker_tail_gate",
            "34:759C",
            16,
            symbolic_metric_marker_paths(),
        ),
        (
            "editor_action_03_controller",
            "39:51F1",
            0x20000,
            symbolic_editor_action03_paths(),
        ),
        (
            "editor_action_04_controller",
            "39:52A5",
            0x20000,
            symbolic_editor_action04_paths(),
        ),
        (
            "editor_reverse_overflow_cue",
            "39:66E9",
            0x10000,
            symbolic_editor_reverse_overflow_cue_paths(),
        ),
    )
    domains = []
    all_outcomes: set[str] = set()
    for name, routine, declared_count, rows in definitions:
        cases = []
        for class_index, row in enumerate(rows):
            terminal = str(row.get("terminal", row.get("stop_class")))
            input_count = int(row.get(
                "projected_input_count",
                row.get("predicate_valuation_count", 0),
            ))
            case = {
                "class_index": class_index,
                "terminal": terminal,
                "projected_input_count": input_count,
                "representative_state": _symbolic_case_representative(row),
                "branch_outcomes": [
                    str(item) for item in row["branch_outcomes"]
                ],
            }
            for field in ("iterations", "delegate_class", "delta_nonzero"):
                if field in row:
                    case[field] = row[field]
            cases.append(case)
        projected_count = sum(
            int(case["projected_input_count"]) for case in cases
        )
        if declared_count is not None and projected_count != declared_count:
            raise AssertionError(
                f"{name} partitions {projected_count} states, expected {declared_count}"
            )
        branch_cover = _exact_symbolic_outcome_cover(cases)
        outcomes = sorted({
            outcome for case in cases for outcome in case["branch_outcomes"]
        })
        all_outcomes.update(outcomes)
        domains.append({
            "name": name,
            "routine": routine,
            "projected_input_domain": projected_count,
            "path_equivalence_class_count": len(cases),
            "path_equivalence_classes": cases,
            "branch_outcome_count": len(outcomes),
            "minimum_branch_outcome_corpus": {
                "class_indices": branch_cover,
                "selected_classes": [cases[index] for index in branch_cover],
                "selected_case_count": len(branch_cover),
                "covered_outcomes": outcomes,
                "algorithm": (
                    "exact outcome-subset dynamic programming; minimum cases, "
                    "then serialized input bytes, then class order"
                ),
                "proven_minimum": True,
            },
        })
    return {
        "scope": (
            "all projected inputs and complete path equivalence classes in the "
            "nine declared finite symbolic models"
        ),
        "not_claimed": [
            "all Z80 register and RAM states",
            "calculator reachability of every representative",
            "all paths outside the declared finite models",
        ],
        "path_equivalence_class_count": sum(
            int(domain["path_equivalence_class_count"]) for domain in domains
        ),
        "representative_path_corpus_count": sum(
            len(domain["path_equivalence_classes"]) for domain in domains
        ),
        "distinct_modeled_branch_outcomes": len(all_outcomes),
        "per_domain_minimum_branch_outcome_corpus_count": sum(
            int(domain["minimum_branch_outcome_corpus"]["selected_case_count"])
            for domain in domains
        ),
        "domains": domains,
    }


def table_report(rom: RomImage, oracle: dict[str, object]) -> dict[str, object]:
    rows = {name: decode_rows(rom, definition) for name, definition in TABLES.items()}
    render = word_rows(rows["render_handlers"])
    metric = word_rows(rows["metric_handlers"])
    geometry = word_rows(rows["geometry_handlers"])
    observed = oracle["record_types"]
    structural = []
    for index, render_type in enumerate(range(0x1F, 0x2C)):
        count = int(observed.get(f"0x{render_type:02X}", 0))
        structural.append(
            {
                "render_type": f"0x{render_type:02X}",
                "metadata": rows["record_metadata"][index],
                "allocator_geometry": rows["allocator_geometry"][index],
                "render_handler": f"34:{render[index]:04X}",
                "metric_handler": f"34:{metric[index]:04X}",
                "geometry_handler": f"34:{geometry[index]:04X}",
                "oracle_records": count,
                "javascript_status": (
                    "fixed_table_abi_without_record_oracle" if render_type == 0x1F
                    else "translated_with_record_oracle" if count
                    else "translated_without_record_oracle"
                ),
            }
        )

    source_lookup = source_lookup_domain(rows["source_token_to_type"])
    source = []
    for row, decoded in zip(rows["source_token_to_type"], source_lookup["rows"]):
        first, second, render_type = row
        source.append({
            **decoded,
            "bytes_de": [second, first],
            "exceptional": render_type == 0x2C,
        })
    editor_words = word_rows(rows["editor_class_handlers"])
    return {
        "source_token_map": source,
        "source_token_lookup_domain": source_lookup,
        "structural_dispatch": structural,
        "scan_kinds": sorted({row[0] for row in rows["record_metadata"]}),
        "nonzero_scan_kinds": sorted({row[0] for row in rows["record_metadata"] if row[0]}),
        "editor_class_table": {
            "entries": len(editor_words),
            "nonzero_pointers": sum(bool(value) for value in editor_words),
            "pointers": [f"39:{value:04X}" if value else None for value in editor_words],
        },
        "indexed_domains": {
            "render_dispatch": indexed_table_domain(
                rom, name="34:6105 structural render dispatch", page=0x34,
                address=0x6119, row_count=13, row_width=2, index_bias=0x1F,
            ),
            "allocator_geometry": indexed_table_domain(
                rom, name="33:4F6D allocator geometry lookup", page=0x33,
                address=0x4F82, row_count=13, row_width=3, index_bias=0x1F,
            ),
            "editor_class": indexed_table_domain(
                rom, name="39:4C27 editor class lookup", page=0x39,
                address=0x5E45, row_count=68, row_width=2,
            ),
        },
    }


def classify_outcome(
    branch: Branch,
    next_point: tuple[str, int],
    branch_state: dict[str, int] | None = None,
    next_state: dict[str, int] | None = None,
) -> str | None:
    fallthrough = trace_key(branch.fallthrough) if branch.fallthrough else None
    target = trace_key(branch.target) if branch.target else None
    if next_point == fallthrough:
        return "fallthrough"
    if target is not None and next_point == target:
        return "taken"
    if branch.kind == "ret":
        if branch_state is None:
            return "returned"
        # TLMT v2 records registers after the named instruction executes. A
        # taken RET therefore already contains the popped SP, so compare the
        # preserved condition flags instead of waiting for another SP change.
        if predicate_state(branch, branch_state)["predicate"] is True:
            return "returned"
    # A maskable interrupt can replace the first target/fallthrough trace
    # point with the page-0 interrupt entry at 0038h. Conditional transfers do
    # not change their tested flags, and TLMT stores post-instruction state, so
    # the consumed predicate still determines the hidden outcome exactly.
    if next_point == ("ram", 0x0038) and branch_state is not None:
        predicate = predicate_state(branch, branch_state)["predicate"]
        if predicate is not None:
            if branch.kind == "ret":
                return "returned" if predicate else "fallthrough"
            return "taken" if predicate else "fallthrough"
    return None


def branch_condition(branch: Branch) -> str:
    """Return the path-relevant Z80 condition tested by a CFG branch."""

    if branch.kind == "djnz":
        return "B_after_decrement != 0"
    operands = branch.instruction.lower().split(None, 1)
    operand = operands[1] if len(operands) == 2 else ""
    condition = operand.split(",", 1)[0].strip()
    return {
        "nz": "Z=0", "z": "Z=1", "nc": "C=0", "c": "C=1",
        "po": "PV=0", "pe": "PV=1", "p": "S=0", "m": "S=1",
    }.get(condition, condition or "conditional return")


def trace_register_state(payload: tuple) -> dict[str, int]:
    """Retain a compact witness for one dynamically selected branch state."""

    af = payload[IDX_AF]
    return {
        "A": af >> 8,
        "F": af & 0xFF,
        "BC": payload[IDX_BC],
        "DE": payload[IDX_DE],
        "HL": payload[IDX_HL],
        "IX": payload[IDX_IX],
        "IY": payload[IDX_IY],
        "SP": payload[IDX_SP],
    }


def predicate_state(branch: Branch, state: dict[str, int]) -> dict[str, object]:
    """Project a register witness onto the value consumed by the branch."""

    if branch.kind == "djnz":
        # TLMT v2 register fields are the post-instruction state.
        after = state["BC"] >> 8
        before = (after + 1) & 0xFF
        return {"B_before": before, "B_after": after, "predicate": after != 0}
    condition = branch_condition(branch)
    flag_mask = {
        "Z=0": (0x40, False), "Z=1": (0x40, True),
        "C=0": (0x01, False), "C=1": (0x01, True),
        "PV=0": (0x04, False), "PV=1": (0x04, True),
        "S=0": (0x80, False), "S=1": (0x80, True),
    }.get(condition)
    if flag_mask is None:
        return {"predicate": None}
    mask, asserted = flag_mask
    flag = bool(state["F"] & mask)
    return {condition[0]: int(flag), "predicate": flag == asserted}


def outcome_id(key: tuple[str, int, str]) -> str:
    space, address, outcome = key
    prefix = "00" if space == "ram" else space.removeprefix("page_").upper()
    return f"{prefix}:{address:04X}:{outcome}"


def dynamic_path_feature(routine: str, result: dict[str, object]) -> str:
    outcomes = ",".join(str(item) for item in result["branch_outcomes"])
    return f"modeled_path:{routine}:{result['terminal']}:{outcomes}"


def entry_feature(routine: str, fields: dict[str, int]) -> str:
    values = ",".join(f"{name}=0x{value:X}" for name, value in fields.items())
    return f"entry_state:{routine}:{values}"


PATH_ROUTINE_BRANCHES = {
    "34:5678": frozenset({0x567A, 0x567C, 0x5680, 0x5682, 0x5686, 0x5688}),
    "34:583D": frozenset({0x5840, 0x5845, 0x5849, 0x584D, 0x5853}),
    "34:6143": frozenset({
        0x6145, 0x614E, 0x6157, 0x6166, 0x616C, 0x6170, 0x6178,
        0x6181, 0x6186, 0x618E, 0x619F, 0x61A5, 0x61AB,
    }),
    "34:759C": frozenset({0x75A5, 0x75A9, 0x75B0, 0x75BB}),
}


def routine_path_terminal(routine: str, address: int, outcome: str) -> bool:
    """Return whether one observed branch completes the modeled invocation."""

    if routine == "34:5678":
        return (
            (address in {0x567A, 0x567C, 0x5680, 0x5682, 0x5686}
             and outcome == "taken")
            or address == 0x5688
        )
    if routine == "34:583D":
        return (
            (address == 0x5840 and outcome == "taken")
            or (address in {0x5849, 0x584D} and outcome == "taken")
            or (address == 0x5853 and outcome == "fallthrough")
        )
    if routine == "34:6143":
        return (
            address == 0x614E
            or (address == 0x6157 and outcome == "fallthrough")
            or (address in {
                0x6166, 0x616C, 0x6178, 0x6186, 0x619F, 0x61A5,
            } and outcome == "taken")
            or address in {0x618E, 0x61AB}
        )
    if routine == "34:759C":
        return (
            (address == 0x75A5 and outcome == "returned")
            or (address == 0x75A9 and outcome == "taken")
            or (address == 0x75B0 and outcome == "fallthrough")
            or address == 0x75BB
        )
    raise ValueError(f"unknown modeled routine {routine}")


def trace_dynamic_features(
    outcomes: set[tuple[str, int, str]],
    entry_states: dict[tuple[str, int], set[tuple[int, int]]],
    path_signatures: dict[str, set[tuple[str, ...]]] | None = None,
) -> set[str]:
    """Tag outcomes plus complete paths derived from observed entry states."""

    features = {f"branch_outcome:{outcome_id(key)}" for key in outcomes}
    for a, _de in entry_states.get(("page_34", 0x5678), set()):
        fields = {"A": a}
        features.add(entry_feature("34:5678", fields))
        features.add(dynamic_path_feature("34:5678", scan_kind_path(a)))
    for a, de in entry_states.get(("page_34", 0x580C), set()):
        fields = {"A": a, "E": de & 0xFF}
        features.add(entry_feature("34:580C", fields))
        features.add(dynamic_path_feature(
            "34:580C", raised_extended_token_path(a, de & 0xFF)
        ))
    for a, _de in entry_states.get(("page_34", 0x6143), set()):
        fields = {"A": a}
        features.add(entry_feature("34:6143", fields))
        # The current trace format does not contain IY-relative RAM or 8520h.
        # Only paths whose tested predicates are fixed by A are sound here.
        if a == 0x27 or a == 0x2B:
            continue
        features.add(dynamic_path_feature("34:6143", type1f_path(a, 0, 0)))
    for _a, de in entry_states.get(("page_34", 0x5935), set()):
        features.add(f"dispatch_input:34:5935:DE=0x{de:04X}")
    for a, _de in entry_states.get(("page_34", 0x6105), set()):
        features.add(f"dispatch_index:34:6105:type=0x{a:02X}")
    for a, _de in entry_states.get(("page_33", 0x4F6D), set()):
        features.add(f"dispatch_index:33:4F6D:index=0x{a:02X}")
    for a, _de in entry_states.get(("page_39", 0x4C31), set()):
        features.add(f"dispatch_index:39:4C31:class=0x{a:02X}")
    # 34:759C reads pointer, application, marker, and nesting state from RAM.
    # A register-only entry sample cannot select one of its complete paths.
    for routine, paths in (path_signatures or {}).items():
        for path in paths:
            features.add(f"observed_path:{routine}:{','.join(path)}")
    return features


def scan_trace(
    label: str,
    path: Path,
    branch_index: dict[tuple[str, int], Branch],
    instruction_universe: set[tuple[str, int]],
    *,
    trace_sha256: str | None = None,
) -> tuple[
    dict[str, object],
    Counter[tuple[str, int, str]],
    Counter[tuple[str, int]],
    dict[tuple[str, int, str], dict[str, object]],
    dict[tuple[str, int], set[tuple[int, int]]],
    dict[str, set[tuple[str, ...]]],
]:
    banker = make_banker("ti84p-reset")
    branch_outcomes: Counter[tuple[str, int, str]] = Counter()
    instruction_hits: Counter[tuple[str, int]] = Counter()
    pending: tuple[Branch, dict[str, int], int] | None = None
    witnesses: dict[tuple[str, int, str], dict[str, object]] = {}
    feature_entries = {
        ("page_33", 0x4F6D), ("page_34", 0x5678),
        ("page_34", 0x580C), ("page_34", 0x5935),
        ("page_34", 0x6105), ("page_34", 0x6143),
        ("page_34", 0x759C), ("page_39", 0x4C31),
    }
    entry_states: dict[tuple[str, int], set[tuple[int, int]]] = defaultdict(set)
    active_paths: dict[str, list[str]] = {}
    path_signatures: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    processed = 0
    unknown_transitions = 0
    with path.open("rb") as stream:
        header = read_header(stream)
        if header["version"] != 2:
            raise ValueError(f"{path}: expected TLMT v2")
        for record_type, payload in iter_records(stream):
            if record_type != 0x01:
                continue
            (space, address, _flat, _page), _switch = resolve_instruction(banker, payload)
            point = (space, address)
            state = trace_register_state(payload)
            if point in feature_entries:
                entry_states[point].add((state["A"], state["DE"]))
            if pending is not None:
                pending_branch, pending_state, pending_index = pending
                outcome = classify_outcome(
                    pending_branch, point, pending_state, state
                )
                if outcome is None:
                    unknown_transitions += 1
                else:
                    key = (*pending_branch.key, outcome)
                    branch_outcomes[key] += 1
                    witnesses.setdefault(
                        key,
                        {
                            "trace": label,
                            "instruction_index": pending_index,
                            "state": pending_state,
                            "predicate_state": predicate_state(
                                pending_branch, pending_state
                            ),
                        },
                    )
                    branch_address = pending_branch.location.address
                    for routine, addresses in PATH_ROUTINE_BRANCHES.items():
                        if branch_address not in addresses or routine not in active_paths:
                            continue
                        identifier = outcome_id(key)
                        active_paths[routine].append(identifier)
                        if routine_path_terminal(routine, branch_address, outcome):
                            path_signatures[routine].add(tuple(active_paths.pop(routine)))
            if point in instruction_universe:
                instruction_hits[point] += 1
            for routine, entry in (
                ("34:5678", ("page_34", 0x5678)),
                ("34:6143", ("page_34", 0x6143)),
                ("34:759C", ("page_34", 0x759C)),
            ):
                if point == entry:
                    active_paths[routine] = []
            if point == ("page_34", 0x5840) and "34:583D" not in active_paths:
                active_paths["34:583D"] = []
            branch = branch_index.get(point)
            pending = (
                None if branch is None
                else (branch, state, processed)
            )
            processed += 1
    return (
        {
            "label": label,
            "sha256": trace_sha256 or digest(path),
            "bytes": path.stat().st_size,
            "instructions": processed,
            "unclassified_branch_transitions": unknown_transitions,
        },
        branch_outcomes,
        instruction_hits,
        witnesses,
        dict(entry_states),
        dict(path_signatures),
    )


def cfg_fingerprint(cfgs: Sequence[ComponentCfg]) -> str:
    """Hash the exact instruction and branch universe used by trace summaries."""

    rows = []
    for cfg in cfgs:
        rows.append({
            "component": cfg.component.name,
            "instructions": [
                [str(item.location), item.data.hex(), item.text]
                for item in cfg.instructions
            ],
            "branches": [
                [
                    str(branch.location), branch.instruction, branch.kind,
                    location_json(branch.target), location_json(branch.fallthrough),
                ]
                for branch in cfg.branches
            ],
        })
    encoded = json.dumps(rows, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def serialize_trace_summary(
    row: dict[str, object],
    outcomes: Counter[tuple[str, int, str]],
    hits: Counter[tuple[str, int]],
    witnesses: dict[tuple[str, int, str], dict[str, object]],
    entry_states: dict[tuple[str, int], set[tuple[int, int]]],
    path_signatures: dict[str, set[tuple[str, ...]]],
) -> dict[str, object]:
    """Convert one trace scan to stable JSON cache data."""

    cached_row = {key: value for key, value in row.items() if key != "label"}
    return {
        "row": cached_row,
        "outcomes": [
            [space, address, outcome, count]
            for (space, address, outcome), count in sorted(outcomes.items())
        ],
        "instruction_hits": [
            [space, address, count]
            for (space, address), count in sorted(hits.items())
        ],
        "witnesses": [
            [space, address, outcome, value]
            for (space, address, outcome), value in sorted(witnesses.items())
        ],
        "entry_states": [
            [space, address, a, de]
            for (space, address), states in sorted(entry_states.items())
            for a, de in sorted(states)
        ],
        "path_signatures": [
            [routine, list(path)]
            for routine, paths in sorted(path_signatures.items())
            for path in sorted(paths)
        ],
    }


def deserialize_trace_summary(
    label: str, cached: dict[str, object]
) -> tuple[
    dict[str, object],
    Counter[tuple[str, int, str]],
    Counter[tuple[str, int]],
    dict[tuple[str, int, str], dict[str, object]],
    dict[tuple[str, int], set[tuple[int, int]]],
    dict[str, set[tuple[str, ...]]],
]:
    """Restore one cached scan and bind its witnesses to the current label."""

    row = {"label": label, **cached["row"]}
    outcomes = Counter({
        (space, address, outcome): count
        for space, address, outcome, count in cached["outcomes"]
    })
    hits = Counter({
        (space, address): count
        for space, address, count in cached["instruction_hits"]
    })
    witnesses = {}
    for space, address, outcome, raw_value in cached["witnesses"]:
        value = dict(raw_value)
        value["trace"] = label
        witnesses[(space, address, outcome)] = value
    entry_states: dict[tuple[str, int], set[tuple[int, int]]] = defaultdict(set)
    for space, address, a, de in cached["entry_states"]:
        entry_states[(space, address)].add((a, de))
    path_signatures: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for routine, path in cached["path_signatures"]:
        path_signatures[routine].add(tuple(path))
    return (
        row, outcomes, hits, witnesses, dict(entry_states),
        dict(path_signatures),
    )


def load_trace_cache(path: Path | None, fingerprint: str) -> dict[str, object]:
    """Load only the current trace-summary schema and CFG fingerprint."""

    if path is None or not path.is_file():
        return {
            "schema": TRACE_CACHE_SCHEMA,
            "cfg_fingerprint": fingerprint,
            "entries": {},
        }
    cache = json.loads(path.read_text())
    if (
        cache.get("schema") != TRACE_CACHE_SCHEMA
        or cache.get("cfg_fingerprint") != fingerprint
        or not isinstance(cache.get("entries"), dict)
    ):
        return {
            "schema": TRACE_CACHE_SCHEMA,
            "cfg_fingerprint": fingerprint,
            "entries": {},
        }
    return cache


def write_trace_cache(path: Path, cache: dict[str, object]) -> None:
    """Persist completed trace scans atomically so interruption loses no work."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(cache, separators=(",", ":")) + "\n")
    temporary.replace(path)


def branch_json(
    branch: Branch,
    outcomes: Counter[tuple[str, int, str]],
    witnesses: dict[tuple[str, int, str], dict[str, object]],
    classifications: dict[tuple[str, int, str], dict[str, str]] | None = None,
) -> dict[str, object]:
    observed = {
        outcome: outcomes[(*branch.key, outcome)]
        for outcome in ("taken", "fallthrough", "returned")
        if outcomes[(*branch.key, outcome)]
    }
    possible = ["returned", "fallthrough"] if branch.kind == "ret" else [
        "taken", "fallthrough"
    ]
    outcome_rows = []
    classifications = classifications or {}
    for outcome in possible:
        key = (*branch.key, outcome)
        classification = classifications.get(key)
        row = {
            "outcome": outcome,
            "status": "exercised" if outcomes[key] else (
                classification["status"] if classification else "unresolved_state_or_abi"
            ),
            "hits": outcomes[key],
        }
        if classification:
            row.update({
                field: classification[field]
                for field in ("scope", "precondition", "reason")
                if field in classification
            })
        if key in witnesses:
            row["witness"] = witnesses[key]
        outcome_rows.append(row)
    return {
        "location": str(branch.location),
        "instruction": branch.instruction,
        "kind": branch.kind,
        "condition": branch_condition(branch),
        "target": location_json(branch.target),
        "fallthrough": location_json(branch.fallthrough),
        "observed": observed,
        "outcomes": outcome_rows,
        "witnesses": {
            outcome: witnesses[(*branch.key, outcome)]
            for outcome in observed
            if (*branch.key, outcome) in witnesses
        },
    }


def component_report(
    cfg: ComponentCfg,
    outcomes: Counter[tuple[str, int, str]],
    instruction_hits: Counter[tuple[str, int]],
    witnesses: dict[tuple[str, int, str], dict[str, object]],
    classifications: dict[tuple[str, int, str], dict[str, str]] | None = None,
) -> dict[str, object]:
    branch_rows = [
        branch_json(branch, outcomes, witnesses, classifications)
        for branch in cfg.branches
    ]
    observed_counts = [len(row["observed"]) for row in branch_rows]
    outcome_statuses = Counter(
        outcome["status"] for branch in branch_rows for outcome in branch["outcomes"]
    )
    reachable_keys = {trace_key(item.location) for item in cfg.instructions}
    return {
        "purpose": cfg.component.purpose,
        "regions": [region.text() for region in cfg.component.regions],
        "entries": [str(location) for location in cfg.component.entries],
        "static": {
            "reachable_instructions": len(cfg.instructions),
            "basic_block_leaders": len(cfg.block_leaders),
            "conditional_branches": len(cfg.branches),
            "possible_branch_outcomes": 2 * len(cfg.branches),
            "unresolved_direct_control_transfers": list(cfg.unresolved),
            "external_direct_targets": [str(location) for location in cfg.external_direct_targets],
        },
        "dynamic": {
            "instructions_observed": sum(bool(instruction_hits[key]) for key in reachable_keys),
            "instruction_coverage_percent": (
                round(100 * sum(bool(instruction_hits[key]) for key in reachable_keys) / len(reachable_keys), 2)
                if reachable_keys else 100.0
            ),
            "branch_outcomes_observed": sum(observed_counts),
            "branches_with_both_outcomes": sum(count >= 2 for count in observed_counts),
            "branches_with_one_outcome": sum(count == 1 for count in observed_counts),
            "branches_unobserved": sum(count == 0 for count in observed_counts),
            "outcome_statuses": dict(sorted(outcome_statuses.items())),
        },
        "branches": branch_rows,
    }


def minimize_trace_corpus(
    trace_outcomes: dict[str, set[tuple[str, int, str]]],
    trace_bytes: dict[str, int] | None = None,
    trace_provenance: dict[str, str] | None = None,
) -> dict[str, object]:
    """Return a proven minimum-cardinality cover of the observed outcomes.

    Exhaustive cardinality-ordered enumeration is intentional here.  The
    checked-in corpus is small, so the first covering cardinality is a proof of
    minimality rather than a greedy approximation.  Equal-cardinality covers
    minimize retained trace bytes, then label order, to keep the result stable.
    """

    labels = sorted(trace_outcomes)
    universe = set().union(*trace_outcomes.values()) if trace_outcomes else set()
    sizes = trace_bytes or {}
    provenance = trace_provenance or {}
    if len(labels) <= EXHAUSTIVE_COVER_LIMIT:
        candidates: list[tuple[tuple[int, tuple[str, ...]], tuple[str, ...]]] = []
        selected: tuple[str, ...] = ()
        for count in range(len(labels) + 1):
            for subset in combinations(labels, count):
                covered = (
                    set().union(*(trace_outcomes[label] for label in subset))
                    if subset else set()
                )
                if covered == universe:
                    rank = (sum(sizes.get(label, 0) for label in subset), subset)
                    candidates.append((rank, subset))
            if candidates:
                selected = min(candidates)[1]
                break
        algorithm = "exact cardinality-ordered subset enumeration"
    else:
        selected = exact_cover_z3(labels, trace_outcomes, universe, sizes)
        algorithm = "exact lexicographic Optimize set cover via Z3"

    selected = tuple(sorted(selected))

    selected_set = set(selected)
    rows = []
    for label in selected:
        other_coverage = set().union(*(
            trace_outcomes[item] for item in selected if item != label
        )) if len(selected) > 1 else set()
        exclusive = trace_outcomes[label] - other_coverage
        rows.append(
            {
                "label": label,
                "provenance": provenance.get(label, TRACE_PROVENANCE_NATURAL),
                "total_outcomes": len(trace_outcomes[label]),
                "exclusive_outcomes": len(exclusive),
                "exclusive_outcome_ids": [
                    outcome_id(outcome) for outcome in sorted(exclusive)
                ],
            }
        )
    return {
        "algorithm": algorithm,
        "objective": "preserve every individual branch outcome observed by the supplied trace corpus",
        "preserved_feature_kinds": ["individual_branch_outcome"],
        "not_preserved": [
            "complete per-invocation branch paths",
            "register or RAM states",
            "dispatch row identities",
            "record-oracle cases",
            "LCD-write traces",
        ],
        "tie_break": "minimum retained trace bytes, then lexicographic labels",
        "source_trace_count": len(trace_outcomes),
        "source_trace_provenance_counts": dict(sorted(Counter(
            provenance.get(label, TRACE_PROVENANCE_NATURAL) for label in labels
        ).items())),
        "selected_trace_count": len(selected),
        "selected_trace_bytes": sum(sizes.get(label, 0) for label in selected),
        "selected": rows,
        "omitted": sorted(set(trace_outcomes) - selected_set),
        "covered_outcomes": len(universe),
        "proven_minimum": True,
    }


def minimize_trace_features(
    trace_features: dict[str, set[str]],
    trace_bytes: dict[str, int] | None = None,
    trace_provenance: dict[str, str] | None = None,
) -> dict[str, object]:
    """Minimize an arbitrary tagged feature universe with the exact solver."""

    labels = sorted(trace_features)
    universe = set().union(*trace_features.values()) if trace_features else set()
    sizes = trace_bytes or {}
    provenance = trace_provenance or {}
    feature_index = {feature: index for index, feature in enumerate(sorted(universe))}
    encoded = {
        label: {("feature", feature_index[feature], "covered") for feature in features}
        for label, features in trace_features.items()
    }
    selected = (
        exact_cover_z3(labels, encoded, set().union(*encoded.values()), sizes)
        if encoded else ()
    )
    selected_set = set(selected)
    rows = []
    for label in selected:
        other_coverage = set().union(*(
            trace_features[item] for item in selected if item != label
        )) if len(selected) > 1 else set()
        exclusive = sorted(trace_features[label] - other_coverage)
        rows.append({
            "label": label,
            "provenance": provenance.get(label, TRACE_PROVENANCE_NATURAL),
            "total_features": len(trace_features[label]),
            "exclusive_features": len(exclusive),
            "exclusive_feature_ids": exclusive,
        })
    return {
        "algorithm": "exact lexicographic Optimize set cover via Z3",
        "objective": "preserve every tagged dynamic feature observed by the supplied trace corpus",
        "tie_break": "minimum retained trace bytes, then lexicographic labels",
        "source_trace_count": len(labels),
        "selected_trace_count": len(selected),
        "selected_trace_bytes": sum(sizes.get(label, 0) for label in selected),
        "selected": rows,
        "omitted": sorted(set(labels) - selected_set),
        "covered_features": len(universe),
        "feature_kind_counts": dict(sorted(Counter(
            feature.partition(":")[0] for feature in universe
        ).items())),
        "proven_minimum": True,
    }


def exact_cover_z3(
    labels: Sequence[str],
    trace_outcomes: dict[str, set[tuple[str, int, str]]],
    universe: set[tuple[str, int, str]],
    sizes: dict[str, int],
) -> tuple[str, ...]:
    """Solve large corpus covers exactly without a Python Z3 dependency."""

    if not shutil.which("z3"):
        raise RuntimeError(
            f"exact minimization of {len(labels)} traces requires the z3 executable"
        )
    names = {label: f"t{index}" for index, label in enumerate(labels)}

    def sum_if(terms: Iterable[tuple[int, str]]) -> str:
        rendered = " ".join(f"(ite {name} {weight} 0)" for weight, name in terms)
        return f"(+ {rendered})" if rendered else "0"

    lines = ["(set-option :opt.priority lex)"]
    lines.extend(f"(declare-const {names[label]} Bool)" for label in labels)
    for outcome in sorted(universe):
        members = [names[label] for label in labels if outcome in trace_outcomes[label]]
        lines.append(f"(assert (or {' '.join(members)}))")
    lines.append(f"(minimize {sum_if((1, names[label]) for label in labels)})")
    lines.append(
        f"(minimize {sum_if((sizes.get(label, 0), names[label]) for label in labels)})"
    )
    # One final bit-vector-like integer objective pins a unique label-order
    # choice among equal-cardinality, equal-byte covers. Earlier labels carry
    # larger weights, so maximizing matches combinations()'s lexicographic
    # subset order.
    lines.append(
        f"(maximize {sum_if((1 << (len(labels) - index - 1), names[label]) for index, label in enumerate(labels))})"
    )
    lines.extend(["(check-sat)", "(get-model)"])
    completed = subprocess.run(
        ["z3", "-in"], input="\n".join(lines) + "\n", text=True,
        capture_output=True, check=False,
    )
    if completed.returncode or not completed.stdout.startswith("sat\n"):
        raise RuntimeError(f"z3 set-cover failure: {completed.stderr or completed.stdout}")
    values = dict(re.findall(r"\(define-fun (t\d+) \(\) Bool\s+(true|false)\)", completed.stdout))
    if len(values) != len(labels):
        raise RuntimeError("z3 set-cover model omitted trace variables")
    return tuple(label for label in labels if values[names[label]] == "true")


def open_paths(
    table: dict[str, object],
    components: dict[str, object],
    outcome_statuses: Counter[str],
) -> list[dict[str, str]]:
    structural = table["structural_dispatch"]
    missing_types = [
        row["render_type"] for row in structural if row["oracle_records"] == 0
    ]
    editor_dynamic = components["editor_layout"]["dynamic"]
    infeasible = (
        outcome_statuses["infeasible_under_entry_invariant"]
        + outcome_statuses["infeasible_under_calculator_abi"]
    )
    return [
        {
            "area": "render type 1Fh record oracle",
            "status": "open",
            "reason": (
                "the 34:6119 table entry fixes A=43h and therefore the 61BEh "
                "bitmap path, but no retained record oracle dispatches a type-1Fh node"
            ),
        },
        {
            "area": "editor equation representation",
            "status": "open",
            "reason": (
                "page 39 proves class/handler cell grids and operand walking, but the "
                "in-progress editor data structure before 34:4900 is not decoded as a "
                "general AST"
            ),
        },
        {
            "area": "arbitrary token streams",
            "status": "open",
            "reason": (
                "parse-ahead has unbounded stream length and state; finite traces do not "
                "prove every depth, malformed-input, quote, or editor-flag combination"
            ),
        },
        {
            "area": "indirect and RAM-bjump edges",
            "status": "open",
            "reason": (
                "the direct CFG does not discover computed dispatches or enter bcall and "
                "RAM-bjump bodies; manually seeded table destinations do not prove that "
                "every runtime target is known"
            ),
        },
        {
            "area": "asynchronous LCD writes",
            "status": "outside parity surface",
            "reason": (
                "the translated stream models synchronous MathPrint writes; timer interrupt "
                "indicator writes are separated from renderer parity"
            ),
        },
        {
            "area": "structural table oracle domain",
            "status": "closed_except_1Fh" if missing_types == ["0x1F"] else "open",
            "reason": f"record types without captured node oracles: {', '.join(missing_types) or 'none'}",
        },
        {
            "area": "editor branch outcomes",
            "status": "open" if editor_dynamic["branches_unobserved"] else "observed",
            "reason": (
                f"{editor_dynamic['branches_unobserved']} declared editor CFG branches have "
                "no outcome in the retained saturation trace set"
            ),
        },
        {
            "area": "declared CFG outcome classification",
            "status": (
                "open" if outcome_statuses["unresolved_state_or_abi"] else "closed"
            ),
            "reason": (
                f"{outcome_statuses['exercised']} outcomes are exercised, "
                f"{infeasible} are proved infeasible under data invariants or "
                "the calculator call ABI, and "
                f"{outcome_statuses['unresolved_state_or_abi']} remain unresolved"
            ),
        },
    ]


def parse_trace(value: str) -> tuple[str, Path]:
    label, separator, raw_path = value.partition("=")
    if not separator or not label or not raw_path:
        raise argparse.ArgumentTypeError("trace must have LABEL=PATH form")
    path = Path(raw_path)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"trace does not exist: {path}")
    return label, path


def validate_trace_provenance(label: str, path: Path, provenance: str) -> None:
    """Reject known state-injection recipes mislabeled as natural input."""

    macro = path.with_suffix(".macro")
    if not macro.is_file():
        return
    injected = any(
        line.lstrip().startswith("memwrite ")
        for line in macro.read_text().splitlines()
    )
    if injected and provenance != TRACE_PROVENANCE_SYNTHETIC:
        raise ValueError(
            f"trace {label!r} has a sibling macro containing memwrite; classify "
            f"it as {TRACE_PROVENANCE_SYNTHETIC!r}"
        )


def build_report(
    rom: RomImage,
    traces: Sequence[tuple[str, Path]],
    instruction_list: Path | None = None,
    trace_cache: Path | None = None,
    trace_provenance: dict[str, str] | None = None,
) -> dict[str, object]:
    if instruction_list is None:
        instruction_maps: dict[int, dict[int, Z80Instruction]] = {}
        for page in sorted({region.page for component in COMPONENTS for region in component.regions}):
            instruction_maps[page] = {
                instruction.location.address: instruction
                for instruction in disassemble_page(rom, page)
            }
        instruction_backend = "z80dasm 1.2 linear decode"
    else:
        instruction_maps = load_ghidra_instructions(instruction_list, rom)
        instruction_backend = (
            "rebuilt Ghidra database via ExportMathPrintInstructionStarts.java"
        )
    cfgs = [
        build_component_cfg(component, instruction_maps, rom)
        for component in COMPONENTS
    ]
    branches = [branch for cfg in cfgs for branch in cfg.branches]
    duplicate_branches = Counter(branch.key for branch in branches)
    if any(count != 1 for count in duplicate_branches.values()):
        raise ValueError("declared components overlap at conditional branch instructions")
    branch_index = {branch.key: branch for branch in branches}
    instruction_universe = {
        trace_key(instruction.location) for cfg in cfgs for instruction in cfg.instructions
    }
    fingerprint = cfg_fingerprint(cfgs)
    cache = load_trace_cache(trace_cache, fingerprint)
    cache_entries = cache["entries"]

    trace_rows = []
    provenance = trace_provenance or {}
    outcomes: Counter[tuple[str, int, str]] = Counter()
    instruction_hits: Counter[tuple[str, int]] = Counter()
    witnesses: dict[tuple[str, int, str], dict[str, object]] = {}
    natural_outcomes: Counter[tuple[str, int, str]] = Counter()
    natural_instruction_hits: Counter[tuple[str, int]] = Counter()
    natural_witnesses: dict[tuple[str, int, str], dict[str, object]] = {}
    trace_outcomes: dict[str, set[tuple[str, int, str]]] = {}
    trace_features: dict[str, set[str]] = {}
    for label, path in traces:
        trace_sha256 = digest(path)
        cached = cache_entries.get(trace_sha256)
        if cached is None:
            (
                row, local_outcomes, local_hits, local_witnesses,
                local_entries, local_paths,
            ) = scan_trace(
                label, path, branch_index, instruction_universe,
                trace_sha256=trace_sha256,
            )
            cache_entries[trace_sha256] = serialize_trace_summary(
                row, local_outcomes, local_hits, local_witnesses,
                local_entries, local_paths,
            )
            if trace_cache is not None:
                write_trace_cache(trace_cache, cache)
        else:
            (
                row, local_outcomes, local_hits, local_witnesses,
                local_entries, local_paths,
            ) = deserialize_trace_summary(label, cached)
        local_set = set(local_outcomes)
        trace_outcomes[label] = local_set
        trace_features[label] = trace_dynamic_features(
            local_set, local_entries, local_paths
        )
        row["provenance"] = provenance.get(label, TRACE_PROVENANCE_NATURAL)
        row["unique_branch_outcomes"] = len(local_set)
        trace_rows.append(row)
        outcomes.update(local_outcomes)
        instruction_hits.update(local_hits)
        for key, value in local_witnesses.items():
            value["provenance"] = row["provenance"]
            witnesses.setdefault(key, value)
        if row["provenance"] == TRACE_PROVENANCE_NATURAL:
            natural_outcomes.update(local_outcomes)
            natural_instruction_hits.update(local_hits)
            for key, value in local_witnesses.items():
                natural_witnesses.setdefault(key, value)

    # Prefer a natural-input witness when both provenance classes exercise the
    # same outcome. Synthetic traces remain the witness of record only for
    # outcomes absent from every key-driven run.
    witnesses.update(natural_witnesses)

    oracle = oracle_coverage(ROOT.glob("tools/mathprint-*-oracles.json"))
    oracle_features = oracle_trace_features(
        ROOT.glob("tools/mathprint-*-oracles.json")
    )
    for row in trace_rows:
        trace_features[row["label"]].update(
            oracle_features.get(row["sha256"], set())
        )
    table = table_report(rom, oracle)
    component_rows = {
        cfg.component.name: component_report(
            cfg, outcomes, instruction_hits, witnesses, OUTCOME_CLASSIFICATIONS
        )
        for cfg in cfgs
    }
    natural_component_rows = {
        cfg.component.name: component_report(
            cfg, natural_outcomes, natural_instruction_hits, natural_witnesses,
            OUTCOME_CLASSIFICATIONS,
        )
        for cfg in cfgs
    }
    for name, row in component_rows.items():
        row["natural_dynamic"] = natural_component_rows[name]["dynamic"]
    unresolved_count = sum(
        len(row["static"]["unresolved_direct_control_transfers"])
        for row in component_rows.values()
    )
    total_branches = sum(row["static"]["conditional_branches"] for row in component_rows.values())
    total_outcomes = sum(row["dynamic"]["branch_outcomes_observed"] for row in component_rows.values())
    outcome_statuses = Counter(
        outcome["status"]
        for component in component_rows.values()
        for branch in component["branches"]
        for outcome in branch["outcomes"]
    )
    natural_outcome_statuses = Counter(
        outcome["status"]
        for component in natural_component_rows.values()
        for branch in component["branches"]
        for outcome in branch["outcomes"]
    )
    external_targets = {
        target
        for row in component_rows.values()
        for target in row["static"]["external_direct_targets"]
    }
    trace_sizes = {row["label"]: row["bytes"] for row in trace_rows}
    natural_trace_outcomes = {
        label: values for label, values in trace_outcomes.items()
        if provenance.get(label, TRACE_PROVENANCE_NATURAL)
        == TRACE_PROVENANCE_NATURAL
    }
    natural_trace_features = {
        label: values for label, values in trace_features.items()
        if provenance.get(label, TRACE_PROVENANCE_NATURAL)
        == TRACE_PROVENANCE_NATURAL
    }
    symbolic_corpus = symbolic_model_corpus()
    report = {
        "schema": 2,
        "claim": {
            "scope": "declared MathPrint entries, decoded table rows, modeled predicate projections, and named traces",
            "not_claimed": [
                "whole-ROM reachability",
                "all possible editor or RAM states",
                "all arbitrary or malformed token streams",
                "full parity with every MathPrint assembly entry",
            ],
            "saturated_means": (
                "all values in a named projected domain are partitioned; this does not "
                "establish reachability for arbitrary machine states"
            ),
        },
        "rom": {"sha256": TI84_PLUS_OS_255MP_SHA256, "model": "TI-84 Plus", "os": "2.55MP"},
        "method": {
            "instruction_boundaries": instruction_backend,
            "instruction_list_sha256": (
                digest(instruction_list) if instruction_list is not None else None
            ),
            "static_cfg": "recursive direct-edge traversal from declared entries",
            "symbolic": (
                "fixed table-row decoding, complete path-equivalence classes, "
                "and exact minimum branch-outcome representatives for eight "
                "finite projected domains"
            ),
            "computed_dispatches": {
                "manually_seeded": [
                    "34:6118 render table", "34:7393 metric table",
                    "34:7609 geometry table", "39:4C27 editor class table",
                ],
                "skipped_call_mechanisms": [
                    "RST 28h bcall bodies", "RAM bjump descriptor bodies",
                ],
            },
            "dynamic": (
                "resolved TLMT next-PC outcomes over named natural-input and "
                "explicitly classified synthetic-state traces"
            ),
            "trace_cache": (
                "per-trace summaries keyed by CFG fingerprint and trace SHA-256"
                if trace_cache is not None else None
            ),
            "oracle": "captured record graphs and accepted LCD-write digests; never renderer inputs",
        },
        "summary": {
            "components": len(component_rows),
            "reachable_instructions": sum(row["static"]["reachable_instructions"] for row in component_rows.values()),
            "conditional_branches": total_branches,
            "possible_branch_outcomes": 2 * total_branches,
            "branch_outcomes_observed": total_outcomes,
            "branch_outcome_statuses": dict(sorted(outcome_statuses.items())),
            "natural_branch_outcomes_observed": sum(
                row["dynamic"]["branch_outcomes_observed"]
                for row in natural_component_rows.values()
            ),
            "natural_branch_outcome_statuses": dict(sorted(
                natural_outcome_statuses.items()
            )),
            "unresolved_direct_control_transfers": unresolved_count,
            "external_direct_targets": len(external_targets),
            "structural_types_with_oracles": sum(row["oracle_records"] > 0 for row in table["structural_dispatch"]),
            "structural_type_domain": len(table["structural_dispatch"]),
            "symbolic_path_equivalence_classes": (
                symbolic_corpus["path_equivalence_class_count"]
            ),
            "symbolic_distinct_branch_outcomes": (
                symbolic_corpus["distinct_modeled_branch_outcomes"]
            ),
            "symbolic_per_domain_minimum_representatives": (
                symbolic_corpus[
                    "per_domain_minimum_branch_outcome_corpus_count"
                ]
            ),
            "globally_saturated": False,
        },
        "tables": table,
        "symbolic_model_corpus": symbolic_corpus,
        "symbolic_predicates": {
            "structural_scan_kind_dispatch": {
                "routine": "34:5678",
                "state": ["incoming A scan-kind byte"],
                "projected_input_domain": 0x100,
                "rom_metadata_values": table["scan_kinds"],
                "terminal_classes": symbolic_scan_kind_paths(outcomes),
            },
            "raised_extended_token_classifier": {
                "routine": "34:580C",
                "state": ["A selected by 34:56A4", "packed-token low byte E"],
                "caller_precondition": (
                    "A is an ordinary token byte or one of the 11 native "
                    "two-byte lead bytes returned by 34:58F9"
                ),
                "projected_input_domain": sum(
                    1 for _state in raised_classifier_caller_states()
                ),
                "terminal_classes": symbolic_raised_extended_token_paths(outcomes),
                "bounded_name_loops": [
                    {
                        "designator": f"0x{designator:02X}",
                        "routine": "34:5836–5855",
                        "byte_limit": limit,
                        "accepted_byte_classes": [
                            "0x30–0x39 digits", "0x41–0x5B letters",
                        ],
                        "path_classes": symbolic_raised_name_loop_paths(limit),
                    }
                    for designator, limit in ((0xEB, 5), (0x5F, 8))
                ],
            },
            "shared_marker_draw_helper": {
                "routine": "34:6143",
                "state": ["A", "(IY+44h).3", "word 0x8520"],
                "projected_input_domain": 0x100 * 2 * 0x10000,
                "terminal_classes": symbolic_type1f_paths(
                    observed_outcomes=outcomes
                ),
                "entry_abis": type1f_entry_abis(rom, outcomes, witnesses),
                "dynamic_record_oracle": False,
            },
            "metric_marker_tail_gate": {
                "routine": "34:759C",
                "state": [
                    "parsed pointer == editTail + 6",
                    "cxCurApp == kYequ and tblFlags.0",
                    "marker type in {0x20,0x24,0x2A}",
                    "nesting counter 0x8515",
                ],
                "abstract_predicate_domain": 16,
                "terminal_classes": symbolic_metric_marker_paths(outcomes),
                "callers": metric_marker_callers(outcomes),
            },
        },
        "record_oracles": oracle,
        "traces": trace_rows,
        "minimized_trace_corpus": minimize_trace_corpus(
            trace_outcomes, trace_sizes, provenance,
        ),
        "minimized_natural_trace_corpus": minimize_trace_corpus(
            natural_trace_outcomes,
            {label: trace_sizes[label] for label in natural_trace_outcomes},
            {label: TRACE_PROVENANCE_NATURAL for label in natural_trace_outcomes},
        ),
        "minimized_dynamic_feature_corpus": minimize_trace_features(
            trace_features, trace_sizes, provenance,
        ),
        "minimized_natural_dynamic_feature_corpus": minimize_trace_features(
            natural_trace_features,
            {label: trace_sizes[label] for label in natural_trace_features},
            {label: TRACE_PROVENANCE_NATURAL for label in natural_trace_features},
        ),
        "components": component_rows,
        "translation_surfaces": list(TRANSLATION_SURFACES),
    }
    report["open_paths"] = open_paths(table, component_rows, outcome_statuses)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--instruction-list", type=Path,
        help="TSV from ExportMathPrintInstructionStarts.java; defaults to z80dasm",
    )
    parser.add_argument("--trace", action="append", type=parse_trace, default=[])
    parser.add_argument(
        "--synthetic-trace", action="append", type=parse_trace, default=[],
        help="trace whose calculator state was injected rather than reached by keys",
    )
    parser.add_argument(
        "--trace-cache", type=Path,
        help="optional local JSON cache for completed per-trace scans",
    )
    parser.add_argument(
        "--trace-manifest", type=Path,
        help=(
            "optional TSV of LABEL, PATH, and optional PROVENANCE fields "
            "appended to command-line trace inputs"
        ),
    )
    args = parser.parse_args()
    if not args.rom.is_file():
        parser.error(f"ROM not found: {args.rom}")
    if digest(args.rom) != TI84_PLUS_OS_255MP_SHA256:
        parser.error("ROM SHA-256 does not match the pinned TI-84 Plus OS 2.55MP image")
    traces = list(args.trace)
    provenance = {
        label: TRACE_PROVENANCE_NATURAL for label, _path in args.trace
    }
    for label, path in args.synthetic_trace:
        traces.append((label, path))
        provenance[label] = TRACE_PROVENANCE_SYNTHETIC
    if args.trace_manifest is not None:
        if not args.trace_manifest.is_file():
            parser.error(f"trace manifest does not exist: {args.trace_manifest}")
        for line_number, line in enumerate(args.trace_manifest.read_text().splitlines(), 1):
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) not in (2, 3) or not all(fields):
                parser.error(
                    f"{args.trace_manifest}:{line_number}: expected "
                    "LABEL<TAB>PATH[<TAB>PROVENANCE]"
                )
            label, raw_path = fields[:2]
            trace_kind = fields[2] if len(fields) == 3 else TRACE_PROVENANCE_NATURAL
            if trace_kind not in TRACE_PROVENANCE_VALUES:
                parser.error(
                    f"{args.trace_manifest}:{line_number}: unsupported trace "
                    f"provenance {trace_kind!r}"
                )
            path = Path(raw_path)
            if not path.is_file():
                parser.error(
                    f"{args.trace_manifest}:{line_number}: trace does not exist: {path}"
                )
            traces.append((label, path))
            provenance[label] = trace_kind
    labels = [label for label, _path in traces]
    if len(labels) != len(set(labels)):
        parser.error("trace labels must be unique")
    for label, path in traces:
        try:
            validate_trace_provenance(
                label, path,
                provenance.get(label, TRACE_PROVENANCE_NATURAL),
            )
        except ValueError as error:
            parser.error(str(error))
    if args.instruction_list is not None and not args.instruction_list.is_file():
        parser.error(f"instruction list does not exist: {args.instruction_list}")

    report = build_report(
        RomImage.from_path(args.rom), traces, args.instruction_list,
        args.trace_cache, provenance,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    summary = report["summary"]
    print(
        f"wrote {args.output}: {summary['reachable_instructions']} instructions, "
        f"{summary['branch_outcomes_observed']}/{summary['possible_branch_outcomes']} "
        f"branch outcomes observed, {summary['structural_types_with_oracles']}/"
        f"{summary['structural_type_domain']} structural types with record oracles"
    )


if __name__ == "__main__":
    main()
