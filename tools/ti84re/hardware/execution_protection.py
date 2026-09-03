"""Reusable models of TI-84 Plus execution-protection registers.

The retail ROM establishes the register values represented by
``TI84P_BOOT_PROTECTION``.  The execution predicates in this module model
specific emulator implementations; they do not assert unmeasured ASIC
behavior.
"""

from __future__ import annotations

from dataclasses import dataclass


CHUNK_SIZE = 0x400
PAGE_SIZE = 0x4000
TI84P_RAM_PAGES = 8
WABBITEMU_BOUNDARY_PORTS = frozenset(range(0x22, 0x27))


def _byte(value: int, name: str) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be a byte")
    return value


def _mode(value: int) -> int:
    if not 0 <= value <= 3:
        raise ValueError("RAM execution mode must be between 0 and 3")
    return value


def _address(value: int) -> int:
    if value < 0:
        raise ValueError("RAM address must be nonnegative")
    return value


def _word(value: int, name: str) -> int:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"{name} must be a 16-bit unsigned value")
    return value


@dataclass(frozen=True)
class ExecutionProtectionRegisters:
    """Values written to the five TI-84 Plus protection registers."""

    port21: int
    flash_lower: int
    flash_upper: int
    ram_lower_chunk: int
    ram_upper_chunk: int

    def __post_init__(self) -> None:
        _byte(self.port21, "port 0x21")
        _byte(self.flash_lower, "port 0x22")
        _byte(self.flash_upper, "port 0x23")
        _byte(self.ram_lower_chunk, "port 0x25")
        _byte(self.ram_upper_chunk, "port 0x26")

    @property
    def ram_mode(self) -> int:
        return (self.port21 >> 4) & 3


TI84P_BOOT_PROTECTION = ExecutionProtectionRegisters(
    port21=0x00,
    flash_lower=0x08,
    flash_upper=0x29,
    ram_lower_chunk=0x10,
    ram_upper_chunk=0x20,
)


@dataclass
class WabbitemuProtectionPortModel:
    """Model Wabbitemu's registered port-``0x22``–``0x26`` handlers."""

    flash_locked: bool = True
    flash_lower: int = 0x0010
    flash_upper: int = 0x0030
    port24: int = 0x00
    ram_lower: int = 0x0000
    ram_upper: int = 0x03FF

    def __post_init__(self) -> None:
        self.flash_lower = _word(self.flash_lower, "lower Flash field")
        self.flash_upper = _word(self.flash_upper, "upper Flash field")
        self.port24 = _byte(self.port24, "port 0x24")
        self.ram_lower = _word(self.ram_lower, "lower RAM field")
        self.ram_upper = _word(self.ram_upper, "upper RAM field")

    def write_port(self, port: int, value: int) -> bool:
        """Apply one device-layer write and return whether it was accepted."""

        if port not in WABBITEMU_BOUNDARY_PORTS:
            return False
        value = _byte(value, f"port 0x{port:02X}")
        if self.flash_locked:
            return False
        if port == 0x22:
            self.flash_lower = (self.flash_lower & 0xFF00) | value
        elif port == 0x23:
            self.flash_upper = (self.flash_upper & 0xFF00) | value
        elif port == 0x24:
            self.port24 = value
            # Match Wabbitemu's parsed C expressions.  Shift binds before
            # bitwise AND, so an eight-bit bus is masked with 0x100.
            self.flash_upper = (self.flash_upper & 0x00FF) | (value & 0x100)
            self.flash_lower = (self.flash_lower & 0x00FF) | (value & 0x100)
        elif port == 0x25:
            self.ram_lower = (value * CHUNK_SIZE) & 0xFFFF
        else:
            self.ram_upper = (value * CHUNK_SIZE + CHUNK_SIZE - 1) & 0xFFFF
        return True

    def read_port(self, port: int) -> int | None:
        """Return one handler readback, or ``None`` for an unrelated port."""

        if port == 0x22:
            return self.flash_lower & 0xFF
        if port == 0x23:
            return self.flash_upper & 0xFF
        if port == 0x24:
            return self.port24
        if port == 0x25:
            return (self.ram_lower // CHUNK_SIZE) & 0xFF
        if port == 0x26:
            return ((self.ram_upper - (CHUNK_SIZE - 1)) // CHUNK_SIZE) & 0xFF
        return None


@dataclass(frozen=True)
class RamPageCoverage:
    """Executable 1 KiB chunks within one physical 16 KiB RAM page."""

    physical_page: int
    executable_chunks: tuple[int, ...]

    @property
    def selector_page(self) -> int:
        """Return the ordinary port-selector spelling for this RAM page."""

        return 0x80 | self.physical_page

    @property
    def fully_executable(self) -> bool:
        return len(self.executable_chunks) == PAGE_SIZE // CHUNK_SIZE

    @property
    def partly_executable(self) -> bool:
        return bool(self.executable_chunks) and not self.fully_executable


def tilem_flash_execution_allowed(page: int, lower: int, upper: int) -> bool:
    """Model TilEm x4's inclusive forbidden Flash-page interval."""

    page = _byte(page, "Flash page")
    lower = _byte(lower, "lower Flash bound")
    upper = _byte(upper, "upper Flash bound")
    return not lower <= page <= upper


def wabbitemu_flash_execution_allowed(page: int, lower: int, upper: int) -> bool:
    """Model Wabbitemu's lower-exclusive, upper-inclusive Flash interval."""

    page = _byte(page, "Flash page")
    lower = _byte(lower, "lower Flash bound")
    upper = _byte(upper, "upper Flash bound")
    return page <= lower or page > upper


def tilem_ram_mask(mode: int) -> int:
    """Return TilEm x4's repeating address mask for a port-``0x21`` mode."""

    return (0x8000 << _mode(mode)) - CHUNK_SIZE


def tilem_masked_ram_chunk(address: int, mode: int) -> int:
    """Return the 1 KiB chunk address compared with ports ``0x25``/``0x26``."""

    return _address(address) & tilem_ram_mask(mode)


def tilem_ram_execution_allowed(
    address: int,
    mode: int,
    lower_chunk: int,
    upper_chunk: int,
) -> bool:
    """Model TilEm x4's inclusive RAM-chunk interval for one physical address."""

    lower = _byte(lower_chunk, "lower RAM chunk") * CHUNK_SIZE
    upper = _byte(upper_chunk, "upper RAM chunk") * CHUNK_SIZE
    masked = tilem_masked_ram_chunk(address, mode)
    return lower <= masked <= upper


def tilem_ram_page_coverage(
    mode: int,
    lower_chunk: int,
    upper_chunk: int,
    *,
    ram_pages: int = TI84P_RAM_PAGES,
) -> tuple[RamPageCoverage, ...]:
    """Enumerate TilEm's executable chunks across physical RAM pages."""

    _mode(mode)
    _byte(lower_chunk, "lower RAM chunk")
    _byte(upper_chunk, "upper RAM chunk")
    if ram_pages <= 0:
        raise ValueError("RAM page count must be positive")

    coverage = []
    for page in range(ram_pages):
        chunks = tuple(
            chunk
            for chunk in range(PAGE_SIZE // CHUNK_SIZE)
            if tilem_ram_execution_allowed(
                page * PAGE_SIZE + chunk * CHUNK_SIZE,
                mode,
                lower_chunk,
                upper_chunk,
            )
        )
        coverage.append(RamPageCoverage(page, chunks))
    return tuple(coverage)


def wabbitemu_ram_execution_allowed(
    physical_page: int,
    page_offset: int,
    mode: int,
    lower_chunk: int,
    upper_chunk: int,
) -> bool:
    """Model Wabbitemu's RAM predicate without ports ``0x27``/``0x28`` overlays.

    Wabbitemu first applies its page shortcut and then compares an unmasked
    physical address with the inclusive chunk bounds.  This function preserves
    that implementation, including its zero-valued shortcut in modes 1-3.
    """

    if physical_page < 0:
        raise ValueError("physical RAM page must be nonnegative")
    if not 0 <= page_offset < PAGE_SIZE:
        raise ValueError("RAM page offset must be between 0 and 0x3FFF")
    mode = _mode(mode)
    # Wabbitemu stores both byte-scaled results in unsigned-short fields.
    # Preserve the resulting 16-bit wrap for high custom port values.
    lower = (_byte(lower_chunk, "lower RAM chunk") * CHUNK_SIZE) & 0xFFFF
    upper = (
        _byte(upper_chunk, "upper RAM chunk") * CHUNK_SIZE + CHUNK_SIZE - 1
    ) & 0xFFFF

    if physical_page & (2 >> (mode + 1)):
        return True
    address = physical_page * PAGE_SIZE + page_offset
    return lower <= address <= upper


def wabbitemu_ram_page_coverage(
    mode: int,
    lower_chunk: int,
    upper_chunk: int,
    *,
    ram_pages: int = TI84P_RAM_PAGES,
) -> tuple[RamPageCoverage, ...]:
    """Enumerate Wabbitemu's executable chunks without forced overlays."""

    _mode(mode)
    _byte(lower_chunk, "lower RAM chunk")
    _byte(upper_chunk, "upper RAM chunk")
    if ram_pages <= 0:
        raise ValueError("RAM page count must be positive")

    return tuple(
        RamPageCoverage(
            page,
            tuple(
                chunk
                for chunk in range(PAGE_SIZE // CHUNK_SIZE)
                if wabbitemu_ram_execution_allowed(
                    page,
                    chunk * CHUNK_SIZE,
                    mode,
                    lower_chunk,
                    upper_chunk,
                )
            ),
        )
        for page in range(ram_pages)
    )
