"""Build explicit synthetic archive-sector layouts for GC experiments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from flash_hardware import FLASH_SIZE


ARCHIVE_FIRST_PAGE = 0x08
ARCHIVE_LAST_SECTOR_PAGE = 0x28
ARCHIVE_SECTOR_PAGE_SPAN = 4
GC_SECTOR_STATES = frozenset((0xFE, 0xFC, 0xF8, 0xF0))


class GcLayoutError(ValueError):
    """A requested synthetic layout would obscure or corrupt its input state."""


@dataclass(frozen=True)
class SectorHeaderMutation:
    """One controlled archive-sector header replacement."""

    page: int
    address: int
    previous: int
    value: int


@dataclass(frozen=True)
class GcLayoutResult:
    """A synthetic image and the complete list of controlled mutations."""

    image: bytes
    mutations: tuple[SectorHeaderMutation, ...]


def archive_sector_address(page: int) -> int:
    """Return the physical header address for an aligned archive-sector page."""

    if not ARCHIVE_FIRST_PAGE <= page <= ARCHIVE_LAST_SECTOR_PAGE:
        raise GcLayoutError(
            f"archive-sector page must be 0x{ARCHIVE_FIRST_PAGE:02X}–"
            f"0x{ARCHIVE_LAST_SECTOR_PAGE:02X}, got 0x{page:X}"
        )
    if page % ARCHIVE_SECTOR_PAGE_SPAN:
        raise GcLayoutError(
            f"archive-sector page must be four-page aligned, got 0x{page:02X}"
        )
    return page * 0x4000


def build_gc_sector_layout(
    source: bytes,
    headers: Iterable[tuple[int, int]],
    *,
    require_erased: bool = True,
) -> GcLayoutResult:
    """Replace selected archive-sector headers in a copy of ``source``.

    The operation is deliberately synthetic: it does not claim that the bytes
    were produced by a calculator. By default, every selected header must be
    erased so the builder cannot silently discard an existing archive state.
    """

    if len(source) != FLASH_SIZE:
        raise GcLayoutError(
            f"Flash image must contain 0x{FLASH_SIZE:X} bytes, got 0x{len(source):X}"
        )
    requested = tuple(headers)
    if not requested:
        raise GcLayoutError("at least one sector header is required")
    image = bytearray(source)
    mutations = []
    seen_pages = set()
    for page, value in requested:
        if page in seen_pages:
            raise GcLayoutError(f"duplicate archive-sector page 0x{page:02X}")
        seen_pages.add(page)
        address = archive_sector_address(page)
        if value not in GC_SECTOR_STATES:
            allowed = ", ".join(f"0x{state:02X}" for state in sorted(GC_SECTOR_STATES))
            raise GcLayoutError(
                f"sector header must be one of {allowed}, got 0x{value:X}"
            )
        previous = image[address]
        if require_erased and previous != 0xFF:
            raise GcLayoutError(
                f"page 0x{page:02X} header is 0x{previous:02X}, not erased"
            )
        image[address] = value
        mutations.append(
            SectorHeaderMutation(
                page=page,
                address=address,
                previous=previous,
                value=value,
            )
        )
    return GcLayoutResult(bytes(image), tuple(mutations))
