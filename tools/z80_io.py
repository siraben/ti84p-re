"""Static Z80 I/O-access helpers for linear ROM disassembly."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Iterator

from z80_disassembly import Z80Instruction


_DIRECT_PORT_RE = re.compile(r"\(([0-9A-Fa-f]+)h\)")


@dataclass(frozen=True)
class DirectIOAccess:
    """One immediate-port ``IN`` or ``OUT`` instruction."""

    instruction: Z80Instruction
    direction: str
    port: int


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
