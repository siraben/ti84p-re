"""Reusable TI-83 Plus-family memory-mapper models.

The profiles in this module reproduce pinned software implementations.  They
are comparison oracles, not claims about physical ASIC behavior.  The default
profile remains TilEm so existing trace-resolution callers keep their prior
semantics.
"""

from __future__ import annotations

from dataclasses import dataclass


PAGE_SIZE = 0x4000
MAPPING_PORTS = frozenset({0x04, 0x05, 0x06, 0x07, 0x0E, 0x0F, 0x27, 0x28})


@dataclass(frozen=True)
class MapperImplementationProfile:
    """One documented contract or pinned emulator implementation."""

    key: str
    name: str
    revision: str
    mapped_ports: frozenset[int]
    port5_write_mask: int | None
    flash_selector_mask: int | None
    accessible_ram_pages: int | None
    ram_selectors_wrap: bool
    extended_flash_selectors: bool
    paired_b_sets_low_bit: bool
    overlay_policy: str
    port27_minimum: int | None
    reset_registers: tuple[tuple[int, int], ...]
    reset_fixed_page: int
    reset_pc: int
    reset_latch: bool
    reset_entry: str
    driver_status: str
    known_limit: str


DOCUMENTED_PROFILE = MapperImplementationProfile(
    key="documented",
    name="Historical public contract",
    revision="WikiTI pages retrieved 2026-08-09",
    mapped_ports=MAPPING_PORTS,
    port5_write_mask=None,
    flash_selector_mask=None,
    accessible_ram_pages=None,
    ram_selectors_wrap=True,
    extended_flash_selectors=True,
    paired_b_sets_low_bit=True,
    overlay_policy="independent",
    port27_minimum=None,
    reset_registers=(),
    reset_fixed_page=0,
    reset_pc=0,
    reset_latch=False,
    reset_entry="No complete TI-84 Plus reset state is asserted by this profile.",
    driver_status="reference description; not a hardware implementation",
    known_limit="nonzero overlay behavior and reset state remain physically unverified",
)

TILEM_PROFILE = MapperImplementationProfile(
    key="tilem",
    name="TilEm",
    revision="f56ad637d0524ee841dd381be6ecbaf5b8975600",
    mapped_ports=MAPPING_PORTS,
    port5_write_mask=0x0F,
    flash_selector_mask=0x3F,
    accessible_ram_pages=None,
    ram_selectors_wrap=True,
    extended_flash_selectors=False,
    paired_b_sets_low_bit=True,
    overlay_policy="always",
    port27_minimum=None,
    reset_registers=(
        (0x04, 0x07),
        (0x05, 0x00),
        (0x06, 0x3F),
        (0x07, 0x3F),
        (0x0E, 0x00),
        (0x0F, 0x00),
        (0x27, 0x00),
        (0x28, 0x00),
    ),
    reset_fixed_page=0,
    reset_pc=0x8000,
    reset_latch=False,
    reset_entry="PC 0x8000; windows 0/A/B/C are Flash 00/3E/3F/3F.",
    driver_status="usable emulator mapper; fixed 64-Flash-page x4 model",
    known_limit="applies forced-RAM overlays even in paired mode",
)

WABBITEMU_PROFILE = MapperImplementationProfile(
    key="wabbitemu",
    name="Wabbitemu",
    revision="48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422",
    mapped_ports=MAPPING_PORTS,
    port5_write_mask=None,
    flash_selector_mask=None,
    accessible_ram_pages=None,
    ram_selectors_wrap=True,
    extended_flash_selectors=True,
    paired_b_sets_low_bit=False,
    overlay_policy="independent",
    port27_minimum=0xFB64,
    reset_registers=(
        (0x04, 0x00),
        (0x05, 0x00),
        (0x06, 0x00),
        (0x07, 0x00),
        (0x0E, 0x00),
        (0x0F, 0x00),
        (0x27, 0x00),
        (0x28, 0x00),
    ),
    reset_fixed_page=0x3F,
    reset_pc=0,
    reset_latch=True,
    reset_entry="PC 0; fixed window starts on Flash 3F until a qualifying opcode fetch.",
    driver_status="usable emulator mapper with implementation-specific quirks",
    known_limit=(
        "paired B fails to force an odd page; port 0x27 has an extra 0xFB64 cutoff"
    ),
)

MAME_PROFILE = MapperImplementationProfile(
    key="mame",
    name="MAME",
    revision="mame0287",
    mapped_ports=frozenset({0x04, 0x05, 0x06, 0x07}),
    port5_write_mask=0x07,
    flash_selector_mask=0x3F,
    accessible_ram_pages=7,
    ram_selectors_wrap=False,
    extended_flash_selectors=False,
    paired_b_sets_low_bit=True,
    overlay_policy="none",
    port27_minimum=None,
    reset_registers=((0x04, 0x01), (0x05, 0), (0x06, 0), (0x07, 0)),
    reset_fixed_page=0x3F,
    reset_pc=0,
    reset_latch=True,
    reset_entry="PC 0; fixed window is Flash 3F until MAME's bank-read latch clears.",
    driver_status="MACHINE_NOT_WORKING driver with incomplete ASIC I/O coverage",
    known_limit=(
        "ports 0x0E/0x0F/0x27/0x28 are absent; RAM selector 0x87 is outside "
        "the mapped backing range"
    ),
)

MAPPER_PROFILES = {
    profile.key: profile
    for profile in (
        DOCUMENTED_PROFILE,
        TILEM_PROFILE,
        WABBITEMU_PROFILE,
        MAME_PROFILE,
    )
}
EMULATOR_PROFILE_KEYS = ("tilem", "wabbitemu", "mame")


def mapper_profile(
    profile: str | MapperImplementationProfile,
) -> MapperImplementationProfile:
    """Resolve a profile key while accepting an already-resolved profile."""

    if isinstance(profile, MapperImplementationProfile):
        return profile
    try:
        return MAPPER_PROFILES[profile.lower()]
    except KeyError:
        choices = ", ".join(MAPPER_PROFILES)
        raise ValueError(f"unknown mapper profile {profile!r}; choose {choices}") from None


class Ti83PlusMapper:
    """Track selectors and resolve logical addresses under one profile."""

    def __init__(
        self,
        *,
        flash_pages: int = 64,
        ram_pages: int = 8,
        profile: str | MapperImplementationProfile = "tilem",
        initial_port4: int | None = None,
        initial_port5: int | None = None,
        initial_port6: int | None = None,
        initial_port7: int | None = None,
        initial_port0e: int | None = None,
        initial_port0f: int | None = None,
        initial_port27: int | None = None,
        initial_port28: int | None = None,
        initial_fixed_page: int = 0,
        initial_pc: int | None = None,
        initial_boot_latch: bool = False,
        ram_alias_from: int | None = None,
        overlays_in_paired_mode: bool | None = None,
    ) -> None:
        if flash_pages <= 0 or ram_pages <= 0:
            raise ValueError("page counts must be positive")
        if not 0 <= initial_fixed_page < flash_pages:
            raise ValueError("fixed page must exist in Flash")
        if initial_pc is not None and not 0 <= initial_pc <= 0xFFFF:
            raise ValueError("initial PC must be a 16-bit value")
        if ram_alias_from is not None and not 0 <= ram_alias_from < ram_pages:
            raise ValueError("RAM alias page must exist in RAM")
        self.flash_pages = flash_pages
        self.ram_pages = ram_pages
        self.profile = mapper_profile(profile)
        self.ram_alias_from = ram_alias_from
        self.overlays_in_paired_mode = overlays_in_paired_mode
        self.port4 = self._byte(initial_port4)
        self.bank_c = self._normalize_port_value(0x05, initial_port5)
        self.bank_a = self._normalize_port_value(0x06, initial_port6)
        self.bank_b = self._normalize_port_value(0x07, initial_port7)
        self.port0e = self._high_page_byte(initial_port0e)
        self.port0f = self._high_page_byte(initial_port0f)
        self.port27 = self._byte(initial_port27)
        self.port28 = self._byte(initial_port28)
        self.fixed_page = initial_fixed_page
        self.initial_pc = initial_pc
        self.boot_latch = initial_boot_latch
        self.switches = 0
        self.ignored_writes: list[tuple[int, int | None]] = []

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

    def _normalize_port_value(self, port: int, value: int | None) -> int | None:
        value = self._byte(value)
        if value is None:
            return None
        if port == 0x05 and self.profile.port5_write_mask is not None:
            return value & self.profile.port5_write_mask
        if (
            port in (0x06, 0x07)
            and self.profile.key == "mame"
            and value < 0x80
        ):
            return value & 0x3F
        return value

    @classmethod
    def ti84p_reset(
        cls,
        profile: str | MapperImplementationProfile = "tilem",
        *,
        ram_alias_from: int | None = None,
    ) -> "Ti83PlusMapper":
        """Return the TI-84 Plus reset state implemented by *profile*."""

        selected = mapper_profile(profile)
        if selected.key == "documented":
            raise ValueError("the documented profile has no verified reset preset")
        registers = dict(selected.reset_registers)
        return cls(
            flash_pages=64,
            ram_pages=8,
            profile=selected,
            initial_port4=registers.get(0x04),
            initial_port5=registers.get(0x05),
            initial_port6=registers.get(0x06),
            initial_port7=registers.get(0x07),
            initial_port0e=registers.get(0x0E),
            initial_port0f=registers.get(0x0F),
            initial_port27=registers.get(0x27),
            initial_port28=registers.get(0x28),
            initial_fixed_page=selected.reset_fixed_page,
            initial_pc=selected.reset_pc,
            initial_boot_latch=selected.reset_latch,
            ram_alias_from=ram_alias_from,
        )

    def write_port(self, port: int, value: int | None) -> bool:
        """Apply a mapped write and return whether the profile accepts it.

        ``None`` invalidates a register for incomplete instruction traces.
        Known mapper ports absent from a profile are recorded in
        :attr:`ignored_writes` and return ``False``.
        """

        if port not in MAPPING_PORTS:
            return False
        if value is not None:
            value = self._byte(value)
        if port not in self.profile.mapped_ports:
            self.ignored_writes.append((port, value))
            return False
        value = self._normalize_port_value(port, value)
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
        low = value & 0x7F
        if self.profile.flash_selector_mask is not None:
            return (low & self.profile.flash_selector_mask) % self.flash_pages
        high = self.port0e if port == 0x06 else self.port0f
        if self.profile.extended_flash_selectors and high is not None:
            return (low | (high << 7)) % self.flash_pages
        if not self.profile.extended_flash_selectors:
            return low % self.flash_pages

        # Unknown high bits can still be irrelevant on a smaller device.
        possible = {
            (low | (candidate << 7)) % self.flash_pages
            for candidate in range(4)
        }
        return possible.pop() if len(possible) == 1 else None

    def _selected_bank_page(
        self, port: int, value: int | None
    ) -> tuple[str | None, int | None]:
        """Decode a selector without resolving its physical backing."""

        if value is None:
            return None, None
        if port == 0x05:
            ram_page = value & 0x7F
            if self.profile.ram_selectors_wrap:
                ram_page %= self.ram_pages
            return "ram", 0x80 | ram_page
        if value & 0x80:
            ram_page = value & 0x7F
            if self.profile.ram_selectors_wrap:
                ram_page %= self.ram_pages
            return "ram", 0x80 | ram_page
        page = self._flash_page(port, value)
        return ("flash", page) if page is not None else (None, None)

    def bank_page(
        self, port: int, value: int | None
    ) -> tuple[str | None, int | None]:
        """Decode a selector and reject pages absent from profile backing."""

        kind, page = self._selected_bank_page(port, value)
        if page is None:
            return None, None
        return self._resolved_page(kind, page)

    def _resolved_page(
        self, kind: str | None, page: int
    ) -> tuple[str | None, int | None]:
        if kind != "ram":
            return kind, page
        ram_page = page & 0x7F
        if (
            self.profile.accessible_ram_pages is not None
            and ram_page >= self.profile.accessible_ram_pages
        ):
            return None, None
        if self.ram_alias_from is not None and ram_page >= self.ram_alias_from:
            ram_page = self.ram_alias_from
        return "ram", 0x80 | ram_page

    def mapped_page(self, region: int) -> tuple[str | None, int | None]:
        """Return the base mapping for one 16 KiB logical region."""

        if not 0 <= region <= 3:
            raise ValueError("region must be between 0 and 3")
        if region == 0:
            return "flash", self.fixed_page
        if self.port4 is None:
            return None, None

        if self.port4 & 1:
            if region in (1, 2):
                kind, page = self._selected_bank_page(0x06, self.bank_a)
                if page is None:
                    return None, None
                if region == 1:
                    paired_page = page & ~1
                    return self._resolved_page(kind, paired_page)
                if self.profile.paired_b_sets_low_bit:
                    paired_page = page | 1
                    return self._resolved_page(kind, paired_page)
                # Literal Wabbitemu expression: page | (!flash_version == 1).
                return self._resolved_page(kind, page)
            return self.bank_page(0x07, self.bank_b)

        if region == 1:
            return self.bank_page(0x06, self.bank_a)
        if region == 2:
            return self.bank_page(0x07, self.bank_b)
        return self.bank_page(0x05, self.bank_c)

    def _overlays_active(self) -> bool | None:
        if self.profile.overlay_policy == "none":
            return False
        if self.overlays_in_paired_mode is True:
            return True
        if self.port4 is None:
            return None
        if self.overlays_in_paired_mode is False:
            return not bool(self.port4 & 1)
        if self.profile.overlay_policy == "always":
            return True
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
            self.mapped_page(region)[1] is not None for region in range(4)
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
            start = 0x10000 - 64 * self.port27
            if self.profile.port27_minimum is not None:
                start = max(start, self.profile.port27_minimum)
            if logical >= start:
                return "ram", 0x80
        return self.mapped_page(region)

    def read_address(
        self, logical: int, *, opcode_fetch: bool = False
    ) -> tuple[str | None, int | None]:
        """Model mapper side effects of one read and return its mapped page.

        MAME clears its boot-page latch before reads from A, and before reads
        from B in paired mode.  Wabbitemu clears fixed page 3F only on a
        qualifying opcode fetch.  Other profiles have no mapper read effect.
        """

        if not 0 <= logical <= 0xFFFF:
            raise ValueError("logical address must be a 16-bit value")
        region = logical >> 14
        paired = self.port4 is not None and bool(self.port4 & 1)
        clear = False
        if self.boot_latch and self.profile.key == "mame":
            clear = region == 1 or (region == 2 and paired)
        elif self.boot_latch and self.profile.key == "wabbitemu" and opcode_fetch:
            if region == 1 or (region == 2 and paired):
                clear = self.mapped_page(region)[0] == "flash"
        if clear:
            self.fixed_page = 0
            self.boot_latch = False
        return self.mapped_address(logical)

    def resolve(
        self, logical: int
    ) -> tuple[str, int, int | None, int | None]:
        """Map a logical address to Ghidra space/address and flat ROM offset."""

        region = logical >> 14
        offset = logical & 0x3FFF
        kind, page = self.mapped_address(logical)
        if page is None:
            return "page_??", PAGE_SIZE + offset, None, None
        if kind == "flash":
            if region == 0 and page == 0:
                return "ram", logical, logical, 0
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
            start = 0x10000 - 64 * self.port27
            if self.profile.port27_minimum is not None:
                start = max(start, self.profile.port27_minimum)
            ranges.append((start, 0xFFFF, 0x80))
        return ranges

    def register_values(self, *, mapped_only: bool = False) -> dict[int, int | None]:
        """Return stored mapper registers keyed by I/O-port number."""

        values = {
            0x04: self.port4,
            0x05: self.bank_c,
            0x06: self.bank_a,
            0x07: self.bank_b,
            0x0E: self.port0e,
            0x0F: self.port0f,
            0x27: self.port27,
            0x28: self.port28,
        }
        if mapped_only:
            return {
                port: value
                for port, value in values.items()
                if port in self.profile.mapped_ports
            }
        return values

    @staticmethod
    def _selector_byte(kind: str | None, page: int | None) -> int | None:
        if kind is None or page is None:
            return None
        return page & 0x7F if kind == "flash" else 0x80 | (page & 0x7F)

    def read_port(self, port: int) -> int | None:
        """Return modeled readback, or ``None`` for status/unmapped reads."""

        if port not in self.profile.mapped_ports or port == 0x04:
            return None
        if self.profile.key == "wabbitemu" and port in (0x05, 0x06, 0x07):
            paired = self.port4 is not None and bool(self.port4 & 1)
            if paired and port == 0x05:
                kind, page = self._selected_bank_page(0x07, self.bank_b)
            elif paired and port in (0x06, 0x07):
                kind, page = self._selected_bank_page(0x06, self.bank_a)
                if page is not None and port == 0x06:
                    page &= ~1
            else:
                selector_port = {0x05: 0x05, 0x06: 0x06, 0x07: 0x07}[port]
                selector = {
                    0x05: self.bank_c,
                    0x06: self.bank_a,
                    0x07: self.bank_b,
                }[port]
                kind, page = self._selected_bank_page(selector_port, selector)
            if port == 0x05:
                return None if page is None else page & 0x7F
            return self._selector_byte(kind, page)
        return self.register_values()[port]
