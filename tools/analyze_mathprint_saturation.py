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
TRACE_CACHE_SCHEMA = 4
EXHAUSTIVE_COVER_LIMIT = 24
TRACE_PROVENANCE_NATURAL = "natural_calculator_input"
TRACE_PROVENANCE_SYNTHETIC = "synthetic_state_injection"
TRACE_PROVENANCE_VALUES = frozenset({
    TRACE_PROVENANCE_NATURAL,
    TRACE_PROVENANCE_SYNTHETIC,
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


def iter_oracle_cases(document: object) -> Iterator[dict[str, object]]:
    if not isinstance(document, dict):
        return
    for value in document.values():
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("nodes"), list):
                yield item


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

    source = []
    for first, second, render_type in rows["source_token_to_type"]:
        source.append(
            {
                "token": f"{second:02X}{first:02X}h",
                "bytes_de": [second, first],
                "render_type": f"0x{render_type:02X}",
                "exceptional": render_type == 0x2C,
            }
        )
    editor_words = word_rows(rows["editor_class_handlers"])
    return {
        "source_token_map": source,
        "structural_dispatch": structural,
        "scan_kinds": sorted({row[0] for row in rows["record_metadata"]}),
        "nonzero_scan_kinds": sorted({row[0] for row in rows["record_metadata"] if row[0]}),
        "editor_class_table": {
            "entries": len(editor_words),
            "nonzero_pointers": sum(bool(value) for value in editor_words),
            "pointers": [f"39:{value:04X}" if value else None for value in editor_words],
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


def trace_dynamic_features(
    outcomes: set[tuple[str, int, str]],
    witnesses: dict[tuple[str, int, str], dict[str, object]],
) -> set[str]:
    """Tag branch outcomes and sound modeled path/state witnesses."""

    features = {f"branch_outcome:{outcome_id(key)}" for key in outcomes}
    for terminal, key in {
        "generic_scan": ("page_34", 0x567A, "taken"),
        "raised_operand_scan": ("page_34", 0x567C, "taken"),
        "fraction_operand_scan": ("page_34", 0x5680, "taken"),
        "single_argument_scan": ("page_34", 0x5682, "taken"),
        "multi_argument_scan": ("page_34", 0x5686, "taken"),
        "kind_5_scan": ("page_34", 0x5688, "taken"),
        "kind_6_or_greater_scan": ("page_34", 0x5688, "fallthrough"),
    }.items():
        if key in outcomes:
            features.add(f"modeled_path:34:5678:{terminal}")
    for terminal, key in {
        "return_nz_pointer_mismatch": ("page_34", 0x75A5, "returned"),
        "return_nz_yequ_table": ("page_34", 0x75A9, "taken"),
        "return_nz_other_marker": ("page_34", 0x75B0, "fallthrough"),
        "return_z_special_marker_nested": ("page_34", 0x75BB, "fallthrough"),
        "return_z_special_marker_top_level": ("page_34", 0x75BB, "taken"),
    }.items():
        if key in outcomes:
            features.add(f"modeled_path:34:759C:{terminal}")
    for a, address, outcome, bit in (
        (0x27, 0x614E, "fallthrough", 0),
        (0x27, 0x614E, "taken", 1),
        (0x22, 0x6157, "fallthrough", 0),
        (0x21, 0x6166, "taken", 0),
        (0x25, 0x616C, "taken", 0),
        (0x26, 0x619F, "taken", 0),
        (0x28, 0x61A5, "taken", 0),
        (0x29, 0x61AB, "taken", 0),
    ):
        key = ("page_34", address, outcome)
        witness = witnesses.get(key)
        if not witness or witness["state"]["A"] != a:
            continue
        terminal = type1f_path(a, bit, 0)["terminal"]
        features.add(f"entry_state:34:6143:A=0x{a:02X}")
        features.add(
            f"modeled_path:34:6143:A=0x{a:02X}:bit3={bit}:{terminal}"
        )
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
]:
    banker = make_banker("ti84p-reset")
    branch_outcomes: Counter[tuple[str, int, str]] = Counter()
    instruction_hits: Counter[tuple[str, int]] = Counter()
    pending: tuple[Branch, dict[str, int], int] | None = None
    witnesses: dict[tuple[str, int, str], dict[str, object]] = {}
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
            if point in instruction_universe:
                instruction_hits[point] += 1
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
    }


def deserialize_trace_summary(
    label: str, cached: dict[str, object]
) -> tuple[
    dict[str, object],
    Counter[tuple[str, int, str]],
    Counter[tuple[str, int]],
    dict[tuple[str, int, str], dict[str, object]],
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
    return row, outcomes, hits, witnesses


def load_trace_cache(path: Path | None, fingerprint: str) -> dict[str, object]:
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
            row, local_outcomes, local_hits, local_witnesses = scan_trace(
                label, path, branch_index, instruction_universe,
                trace_sha256=trace_sha256,
            )
            cache_entries[trace_sha256] = serialize_trace_summary(
                row, local_outcomes, local_hits, local_witnesses
            )
            if trace_cache is not None:
                write_trace_cache(trace_cache, cache)
        else:
            row, local_outcomes, local_hits, local_witnesses = (
                deserialize_trace_summary(label, cached)
            )
        local_set = set(local_outcomes)
        trace_outcomes[label] = local_set
        trace_features[label] = trace_dynamic_features(local_set, local_witnesses)
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
    report = {
        "schema": 1,
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
            "symbolic": "fixed table-row decoding and representative equivalence classes for selected predicate projections",
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
            "globally_saturated": False,
        },
        "tables": table,
        "symbolic_predicates": {
            "structural_scan_kind_dispatch": {
                "routine": "34:5678",
                "state": ["incoming A scan-kind byte"],
                "projected_input_domain": 0x100,
                "rom_metadata_values": table["scan_kinds"],
                "terminal_classes": symbolic_scan_kind_paths(outcomes),
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
