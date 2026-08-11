"""Reusable access to physical pages and logical addresses in a TI ROM image."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PAGE_SIZE = 0x4000


class RomFormatError(ValueError):
    """The ROM size or a requested location is invalid."""


@dataclass(frozen=True)
class RomLocation:
    """A physical flash page and a logical address within its 16 KiB window."""

    page: int
    address: int

    def __str__(self) -> str:
        return f"{self.page:02X}:{self.address:04X}"


class RomImage:
    """An immutable, page-aware TI-83+/84+ ROM image."""

    def __init__(self, data: bytes):
        if not data or len(data) % PAGE_SIZE:
            raise RomFormatError(
                f"ROM size must be a nonzero multiple of 0x{PAGE_SIZE:X}, "
                f"got 0x{len(data):X}"
            )
        self._data = data

    @classmethod
    def from_path(cls, path: Path) -> "RomImage":
        return cls(path.read_bytes())

    @property
    def page_count(self) -> int:
        return len(self._data) // PAGE_SIZE

    @property
    def data(self) -> bytes:
        return self._data

    def _page_start(self, page: int) -> int:
        if not 0 <= page < self.page_count:
            raise RomFormatError(
                f"physical page 0x{page:X} is outside 0x00–0x{self.page_count - 1:02X}"
            )
        return page * PAGE_SIZE

    def page(self, page: int) -> bytes:
        start = self._page_start(page)
        return self._data[start : start + PAGE_SIZE]

    def flat_offset(self, page: int, address: int) -> int:
        """Map a page and a `0000`–`7FFF` logical address to a file offset."""

        if not 0 <= address < 0x8000:
            raise RomFormatError(
                f"logical address must be in 0x0000–0x7FFF, got 0x{address:X}"
            )
        return self._page_start(page) + (address & (PAGE_SIZE - 1))

    def bytes_at(self, page: int, address: int, length: int) -> bytes:
        if length < 0:
            raise RomFormatError("length must be nonnegative")
        within_page = address & (PAGE_SIZE - 1)
        if within_page + length > PAGE_SIZE:
            raise RomFormatError(
                f"read at {page:02X}:{address:04X} crosses a physical-page boundary"
            )
        start = self.flat_offset(page, address)
        return self._data[start : start + length]

    def u16le(self, page: int, address: int) -> int:
        return int.from_bytes(self.bytes_at(page, address, 2), "little")
