"""Reusable linear Z80 disassembly and literal-search helpers.

The repository's Nix development shell supplies ``z80dasm``.  This module
keeps process invocation and output parsing out of subsystem-specific scripts.
Linear disassembly is intentionally a candidate generator: ROM data tables can
decode as instructions, so callers must confirm control flow from raw bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Iterable, Iterator, Sequence

from rom_image import RomImage, RomLocation


_LINE_RE = re.compile(
    r"^\s*(?P<text>.*?)\s*;(?P<address>[0-9A-Fa-f]{4})\s+"
    r"(?P<bytes>(?:[0-9A-Fa-f]{2}(?:\s+|$))+ )?",
    re.VERBOSE,
)
_HEX_RE = re.compile(r"(?<![0-9A-Za-z_])0*([0-9A-Fa-f]+)h(?![0-9A-Za-z_])")


class DisassemblyError(RuntimeError):
    """``z80dasm`` was missing or rejected a page."""


@dataclass(frozen=True)
class Z80Instruction:
    """One instruction parsed from ``z80dasm -a -t`` output."""

    location: RomLocation
    data: bytes
    text: str

    @property
    def mnemonic(self) -> str:
        return self.text.split(None, 1)[0].lower()

    @property
    def operands(self) -> str:
        fields = self.text.split(None, 1)
        return fields[1].lower() if len(fields) == 2 else ""

    @property
    def end_address(self) -> int:
        return self.location.address + len(self.data)


@dataclass(frozen=True)
class LiteralUse:
    """An instruction whose rendered operands contain a requested integer."""

    instruction: Z80Instruction
    values: tuple[int, ...]


@dataclass(frozen=True)
class BcallSite:
    """A raw ``rst 28h`` followed by a requested 16-bit bcall ID."""

    location: RomLocation
    id: int


@dataclass(frozen=True)
class BjumpSite:
    """A raw cross-page jump descriptor following ``CALL 2B09h``."""

    location: RomLocation
    target: RomLocation
    raw_page: int


def parse_z80dasm(text: str, page: int) -> Iterator[Z80Instruction]:
    """Parse the stable address/byte comments emitted by ``z80dasm`` 1.2."""

    for line in text.splitlines():
        match = _LINE_RE.match(line)
        if not match:
            continue
        byte_text = match.group("bytes")
        if not byte_text:
            continue
        yield Z80Instruction(
            location=RomLocation(page, int(match.group("address"), 16)),
            data=bytes.fromhex(byte_text),
            text=match.group("text").strip(),
        )


def disassemble_page(
    rom: RomImage,
    page: int,
    *,
    executable: str = "z80dasm",
    origin: int | None = None,
) -> tuple[Z80Instruction, ...]:
    """Linearly disassemble one physical page with the repository toolchain."""

    if origin is None:
        origin = 0 if page == 0 else 0x4000
    with tempfile.NamedTemporaryFile(prefix=f"ti84-page-{page:02x}-") as fp:
        fp.write(rom.page(page))
        fp.flush()
        command = [executable, "-a", "-t", "-g", f"0x{origin:X}", fp.name]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as error:
            raise DisassemblyError(
                f"{executable!r} was not found; run this CLI through `nix develop -c`"
            ) from error
    if result.returncode:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise DisassemblyError(f"{executable} failed for page 0x{page:02X}: {detail}")
    return tuple(parse_z80dasm(result.stdout, page))


def disassemble_rom(
    rom: RomImage, *, executable: str = "z80dasm"
) -> Iterator[tuple[int, tuple[Z80Instruction, ...]]]:
    """Yield linear disassembly for every physical page in page order."""

    for page in range(rom.page_count):
        yield page, disassemble_page(rom, page, executable=executable)


def instruction_literals(instruction: Z80Instruction) -> tuple[int, ...]:
    """Return hexadecimal integer operands, excluding addresses in comments."""

    return tuple(int(match.group(1), 16) for match in _HEX_RE.finditer(instruction.operands))


def find_literal_uses(
    instructions: Iterable[Z80Instruction], values: Iterable[int]
) -> Iterator[LiteralUse]:
    """Yield linear-disassembly candidates containing any requested value."""

    requested = frozenset(values)
    for instruction in instructions:
        matches = tuple(
            value for value in instruction_literals(instruction) if value in requested
        )
        if matches:
            yield LiteralUse(instruction, matches)


def find_bcall_sites(
    rom: RomImage, page: int, ids: Iterable[int]
) -> Iterator[BcallSite]:
    """Yield raw bcall-sequence candidates from one physical page."""

    wanted = frozenset(ids)
    data = rom.page(page)
    origin = 0 if page == 0 else 0x4000
    for offset in range(len(data) - 2):
        if data[offset] != 0xEF:
            continue
        id_value = int.from_bytes(data[offset + 1 : offset + 3], "little")
        if id_value in wanted:
            yield BcallSite(RomLocation(page, origin + offset), id_value)


def find_bjump_sites(
    rom: RomImage,
    page: int,
    targets: Iterable[RomLocation] | None = None,
    *,
    trampoline: int = 0x2B09,
) -> Iterator[BjumpSite]:
    """Yield raw ``CALL trampoline; .dw address; .db page`` candidates.

    The dispatcher masks the inline page byte to six bits on this ROM, so
    requested targets use physical-page values while each report retains the
    original descriptor byte.
    """

    wanted = (
        None
        if targets is None
        else {(target.page, target.address) for target in targets}
    )
    data = rom.page(page)
    origin = 0 if page == 0 else 0x4000
    call_prefix = bytes((0xCD, trampoline & 0xFF, trampoline >> 8))
    for offset in range(len(data) - 5):
        if data[offset : offset + 3] != call_prefix:
            continue
        address = int.from_bytes(data[offset + 3 : offset + 5], "little")
        raw_page = data[offset + 5]
        target = (raw_page & 0x3F, address)
        if wanted is not None and target not in wanted:
            continue
        yield BjumpSite(
            location=RomLocation(page, origin + offset),
            target=RomLocation(*target),
            raw_page=raw_page,
        )


def direct_target(instruction: Z80Instruction) -> int | None:
    """Return the absolute target of a direct CALL or JP instruction."""

    if instruction.mnemonic not in {"call", "jp"}:
        return None
    # Conditional forms render as ``nz,02799h``; the address is last.
    matches = tuple(_HEX_RE.finditer(instruction.operands))
    return int(matches[-1].group(1), 16) if matches else None


def nearby_direct_sinks(
    instructions: Sequence[Z80Instruction],
    index: int,
    sinks: Iterable[int],
    *,
    distance: int,
) -> tuple[Z80Instruction, ...]:
    """Find direct CALL/JP sinks within a symmetric instruction window.

    Proximity is not a data-flow claim.  It is printed to make manual review of
    literal candidates faster.
    """

    wanted = frozenset(sinks)
    start = max(0, index - distance)
    stop = min(len(instructions), index + distance + 1)
    return tuple(
        instruction
        for instruction in instructions[start:stop]
        if direct_target(instruction) in wanted
    )
