"""Reusable byte-complete comparison for Flash images and replay outputs."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class DifferenceRange:
    """One half-open contiguous range whose image bytes differ."""

    start: int
    end: int


@dataclass(frozen=True)
class FlashImageComparison:
    """Hashes and complete difference accounting for two equal-sized images."""

    size: int
    left_sha256: str
    right_sha256: str
    differing_bytes: int
    ranges: tuple[DifferenceRange, ...]
    page_counts: tuple[tuple[int, int], ...]

    @property
    def equal(self) -> bool:
        return self.differing_bytes == 0


def compare_flash_images(left: bytes, right: bytes) -> FlashImageComparison:
    """Compare every byte and group differences by range and 16 KiB page."""

    if len(left) != len(right):
        raise ValueError(
            f"image sizes differ: 0x{len(left):X} versus 0x{len(right):X}"
        )
    ranges: list[DifferenceRange] = []
    page_counts: dict[int, int] = {}
    differing_bytes = 0
    range_start = None
    previous = None
    for address, (left_byte, right_byte) in enumerate(zip(left, right)):
        if left_byte == right_byte:
            continue
        differing_bytes += 1
        page = address // 0x4000
        page_counts[page] = page_counts.get(page, 0) + 1
        if previous is None or address != previous + 1:
            if range_start is not None:
                ranges.append(DifferenceRange(range_start, previous + 1))
            range_start = address
        previous = address
    if range_start is not None:
        ranges.append(DifferenceRange(range_start, previous + 1))
    return FlashImageComparison(
        size=len(left),
        left_sha256=sha256(left).hexdigest(),
        right_sha256=sha256(right).hexdigest(),
        differing_bytes=differing_bytes,
        ranges=tuple(ranges),
        page_counts=tuple(sorted(page_counts.items())),
    )
