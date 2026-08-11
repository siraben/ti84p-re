"""Recognize privileged Flash-gate writes in a TI ROM image.

The ASIC recognizes fetched bytes around ``OUT (0x14),A``.  This module scans
raw ROM bytes rather than assigning instruction semantics to that recognizer.
It reports the four privilege-sequence spellings used by OS 2.55MP and keeps
any other immediate port-0x14 bytes separate as unclassified candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from rom_image import RomImage, RomLocation


PORT_14_WRITE = bytes.fromhex("D314")
PRIVILEGED_SUFFIX = bytes.fromhex("0000ED56F3D314")
UNLOCK_SEQUENCES = (
    bytes.fromhex("F53E01") + PRIVILEGED_SUFFIX,
    bytes.fromhex("F53E0100F3") + PRIVILEGED_SUFFIX,
)
LOCK_SEQUENCES = (
    bytes.fromhex("F5AF") + PRIVILEGED_SUFFIX,
    bytes.fromhex("F5AF00F3") + PRIVILEGED_SUFFIX,
)


@dataclass(frozen=True)
class FlashGateSequence:
    """One privileged byte sequence through its port-0x14 write."""

    kind: str
    requested_value: int
    start: RomLocation
    output: RomLocation
    data: bytes


@dataclass(frozen=True)
class FlashGateScan:
    """Recognized sequences and raw ``D3 14`` candidates outside them."""

    sequences: tuple[FlashGateSequence, ...]
    unclassified_candidates: tuple[RomLocation, ...]


def _locations_for_pattern(
    rom: RomImage,
    page: int,
    pattern: bytes,
    *,
    kind: str,
    requested_value: int,
) -> tuple[FlashGateSequence, ...]:
    page_data = rom.page(page)
    origin = 0 if page == 0 else 0x4000
    output_offset = pattern.index(PORT_14_WRITE)
    results = []
    start = 0
    while True:
        start = page_data.find(pattern, start)
        if start < 0:
            break
        results.append(
            FlashGateSequence(
                kind=kind,
                requested_value=requested_value,
                start=RomLocation(page, origin + start),
                output=RomLocation(page, origin + start + output_offset),
                data=pattern,
            )
        )
        start += 1
    return tuple(results)


def scan_flash_gate(
    rom: RomImage, pages: Iterable[int] | None = None
) -> FlashGateScan:
    """Scan physical pages for complete privileged sequences and other writes."""

    selected_pages = tuple(range(rom.page_count) if pages is None else pages)
    for page in selected_pages:
        if not 0 <= page < rom.page_count:
            raise ValueError(f"physical page 0x{page:X} is outside this ROM")

    sequences = []
    all_writes: set[RomLocation] = set()
    for page in selected_pages:
        page_data = rom.page(page)
        origin = 0 if page == 0 else 0x4000
        offset = 0
        while True:
            offset = page_data.find(PORT_14_WRITE, offset)
            if offset < 0:
                break
            all_writes.add(RomLocation(page, origin + offset))
            offset += 1
        for pattern in UNLOCK_SEQUENCES:
            sequences.extend(
                _locations_for_pattern(
                    rom,
                    page,
                    pattern,
                    kind="unlock",
                    requested_value=1,
                )
            )
        for pattern in LOCK_SEQUENCES:
            sequences.extend(
                _locations_for_pattern(
                    rom,
                    page,
                    pattern,
                    kind="lock",
                    requested_value=0,
                )
            )

    sequences.sort(key=lambda item: (item.output.page, item.output.address))
    recognized_writes = {sequence.output for sequence in sequences}
    return FlashGateScan(
        sequences=tuple(sequences),
        unclassified_candidates=tuple(
            sorted(
                all_writes - recognized_writes,
                key=lambda location: (location.page, location.address),
            )
        ),
    )
