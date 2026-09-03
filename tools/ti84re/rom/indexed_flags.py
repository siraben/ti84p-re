"""Raw, page-aware scans for Z80 indexed flag operations in TI ROM images.

The scanner finds exact ``DD CB d op`` and ``FD CB d op`` byte sequences whose
opcode updates or tests the indexed memory byte. It also finds immediate
``LD (IX/IY+d),n`` writes that replace a complete flag byte. Results are
candidates until the surrounding bytes are confirmed as reachable code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ti84re.rom.image import RomImage, RomLocation


@dataclass(frozen=True)
class IndexedBitReference:
    """One memory-only BIT, RES, or SET operation using IX or IY."""

    location: RomLocation
    index_register: str
    displacement: int
    operation: str
    bit: int
    data: bytes


@dataclass(frozen=True)
class IndexedImmediateWrite:
    """One immediate write that replaces an indexed memory byte."""

    location: RomLocation
    index_register: str
    displacement: int
    value: int
    data: bytes


def normalize_displacement(value: int) -> int:
    """Normalize a signed value or raw displacement byte to -128 through 127."""

    if not -128 <= value <= 0xFF:
        raise ValueError("indexed displacement must be -128 through 255")
    return value - 0x100 if value >= 0x80 else value


def scan_indexed_bit_references(
    rom: RomImage,
    *,
    displacement: int | None = None,
    bit: int | None = None,
    index_register: str | None = None,
    pages: Iterable[int] | None = None,
) -> tuple[IndexedBitReference, ...]:
    """Find raw memory-only indexed bit operations in selected physical pages."""

    if displacement is not None:
        displacement = normalize_displacement(displacement)
    if bit is not None and not 0 <= bit <= 7:
        raise ValueError("bit must be between 0 and 7")
    if index_register is not None:
        index_register = index_register.casefold()
        if index_register not in {"ix", "iy"}:
            raise ValueError("index register must be IX or IY")

    selected_pages = tuple(range(rom.page_count) if pages is None else pages)
    for page in selected_pages:
        if not 0 <= page < rom.page_count:
            raise ValueError(f"physical page 0x{page:X} is outside this ROM")

    references = []
    for page in selected_pages:
        page_data = rom.page(page)
        origin = 0 if page == 0 else 0x4000
        for offset in range(len(page_data) - 3):
            prefix, cb, raw_displacement, opcode = page_data[offset : offset + 4]
            if prefix not in {0xDD, 0xFD} or cb != 0xCB:
                continue
            if not 0x40 <= opcode <= 0xFF or opcode & 0x07 != 0x06:
                continue
            register = "ix" if prefix == 0xDD else "iy"
            signed_displacement = normalize_displacement(raw_displacement)
            operation = ("bit", "res", "set")[(opcode - 0x40) // 0x40]
            bit_number = (opcode >> 3) & 0x07
            if index_register is not None and register != index_register:
                continue
            if displacement is not None and signed_displacement != displacement:
                continue
            if bit is not None and bit_number != bit:
                continue
            references.append(
                IndexedBitReference(
                    location=RomLocation(page, origin + offset),
                    index_register=register,
                    displacement=signed_displacement,
                    operation=operation,
                    bit=bit_number,
                    data=page_data[offset : offset + 4],
                )
            )
    return tuple(references)


def scan_indexed_immediate_writes(
    rom: RomImage,
    *,
    displacement: int | None = None,
    index_register: str | None = None,
    pages: Iterable[int] | None = None,
) -> tuple[IndexedImmediateWrite, ...]:
    """Find raw ``LD (IX/IY+d),n`` writes in selected physical pages."""

    if displacement is not None:
        displacement = normalize_displacement(displacement)
    if index_register is not None:
        index_register = index_register.casefold()
        if index_register not in {"ix", "iy"}:
            raise ValueError("index register must be IX or IY")

    selected_pages = tuple(range(rom.page_count) if pages is None else pages)
    for page in selected_pages:
        if not 0 <= page < rom.page_count:
            raise ValueError(f"physical page 0x{page:X} is outside this ROM")

    writes = []
    for page in selected_pages:
        page_data = rom.page(page)
        origin = 0 if page == 0 else 0x4000
        for offset in range(len(page_data) - 3):
            prefix, opcode, raw_displacement, value = page_data[offset : offset + 4]
            if prefix not in {0xDD, 0xFD} or opcode != 0x36:
                continue
            register = "ix" if prefix == 0xDD else "iy"
            signed_displacement = normalize_displacement(raw_displacement)
            if index_register is not None and register != index_register:
                continue
            if displacement is not None and signed_displacement != displacement:
                continue
            writes.append(
                IndexedImmediateWrite(
                    location=RomLocation(page, origin + offset),
                    index_register=register,
                    displacement=signed_displacement,
                    value=value,
                    data=page_data[offset : offset + 4],
                )
            )
    return tuple(writes)
