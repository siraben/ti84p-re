"""Parse project-local Z80 I/O-port labels."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PortDefinitionError(ValueError):
    """A port-label row is malformed or duplicates another row."""


@dataclass(frozen=True)
class PortDefinition:
    """One 8-bit I/O port and its project-local symbol."""

    port: int
    name: str


def parse_port_definitions(
    text: str, *, source: str = "<ports>"
) -> dict[int, PortDefinition]:
    """Parse hexadecimal ``PORT NAME`` rows with strict uniqueness."""

    definitions: dict[int, PortDefinition] = {}
    names: dict[str, int] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.partition("#")[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 2:
            raise PortDefinitionError(
                f"{source}:{line_number}: expected hexadecimal port and symbol"
            )
        port_text, name = fields
        try:
            port = int(port_text, 16)
        except ValueError as error:
            raise PortDefinitionError(
                f"{source}:{line_number}: invalid hexadecimal port {port_text!r}"
            ) from error
        if not 0 <= port <= 0xFF:
            raise PortDefinitionError(
                f"{source}:{line_number}: port is outside 00-FF: {port_text!r}"
            )
        if not name.isidentifier():
            raise PortDefinitionError(
                f"{source}:{line_number}: invalid symbol {name!r}"
            )
        if port in definitions:
            raise PortDefinitionError(
                f"{source}:{line_number}: duplicate port 0x{port:02X}"
            )
        if name in names:
            raise PortDefinitionError(
                f"{source}:{line_number}: duplicate symbol {name!r} "
                f"for ports 0x{names[name]:02X} and 0x{port:02X}"
            )
        definition = PortDefinition(port, name)
        definitions[port] = definition
        names[name] = port
    return definitions


def load_port_definitions(path: Path) -> dict[int, PortDefinition]:
    """Read and parse one port-label file."""

    return parse_port_definitions(path.read_text(encoding="utf-8"), source=str(path))
