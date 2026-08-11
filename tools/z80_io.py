"""Static Z80 I/O-access helpers for linear ROM disassembly.

Immediate-port instructions encode their port in the instruction.  The Z80's
``IN r,(C)`` and ``OUT (C),r`` forms instead take the low port byte from C.
This module resolves the latter only while a literal C value remains visible
within one straight-line instruction sequence.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from rom_image import RomImage, RomLocation
from z80_disassembly import Z80Instruction

_DIRECT_PORT_RE = re.compile(r"\(([0-9A-Fa-f]+)h\)")
_INDIRECT_C_RE = re.compile(r"\(c\)")
_HEX_OPERAND_RE = re.compile(r"^0*([0-9A-Fa-f]+)h$")
_BLOCK_IO_DIRECTIONS = {
    "ini": "in",
    "ind": "in",
    "inir": "in",
    "indr": "in",
    "outi": "out",
    "outd": "out",
    "otir": "out",
    "otdr": "out",
}
_INDIRECT_IO_OPCODES = {
    0x40: ("in", "IN B,(C)"),
    0x48: ("in", "IN C,(C)"),
    0x50: ("in", "IN D,(C)"),
    0x58: ("in", "IN E,(C)"),
    0x60: ("in", "IN H,(C)"),
    0x68: ("in", "IN L,(C)"),
    0x70: ("in", "IN (C)"),
    0x78: ("in", "IN A,(C)"),
    0x41: ("out", "OUT (C),B"),
    0x49: ("out", "OUT (C),C"),
    0x51: ("out", "OUT (C),D"),
    0x59: ("out", "OUT (C),E"),
    0x61: ("out", "OUT (C),H"),
    0x69: ("out", "OUT (C),L"),
    0x71: ("out", "OUT (C),0"),
    0x79: ("out", "OUT (C),A"),
    0xA2: ("in", "INI"),
    0xAA: ("in", "IND"),
    0xB2: ("in", "INIR"),
    0xBA: ("in", "INDR"),
    0xA3: ("out", "OUTI"),
    0xAB: ("out", "OUTD"),
    0xB3: ("out", "OTIR"),
    0xBB: ("out", "OTDR"),
}


@dataclass(frozen=True)
class DirectIOAccess:
    """One immediate-port ``IN`` or ``OUT`` instruction."""

    instruction: Z80Instruction
    direction: str
    port: int
    source: str = "immediate"


@dataclass(frozen=True)
class RawIndirectIO:
    """One raw ``ED``-prefixed register or block-I/O opcode pair."""

    location: RomLocation
    data: bytes
    direction: str
    form: str


def direct_io_access(instruction: Z80Instruction) -> DirectIOAccess | None:
    """Decode an immediate 8-bit port from an ``IN`` or ``OUT`` instruction."""

    if instruction.mnemonic not in {"in", "out"}:
        return None
    match = _DIRECT_PORT_RE.search(instruction.operands)
    if not match:
        return None
    return DirectIOAccess(
        instruction=instruction,
        direction=instruction.mnemonic,
        port=int(match.group(1), 16),
    )


def iter_direct_io_accesses(
    instructions: Iterable[Z80Instruction], ports: Iterable[int] | None = None
) -> Iterator[DirectIOAccess]:
    """Yield immediate-port accesses, optionally restricted to selected ports."""

    wanted = frozenset(ports) if ports is not None else None
    for instruction in instructions:
        access = direct_io_access(instruction)
        if access is not None and (wanted is None or access.port in wanted):
            yield access


def raw_indirect_io_locations(
    rom: RomImage, pages: Iterable[int] | None = None
) -> tuple[RawIndirectIO, ...]:
    """Return every raw register or block-I/O opcode pair in selected pages."""

    selected_pages = range(rom.page_count) if pages is None else tuple(pages)
    candidates = []
    for page_number in selected_pages:
        if not 0 <= page_number < rom.page_count:
            raise ValueError(f"page 0x{page_number:X} is outside this ROM")
        page = rom.page(page_number)
        origin = 0 if page_number == 0 else 0x4000
        for offset in range(len(page) - 1):
            if page[offset] != 0xED:
                continue
            decoded = _INDIRECT_IO_OPCODES.get(page[offset + 1])
            if decoded is None:
                continue
            direction, form = decoded
            candidates.append(
                RawIndirectIO(
                    RomLocation(page_number, origin + offset),
                    page[offset : offset + 2],
                    direction,
                    form,
                )
            )
    return tuple(candidates)


def raw_indirect_io_boundary_prefixes(
    rom: RomImage, pages: Iterable[int] | None = None
) -> tuple[RomLocation, ...]:
    """Return page-ending ``ED`` bytes whose following mapped byte is unknown."""

    selected_pages = range(rom.page_count) if pages is None else tuple(pages)
    locations = []
    for page_number in selected_pages:
        if not 0 <= page_number < rom.page_count:
            raise ValueError(f"page 0x{page_number:X} is outside this ROM")
        page = rom.page(page_number)
        if page[-1] == 0xED:
            address = 0x3FFF if page_number == 0 else 0x7FFF
            locations.append(RomLocation(page_number, address))
    return tuple(locations)


def _literal_operand(operand: str) -> int | None:
    match = _HEX_OPERAND_RE.fullmatch(operand.strip())
    return int(match.group(1), 16) if match else None


def _next_c_value(instruction: Z80Instruction, current: int | None) -> int | None:
    """Conservatively propagate C across one straight-line instruction."""

    mnemonic = instruction.mnemonic
    operands = tuple(part.strip() for part in instruction.operands.split(","))

    if mnemonic == "ld" and len(operands) == 2:
        destination, source = operands
        literal = _literal_operand(source)
        if destination == "c":
            return literal & 0xFF if literal is not None else None
        if destination == "bc":
            return literal & 0xFF if literal is not None else None

    if mnemonic in {"inc", "dec"} and operands and operands[0] in {"c", "bc"}:
        if current is None:
            return None
        delta = 1 if mnemonic == "inc" else -1
        return (current + delta) & 0xFF
    if mnemonic == "pop" and operands and operands[0] == "bc":
        return None
    if mnemonic == "exx":
        return None
    if mnemonic == "in" and operands and operands[0] == "c":
        return None
    if mnemonic in {"ldi", "ldir", "ldd", "lddr", "cpi", "cpir", "cpd", "cpdr"}:
        return None
    if (
        mnemonic in {"rlc", "rrc", "rl", "rr", "sla", "sra", "sll", "srl", "res", "set"}
        and operands
        and operands[-1] == "c"
    ):
        return None

    # Calls can clobber C.  Branches split linear disassembly into paths, so a
    # value seen before one cannot safely describe the following bytes.
    if mnemonic in {
        "call",
        "rst",
        "jp",
        "jr",
        "djnz",
        "ret",
        "reti",
        "retn",
    }:
        return None
    return current


def iter_resolved_io_accesses(
    instructions: Iterable[Z80Instruction], ports: Iterable[int] | None = None
) -> Iterator[DirectIOAccess]:
    """Yield immediate and conservatively resolved C-register I/O accesses.

    The helper is a candidate generator for linear disassembly.  It deliberately
    forgets C at every control-flow boundary and potential C write rather than
    guessing across paths or calls.
    """

    wanted = frozenset(ports) if ports is not None else None
    c_value: int | None = None
    for instruction in instructions:
        access = direct_io_access(instruction)
        if access is None and instruction.mnemonic in {"in", "out"}:
            if c_value is not None and _INDIRECT_C_RE.search(instruction.operands):
                access = DirectIOAccess(
                    instruction=instruction,
                    direction=instruction.mnemonic,
                    port=c_value,
                    source="register-c",
                )
        elif (
            access is None
            and instruction.mnemonic in _BLOCK_IO_DIRECTIONS
            and c_value is not None
        ):
            access = DirectIOAccess(
                instruction=instruction,
                direction=_BLOCK_IO_DIRECTIONS[instruction.mnemonic],
                port=c_value,
                source="register-c",
            )
        if access is not None and (wanted is None or access.port in wanted):
            yield access
        c_value = _next_c_value(instruction, c_value)


def parse_port_specs(specs: Iterable[str]) -> frozenset[int]:
    """Parse comma-separated ports and inclusive ranges accepted by I/O CLIs."""

    ports: set[int] = set()
    for spec in specs:
        for field in spec.split(","):
            field = field.strip()
            if not field:
                raise ValueError("empty port selector")
            bounds = field.split("-", 1)
            try:
                first = int(bounds[0], 0)
                last = int(bounds[1], 0) if len(bounds) == 2 else first
            except ValueError as error:
                raise ValueError(f"invalid port selector: {field!r}") from error
            if not 0 <= first <= 0xFF or not 0 <= last <= 0xFF:
                raise ValueError(f"port selector is outside 0x00-0xFF: {field!r}")
            if last < first:
                raise ValueError(f"descending port range: {field!r}")
            ports.update(range(first, last + 1))
    return frozenset(ports)
