"""Reusable TI-83 Plus-family memory-mapper model.

The model describes the documented selector arithmetic used by TilEm and
Wabbitemu.  It is also used to resolve TilEm traces, so forced RAM overlays are
applied in paired mode as TilEm applies them.  Physical-hardware behavior can
differ where the documentation and emulators disagree.
"""

from __future__ import annotations


PAGE_SIZE = 0x4000
MAPPING_PORTS = frozenset({0x04, 0x05, 0x06, 0x07, 0x0E, 0x0F, 0x27, 0x28})


class Ti83PlusMapper:
    """Track bank selectors and resolve TI-83 Plus-family logical addresses."""

    def __init__(
        self,
        *,
        flash_pages: int = 64,
        ram_pages: int = 8,
        initial_port4: int | None = None,
        initial_port5: int | None = None,
        initial_port6: int | None = None,
        initial_port7: int | None = None,
        initial_port0e: int | None = None,
        initial_port0f: int | None = None,
        initial_port27: int | None = None,
        initial_port28: int | None = None,
        overlays_in_paired_mode: bool = True,
    ) -> None:
        if flash_pages <= 0 or ram_pages <= 0:
            raise ValueError("page counts must be positive")
        self.flash_pages = flash_pages
        self.ram_pages = ram_pages
        self.overlays_in_paired_mode = overlays_in_paired_mode
        self.port4 = self._byte(initial_port4)
        self.bank_c = self._byte(initial_port5)  # port 5
        self.bank_a = self._byte(initial_port6)  # port 6
        self.bank_b = self._byte(initial_port7)  # port 7
        self.port0e = self._high_page_byte(initial_port0e)
        self.port0f = self._high_page_byte(initial_port0f)
        self.port27 = self._byte(initial_port27)
        self.port28 = self._byte(initial_port28)
        self.switches = 0

    @staticmethod
    def _byte(value: int | None) -> int | None:
        if value is None:
            return None
        if not 0 <= value <= 0xFF:
            raise ValueError("port values must be bytes")
        return value

    @classmethod
    def _high_page_byte(cls, value: int | None) -> int | None:
        value = cls._byte(value)
        return None if value is None else value & 0x03

    @classmethod
    def ti84p_reset(cls) -> "Ti83PlusMapper":
        """Return the mapping established by TilEm's TI-84 Plus reset path."""

        return cls(
            flash_pages=64,
            ram_pages=8,
            initial_port4=0x07,
            initial_port5=0x00,
            initial_port6=0x3F,
            initial_port7=0x3F,
            initial_port0e=0x00,
            initial_port0f=0x00,
            initial_port27=0x00,
            initial_port28=0x00,
        )

    def write_port(self, port: int, value: int | None) -> bool:
        """Apply one mapper-port write, including an unknown trace value.

        Return ``True`` when *port* belongs to the mapper and ``False`` for an
        unrelated port.  ``None`` invalidates the selected register, which is
        useful for traces whose block-output byte was not captured.
        """

        if port not in MAPPING_PORTS:
            return False
        if value is not None:
            value = self._byte(value)
        if port == 0x04:
            self.port4 = value
        elif port == 0x05:
            self.bank_c = value
        elif port == 0x06:
            self.bank_a = value
        elif port == 0x07:
            self.bank_b = value
        elif port == 0x0E:
            self.port0e = self._high_page_byte(value)
        elif port == 0x0F:
            self.port0f = self._high_page_byte(value)
        elif port == 0x27:
            self.port27 = value
        else:
            self.port28 = value
        self.switches += 1
        return True

    def _flash_page(self, port: int, value: int) -> int | None:
        high = self.port0e if port == 0x06 else self.port0f
        low = value & 0x7F
        if high is not None:
            return (low | (high << 7)) % self.flash_pages

        # High bits can be unknown yet irrelevant on smaller Flash devices.
        possible = {
            (low | (candidate << 7)) % self.flash_pages
            for candidate in range(4)
        }
        return possible.pop() if len(possible) == 1 else None

    def bank_page(
        self, port: int, value: int | None
    ) -> tuple[str | None, int | None]:
        """Decode a complete page selector into ``(kind, physical page)``."""

        if value is None:
            return None, None
        if port == 0x05:
            return "ram", 0x80 | ((value & 0x7F) % self.ram_pages)
        if value & 0x80:
            return "ram", 0x80 | ((value & 0x7F) % self.ram_pages)
        page = self._flash_page(port, value)
        return ("flash", page) if page is not None else (None, None)

    def mapped_page(self, region: int) -> tuple[str | None, int | None]:
        """Return the base mapping for one 16 KiB logical region."""

        if not 0 <= region <= 3:
            raise ValueError("region must be between 0 and 3")
        if region == 0:
            return "flash", 0
        if self.port4 is None:
            return None, None

        if self.port4 & 1:
            if region in (1, 2):
                kind, page = self.bank_page(0x06, self.bank_a)
                if page is None:
                    return None, None
                return kind, (page & ~1) | (region - 1)
            return self.bank_page(0x07, self.bank_b)

        if region == 1:
            return self.bank_page(0x06, self.bank_a)
        if region == 2:
            return self.bank_page(0x07, self.bank_b)
        return self.bank_page(0x05, self.bank_c)

    def _overlays_active(self) -> bool | None:
        if self.overlays_in_paired_mode:
            return True
        if self.port4 is None:
            return None
        return not bool(self.port4 & 1)

    def mapping_complete(self) -> bool:
        """Return whether every logical address can be resolved."""

        overlays_active = self._overlays_active()
        if overlays_active is None:
            return False
        overlays_known = not overlays_active or (
            self.port27 is not None and self.port28 is not None
        )
        return overlays_known and all(
            self.mapped_page(region)[1] is not None for region in (1, 2, 3)
        )

    def mapped_address(self, logical: int) -> tuple[str | None, int | None]:
        """Return ``(kind, page)`` after applying forced-RAM subranges."""

        if not 0 <= logical <= 0xFFFF:
            raise ValueError("logical address must be a 16-bit value")
        overlays_active = self._overlays_active()
        region = logical >> 14
        if overlays_active is None and region in (2, 3):
            return None, None
        if overlays_active and region == 2:
            if self.port28 is None:
                return None, None
            if logical < 0x8000 + 64 * self.port28:
                return "ram", 0x81
        elif overlays_active and region == 3:
            if self.port27 is None:
                return None, None
            if logical >= 0x10000 - 64 * self.port27:
                return "ram", 0x80
        return self.mapped_page(region)

    def resolve(
        self, logical: int
    ) -> tuple[str, int, int | None, int | None]:
        """Map a logical address to Ghidra space/address and flat ROM offset."""

        region = logical >> 14
        offset = logical & 0x3FFF
        if region == 0:
            return "ram", logical, logical, 0
        kind, page = self.mapped_address(logical)
        if page is None:
            return "page_??", PAGE_SIZE + offset, None, None
        if kind == "flash":
            return (
                f"page_{page:02X}",
                PAGE_SIZE + offset,
                page * PAGE_SIZE + offset,
                page,
            )
        return "ram", logical, None, None

    def forced_ranges(self) -> list[tuple[int, int, int]] | None:
        """Return inclusive forced-RAM ranges as ``(start, end, page)``."""

        active = self._overlays_active()
        if active is None or (active and (self.port27 is None or self.port28 is None)):
            return None
        if not active:
            return []
        ranges = []
        if self.port28:
            ranges.append((0x8000, 0x8000 + 64 * self.port28 - 1, 0x81))
        if self.port27:
            ranges.append((0x10000 - 64 * self.port27, 0xFFFF, 0x80))
        return ranges

    def register_values(self) -> dict[int, int | None]:
        """Return the mapper registers keyed by I/O-port number."""

        return {
            0x04: self.port4,
            0x05: self.bank_c,
            0x06: self.bank_a,
            0x07: self.bank_b,
            0x0E: self.port0e,
            0x0F: self.port0f,
            0x27: self.port27,
            0x28: self.port28,
        }
