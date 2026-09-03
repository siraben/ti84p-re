"""Classify ROM I/O candidates that overlap inline call descriptors."""

from __future__ import annotations

from dataclasses import dataclass

from ti84re.rom.image import RomImage, RomLocation


@dataclass(frozen=True)
class InlineDescriptor:
    """A bcall or bjump descriptor containing an apparent I/O instruction."""

    kind: str
    owner_location: str
    value: int
    target: str | None = None
    raw_page: int | None = None


def inline_descriptor_at(
    rom: RomImage, location: RomLocation
) -> InlineDescriptor | None:
    """Return the raw inline descriptor that overlaps *location*, if any.

    The result classifies bytes structurally. It does not prove that no
    alternate control-flow entry reaches the same byte as an instruction.
    """

    page = rom.page(location.page)
    origin = 0 if location.page == 0 else 0x4000
    offset = location.address - origin
    if not 0 <= offset < len(page):
        raise ValueError(f"location {location} is outside its physical page")

    for operand_index in (1, 2):
        owner = offset - operand_index
        if owner < 0 or owner + 3 > len(page) or page[owner] != 0xEF:
            continue
        bcall_id = int.from_bytes(page[owner + 1 : owner + 3], "little")
        return InlineDescriptor(
            kind="bcall-operand",
            owner_location=str(RomLocation(location.page, origin + owner)),
            value=bcall_id,
        )

    prefix = bytes.fromhex("CD092B")
    for descriptor_index in (3, 4, 5):
        owner = offset - descriptor_index
        if owner < 0 or owner + 6 > len(page):
            continue
        if page[owner : owner + 3] != prefix:
            continue
        address = int.from_bytes(page[owner + 3 : owner + 5], "little")
        raw_page = page[owner + 5]
        return InlineDescriptor(
            kind="bjump-descriptor",
            owner_location=str(RomLocation(location.page, origin + owner)),
            value=address,
            target=str(RomLocation(raw_page & 0x3F, address)),
            raw_page=raw_page,
        )
    return None
