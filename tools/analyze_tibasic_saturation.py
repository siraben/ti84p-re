#!/usr/bin/env python3
"""Audit bounded TI-BASIC interpreter CFG and trace saturation.

The control-flow graph starts at ROM table destinations and named subsystem
entries. Computed jumps, cross-component calls, and missing Ghidra boundaries
remain explicit. Raw TLMT traces are reduced to hashes and aggregate coverage;
they are never repository artifacts.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Iterable, Iterator, Sequence

from analyze_tibasic_coverage import (
    TRACE_PROVENANCE,
    digest,
    parse_trace,
    z3_minimum_cover,
)
from hardware_trace import make_banker
from rom_image import RomImage, RomLocation
from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from tilem_trace_resolve import iter_records, read_header, resolve_instruction
from z80_disassembly import Z80Instruction, direct_target, parse_z80dasm


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "tools" / "rom.bin"
DEFAULT_OUTPUT = ROOT / "tools" / "tibasic-saturation.json"


@dataclass(frozen=True)
class Region:
    page: int
    start: int
    end: int

    def contains(self, location: RomLocation) -> bool:
        return location.page == self.page and self.start <= location.address < self.end

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
    fallthrough: RomLocation

    @property
    def key(self) -> tuple[str, int]:
        return trace_key(self.location)


@dataclass(frozen=True)
class ComponentCfg:
    component: Component
    instructions: tuple[Z80Instruction, ...]
    branches: tuple[Branch, ...]
    unresolved: tuple[dict[str, str], ...]
    external_targets: tuple[RomLocation, ...]


NAMED_ANCHORS = {
    ("page_38", 0x41E5): "For production entry",
    ("page_38", 0x4200): "End production entry",
    ("page_38", 0x5836): "initial loop continuation",
    ("page_38", 0x587D): "steady loop continuation",
    ("page_38", 0x7244): "computed production dispatch",
    ("page_38", 0x5CD8): "parse expectation/error boundary",
    ("page_07", 0x565F): "VAT symbol scan",
    ("ram", 0x26E8): "overflow error",
    ("ram", 0x26EC): "division-by-zero error",
    ("ram", 0x26F4): "domain error",
    ("ram", 0x2700): "syntax error",
}


def trace_space(page: int) -> str:
    return "ram" if page == 0 else f"page_{page:02X}"


def trace_key(location: RomLocation) -> tuple[str, int]:
    return trace_space(location.page), location.address


def page_from_space(space: str) -> int:
    return 0 if space == "ram" else int(space.removeprefix("page_"), 16)


def load_instructions(path: Path, rom: RomImage) -> dict[int, dict[int, Z80Instruction]]:
    result: dict[int, dict[int, Z80Instruction]] = defaultdict(dict)
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
        if rom.bytes_at(page, address, len(data)) != data:
            raise ValueError(f"{path}:{line_number}: bytes disagree with pinned ROM")
        if address in result[page]:
            raise ValueError(f"{path}:{line_number}: duplicate instruction boundary")
        result[page][address] = Z80Instruction(
            RomLocation(page, address), data, text.strip().lower()
        )
    return dict(result)


def decode_instruction_at(rom: RomImage, location: RomLocation) -> Z80Instruction:
    """Decode one proven flow target without inheriting a table boundary."""

    data = rom.bytes_at(location.page, location.address, 6)
    with tempfile.NamedTemporaryFile(prefix="tibasic-instruction-") as stream:
        stream.write(data)
        stream.flush()
        result = subprocess.run(
            ["z80dasm", "-a", "-t", "-g", f"0x{location.address:X}", stream.name],
            check=False,
            capture_output=True,
            text=True,
        )
    if result.returncode:
        raise ValueError(f"z80dasm failed at {location}: {result.stderr.strip()}")
    decoded = tuple(parse_z80dasm(result.stdout, location.page))
    if not decoded or decoded[0].location != location:
        raise ValueError(f"z80dasm did not decode requested instruction {location}")
    return decoded[0]


def parser_table(rom: RomImage) -> dict[str, object]:
    values = [rom.u16le(0x38, 0x4000 + 2 * index) for index in range(87)]
    valid = [value for value in values if 0x4000 <= value < 0x8000]
    return {
        "location": "38:4000–40AD",
        "slots": len(values),
        "valid_pointer_slots": len(valid),
        "unique_handler_entries": len(set(valid)),
        "invalid_slots": [index for index, value in enumerate(values) if value not in valid],
        "handler_entries": [f"38:{value:04X}" for value in sorted(set(valid))],
    }


def computed_dispatches(rom: RomImage) -> dict[RomLocation, tuple[RomLocation, ...]]:
    """Return destinations for ROM-owned indirect jumps in the declared graph."""

    operation_handlers = {
        rom.u16le(0x38, 0x4FDB + 2 * index) for index in range(49)
    } - {0}
    return {
        RomLocation(0x38, 0x4390): tuple(
            RomLocation(0x38, address) for address in (
                0x5108, 0x510C, 0x5110, 0x5127, 0x511C, 0x5120, 0x5114,
                0x5118, 0x5133, 0x5137, 0x513B, 0x513F, 0x5143, 0x5147,
            )
        ),
        RomLocation(0x38, 0x7244): tuple(
            RomLocation(0x38, address) for address in sorted(operation_handlers)
        ),
        RomLocation(0x02, 0x5675): tuple(
            RomLocation(0x02, address)
            for address in (0x5026, 0x69F5, 0x69FB, 0x6A00, 0x6A04)
        ),
        RomLocation(0x33, 0x4380): tuple(
            RomLocation(0x33, rom.u16le(0x33, 0x4381 + 2 * index))
            for index in range(13)
        ),
    }


def dispatch_report(rom: RomImage) -> list[dict[str, object]]:
    dispatches = computed_dispatches(rom)
    operation_rows = [rom.u16le(0x38, 0x4FDB + 2 * index) for index in range(49)]
    return [
        {
            "location": str(location),
            "bounded_by": boundary,
            "destinations": len(set(targets)),
        }
        for location, targets, boundary in (
            (
                RomLocation(0x38, 0x4390),
                dispatches[RomLocation(0x38, 0x4390)],
                "14 entry wrappers load literal continuation addresses",
            ),
            (
                RomLocation(0x38, 0x7244),
                dispatches[RomLocation(0x38, 0x7244)],
                f"49 valid type classes; {operation_rows.count(0)} invalid zero rows",
            ),
            (
                RomLocation(0x02, 0x5675),
                dispatches[RomLocation(0x02, 0x5675)],
                "five preceding token comparisons select literal targets",
            ),
            (
                RomLocation(0x33, 0x4380),
                dispatches[RomLocation(0x33, 0x4380)],
                "bounds check accepts 13 table indices",
            ),
        )
    ]


def components(rom: RomImage) -> tuple[Component, ...]:
    parser_entries = {
        rom.u16le(0x38, 0x4000 + 2 * index)
        for index in range(87)
    }
    parser_entries = {value for value in parser_entries if 0x4100 <= value < 0x7800}
    parser_entries.update({
        0x4130, 0x4180, 0x4870, 0x5826, 0x5987, 0x59C5, 0x5AB3,
        0x5C00, 0x6251, 0x679F, 0x6910, 0x69C5, 0x6A15, 0x7010,
        0x7244, 0x7248, 0x72DA, 0x7511, 0x7521, 0x752A, 0x753E,
        0x758A, 0x778F,
    })
    control_entries = {
        rom.u16le(0x33, 0x4381 + 2 * index) for index in range(13)
    } | {0x435F}
    return (
        Component(
            "parser_core",
            "statement scanning, grammar handlers, recursive expressions, and OPS frames",
            (Region(0x38, 0x4100, 0x7800),),
            tuple(RomLocation(0x38, address) for address in sorted(parser_entries)),
        ),
        Component(
            "command_arguments",
            "Input, Menu, Pause, Prompt, command finalization, and Output argument handling",
            (Region(0x02, 0x54EF, 0x56C3), Region(0x02, 0x673E, 0x6800)),
            tuple(RomLocation(0x02, address) for address in (
                0x54EF, 0x555D, 0x55E7, 0x562F, 0x5676, 0x673E,
            )),
        ),
        Component(
            "control_flow",
            "bounded page-33 control-flow dispatch and its 13 ROM table destinations",
            (Region(0x33, 0x435F, 0x4D50),),
            tuple(RomLocation(0x33, address) for address in sorted(control_entries)),
        ),
        Component(
            "value_storage",
            "memory checks, VAT allocation, scalar storage, and floating-point stack movement",
            (Region(0x00, 0x0E20, 0x1800),),
            tuple(RomLocation(0, address) for address in (
                0x0E20, 0x0FA6, 0x0FF0, 0x100B, 0x1080, 0x1183,
                0x12A1, 0x1308, 0x1475, 0x14F0, 0x1518, 0x151E,
                0x159C, 0x15A3, 0x1690, 0x1735, 0x1749,
            )),
        ),
        Component(
            "numeric_errors",
            "numeric guards, loop progress checks, and shared error entries",
            (
                Region(0x00, 0x1B80, 0x1BA4),
                Region(0x00, 0x1D80, 0x2800),
                Region(0x02, 0x4390, 0x43B0),
                Region(0x02, 0x4F90, 0x4FD8),
                Region(0x02, 0x6F00, 0x7140),
                Region(0x02, 0x76D0, 0x7720),
                Region(0x35, 0x79B0, 0x79E0),
                Region(0x37, 0x4250, 0x4270),
            ),
            (
                *(RomLocation(0, address) for address in (
                    0x1B8F, 0x1DFD, 0x1F0F, 0x1FD6, 0x2119, 0x2123,
                    0x2125, 0x212D, 0x2513, 0x2548, 0x26E8, 0x26EC,
                    0x26F0, 0x26F4, 0x26F8, 0x26FC, 0x2700, 0x2715,
                    0x2719, 0x2721,
                )),
                *(RomLocation(0x02, address) for address in (
                    0x439C, 0x4FA1, 0x4FC8, 0x6F1E, 0x7053, 0x7076,
                    0x76DF, 0x76F1,
                )),
                RomLocation(0x35, 0x79CF),
                RomLocation(0x37, 0x4268),
            ),
        ),
    )


def direct_instruction_target(instruction: Z80Instruction) -> int | None:
    result = direct_target(instruction)
    if result is not None:
        return result
    if instruction.mnemonic not in {"call", "jp"}:
        return None
    matches = re.findall(r"0x([0-9a-f]+)", instruction.operands)
    return int(matches[-1], 16) if matches else None


def target_location(instruction: Z80Instruction, address: int) -> RomLocation:
    return RomLocation(0 if address < 0x4000 else instruction.location.page, address)


def relative_target(instruction: Z80Instruction) -> RomLocation:
    displacement = int.from_bytes(instruction.data[-1:], "little", signed=True)
    return target_location(instruction, (instruction.end_address + displacement) & 0xFFFF)


def conditional(instruction: Z80Instruction) -> bool:
    if instruction.mnemonic in {"jr", "jp", "call"}:
        return "," in instruction.operands
    if instruction.mnemonic == "ret":
        return bool(instruction.operands)
    return instruction.mnemonic == "djnz"


def branch_for(instruction: Z80Instruction) -> Branch | None:
    if not conditional(instruction):
        return None
    fallthrough = target_location(instruction, instruction.end_address)
    if instruction.mnemonic in {"jr", "djnz"}:
        target = relative_target(instruction)
    elif instruction.mnemonic in {"jp", "call"}:
        address = direct_instruction_target(instruction)
        target = None if address is None else target_location(instruction, address)
    else:
        target = None
    return Branch(
        instruction.location, instruction.text, instruction.mnemonic, target, fallthrough
    )


def in_component(component: Component, location: RomLocation) -> bool:
    return any(region.contains(location) for region in component.regions)


def build_cfg(
    component: Component,
    instruction_maps: dict[int, dict[int, Z80Instruction]],
    rom: RomImage,
) -> ComponentCfg:
    pending = deque(component.entries)
    reachable: dict[RomLocation, Z80Instruction] = {}
    unresolved: dict[tuple[str, str], dict[str, str]] = {}
    external: set[RomLocation] = set()
    indirect_targets = computed_dispatches(rom)

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
            if conditional(instruction):
                enqueue(fallthrough)
            continue
        if mnemonic == "rst":
            skip = 2 if instruction.data == b"\xEF" else 0
            enqueue(target_location(instruction, instruction.end_address + skip))
            continue
        if mnemonic in {"jp", "call"}:
            address = direct_instruction_target(instruction)
            if address is None:
                destinations = indirect_targets.get(location)
                if destinations is None:
                    unresolved[(str(location), mnemonic)] = {
                        "location": str(location),
                        "kind": f"indirect_{mnemonic}",
                    }
                else:
                    for destination in destinations:
                        if in_component(component, destination):
                            enqueue(destination)
                        else:
                            external.add(destination)
            elif mnemonic == "call" and address == 0x2B09:
                descriptor = instruction.end_address
                destination = RomLocation(
                    rom.bytes_at(location.page, descriptor + 2, 1)[0] & 0x3F,
                    rom.u16le(location.page, descriptor),
                )
                external.add(destination)
                enqueue(target_location(instruction, descriptor + 3))
                continue
            else:
                destination = target_location(instruction, address)
                if in_component(component, destination):
                    enqueue(destination)
                else:
                    external.add(destination)
            if mnemonic == "call" or conditional(instruction):
                enqueue(fallthrough)
            continue
        if mnemonic == "ret":
            if conditional(instruction):
                enqueue(fallthrough)
            continue
        if mnemonic in {"reti", "retn", "halt"}:
            continue
        enqueue(fallthrough)

    ordered = tuple(sorted(reachable.values(), key=lambda row: row.location.address))
    return ComponentCfg(
        component,
        ordered,
        tuple(branch for row in ordered if (branch := branch_for(row))),
        tuple(unresolved[key] for key in sorted(unresolved)),
        tuple(sorted(external, key=lambda row: (row.page, row.address))),
    )


def classify_successor(branch: Branch, point: tuple[str, int]) -> str | None:
    if branch.kind == "ret":
        return "fallthrough" if point == trace_key(branch.fallthrough) else "returned"
    if branch.target is not None and point == trace_key(branch.target):
        return "taken"
    if point == trace_key(branch.fallthrough):
        return "fallthrough"
    return None


def scan_trace(
    label: str,
    path: Path,
    branches: dict[tuple[str, int], Branch],
    instructions: set[tuple[str, int]],
) -> tuple[dict[str, object], set[str]]:
    banker = make_banker("ti84p-reset")
    pending: Branch | None = None
    outcomes: Counter[str] = Counter()
    hits: set[tuple[str, int]] = set()
    anchors: Counter[str] = Counter()
    count = 0
    with path.open("rb") as stream:
        read_header(stream)
        records: Iterator[tuple[int, object]] = iter_records(stream)
        for point in (
            resolve_instruction(banker, payload)[0][:2]
            for record_type, payload in records
            if record_type == 0x01
        ):
            if pending is not None:
                result = classify_successor(pending, point)
                if result is not None:
                    outcomes[f"{pending.location}:{result}"] += 1
                pending = None
            if point in instructions:
                hits.add(point)
            if point in NAMED_ANCHORS:
                anchors[NAMED_ANCHORS[point]] += 1
            if point in branches:
                pending = branches[point]
            count += 1
    return ({
        "label": label,
        "provenance": TRACE_PROVENANCE.get(label, "unspecified"),
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "instructions": count,
        "declared_instructions_hit": len(hits),
        "branch_outcomes_hit": len(outcomes),
        "anchor_hits": dict(sorted(anchors.items())),
    }, set(outcomes))


def build_report(
    rom_path: Path,
    instruction_list: Path,
    traces: Sequence[tuple[str, Path]],
) -> dict[str, object]:
    if digest(rom_path) != TI84_PLUS_OS_255MP_SHA256:
        raise ValueError("ROM SHA-256 does not match TI-84 Plus OS 2.55MP")
    rom = RomImage.from_path(rom_path)
    maps = load_instructions(instruction_list, rom)
    cfgs = tuple(build_cfg(component, maps, rom) for component in components(rom))
    all_branches = [branch for cfg in cfgs for branch in cfg.branches]
    duplicate = Counter(branch.key for branch in all_branches)
    if any(count != 1 for count in duplicate.values()):
        raise ValueError("component branch ranges overlap")
    branch_index = {branch.key: branch for branch in all_branches}
    instruction_universe = {
        trace_key(row.location) for cfg in cfgs for row in cfg.instructions
    }
    trace_rows = []
    features: dict[str, set[str]] = {}
    aggregate: set[str] = set()
    natural: set[str] = set()
    for label, path in traces:
        row, observed = scan_trace(label, path, branch_index, instruction_universe)
        trace_rows.append(row)
        features[label] = observed
        aggregate.update(observed)
        if row["provenance"] == "natural_tibasic":
            natural.update(observed)
    possible = {
        f"{branch.location}:{outcome}"
        for branch in all_branches
        for outcome in (("returned", "fallthrough") if branch.kind == "ret" else ("taken", "fallthrough"))
    }
    candidate_labels = sorted(label for label, values in features.items() if values)
    minimum = z3_minimum_cover(candidate_labels, features) if candidate_labels else ()
    dynamic_components = []
    for cfg in cfgs:
        component_possible = {
            f"{branch.location}:{outcome}"
            for branch in cfg.branches
            for outcome in (
                ("returned", "fallthrough")
                if branch.kind == "ret"
                else ("taken", "fallthrough")
            )
        }
        dynamic_components.append({
            "name": cfg.component.name,
            "outcomes_possible": len(component_possible),
            "outcomes_observed": len(component_possible & aggregate),
            "natural_outcomes_observed": len(component_possible & natural),
        })
    return {
        "schema": 1,
        "rom": {"path": "tools/rom.bin", "sha256": digest(rom_path)},
        "instruction_boundaries": {
            "source": "rebuilt Ghidra database plus exact-target z80dasm fallback",
            "sha256": digest(instruction_list),
        },
        "scope": {
            "claim": "direct CFG saturation for five declared interpreter components, with parser and control-table destinations seeded from ROM",
            "complete": False,
            "reason": "external page handlers, arbitrary parser/VAT/FPS states, invalid computed-dispatch inputs, and unseeded subsystem tables remain outside the graph",
        },
        "parser_handler_table": parser_table(rom),
        "computed_dispatches": dispatch_report(rom),
        "static": {
            "components": [{
                "name": cfg.component.name,
                "purpose": cfg.component.purpose,
                "regions": [region.text() for region in cfg.component.regions],
                "entry_count": len(cfg.component.entries),
                "reachable_instructions": len(cfg.instructions),
                "conditional_branches": len(cfg.branches),
                "possible_outcomes": 2 * len(cfg.branches),
                "unresolved": list(cfg.unresolved),
                "external_direct_targets": len(cfg.external_targets),
            } for cfg in cfgs],
            "reachable_instructions": len(instruction_universe),
            "conditional_branches": len(all_branches),
            "possible_outcomes": len(possible),
        },
        "dynamic": {
            "trace_count": len(trace_rows),
            "components": dynamic_components,
            "traces": sorted(trace_rows, key=lambda row: row["label"]),
            "outcomes_observed": len(aggregate),
            "natural_outcomes_observed": len(natural),
            "outcomes_unobserved": len(possible - aggregate),
            "observed_outcomes": sorted(aggregate),
            "minimum_outcome_corpus": {
                "algorithm": "exact lexicographic Optimize set cover via Z3",
                "selected": list(minimum),
                "selected_trace_count": len(minimum),
                "source_trace_count": len(candidate_labels),
            },
        },
        "next_expansion": [
            "prove caller-side bounds for every modeled computed-dispatch domain",
            "reject non-code and unreachable members of the 114-site numeric error reference census",
            "backward-slice executable error callers and retain minimal natural witnesses for distinct predicates",
            "model OPS/FPS record transitions and parser restore state as finite relations",
            "seed command-specific tables only after a natural trace enters their dispatcher",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--instruction-list", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--trace", action="append", type=parse_trace, default=[])
    args = parser.parse_args()
    labels = [label for label, _path in args.trace]
    if len(labels) != len(set(labels)):
        parser.error("trace labels must be unique")
    try:
        report = build_report(args.rom, args.instruction_list, args.trace)
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"wrote {args.output}: {report['dynamic']['outcomes_observed']} / "
        f"{report['static']['possible_outcomes']} outcomes observed"
    )


if __name__ == "__main__":
    main()
