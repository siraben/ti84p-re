"""Static Z80 I/O-access helpers for linear ROM disassembly.

Immediate-port instructions encode their port in the instruction.  The Z80's
``IN r,(C)`` and ``OUT (C),r`` forms instead take the low port byte from C.
This module resolves the latter only while a literal C value remains visible
within one straight-line instruction sequence.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Iterator

from z80_disassembly import Z80Instruction


_DIRECT_PORT_RE = re.compile(r"\(([0-9A-Fa-f]+)h\)")
_INDIRECT_C_RE = re.compile(r"\(c\)")
_HEX_OPERAND_RE = re.compile(r"^0*([0-9A-Fa-f]+)h$")


@dataclass(frozen=True)
class DirectIOAccess:
    """One immediate-port ``IN`` or ``OUT`` instruction."""

    instruction: Z80Instruction
    direction: str
    port: int
    source: str = "immediate"


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
        return None
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
