"""Reusable TI-84 Plus Flash geometry and emulator-behavior models.

The geometry follows the one-megabyte top-boot device used by the calculator.
The emulator helpers reproduce specific source implementations.  They are test
oracles for those implementations, not claims about unmeasured hardware.
"""

from __future__ import annotations

from dataclasses import dataclass


FLASH_SIZE = 0x100000
PAGE_SIZE = 0x4000


def _byte(value: int, name: str) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be a byte")
    return value


@dataclass(frozen=True)
class FlashSector:
    """One physical erase sector in the top-boot Flash device."""

    start: int
    size: int

    @property
    def end(self) -> int:
        return self.start + self.size

    def contains(self, address: int) -> bool:
        return self.start <= address < self.end


TOP_BOOT_SECTORS = tuple(
    [FlashSector(start, 0x10000) for start in range(0, 0xF0000, 0x10000)]
    + [
        FlashSector(0xF0000, 0x8000),
        FlashSector(0xF8000, 0x2000),
        FlashSector(0xFA000, 0x2000),
        FlashSector(0xFC000, 0x4000),
    ]
)


def flash_sector(address: int) -> FlashSector:
    """Return the Am29LV800B top-boot sector containing *address*."""

    if not 0 <= address < FLASH_SIZE:
        raise ValueError(f"Flash address outside 1 MiB device: 0x{address:X}")
    for sector in TOP_BOOT_SECTORS:
        if sector.contains(address):
            return sector
    raise AssertionError("complete sector table did not contain Flash address")


@dataclass(frozen=True)
class EmulatorFlashProfile:
    """Source-level capabilities of one pinned emulator Flash path."""

    name: str
    revision: str
    program_rule: str
    program_completion: str
    erase_completion: str
    autoselect: str
    asic_write_gate: str
    driver_status: str


EMULATOR_PROFILES = (
    EmulatorFlashProfile(
        name="TilEm",
        revision="f56ad637d0524ee841dd381be6ecbaf5b8975600",
        program_rule="old & requested",
        program_completion="7-cycle busy model with DQ7/DQ6 status",
        erase_completion="200000-cycle busy model with DQ6/DQ2/DQ3 status",
        autoselect="not implemented",
        asic_write_gate="protected-byte recognizer, port 0x14 lock, sector groups",
        driver_status="TI-84 Plus model used for dynamic traces",
    ),
    EmulatorFlashProfile(
        name="Wabbitemu",
        revision="48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422",
        program_rule="old & requested",
        program_completion="immediate; one transient error read for 0-to-1 requests",
        erase_completion="immediate",
        autoselect="manufacturer 0x01, TI-84 Plus device 0xDA",
        asic_write_gate="privileged-page port 0x14 gate and boot-page model bits",
        driver_status="source model; no physical timing claim",
    ),
    EmulatorFlashProfile(
        name="MAME",
        revision="mame0287",
        program_rule="requested (assignment)",
        program_completion="immediate array read; no AMD program-busy status",
        erase_completion="data cleared immediately, then timed erase status",
        autoselect="manufacturer 0x01, device 0xDA",
        asic_write_gate="none; port 0x14 state does not gate mapped Flash writes",
        driver_status="TI-84 Plus driver is MACHINE_NOT_WORKING",
    ),
)


def emulator_profile(name: str) -> EmulatorFlashProfile:
    """Return a pinned profile by case-insensitive emulator name."""

    normalized = name.casefold()
    for profile in EMULATOR_PROFILES:
        if profile.name.casefold() == normalized:
            return profile
    choices = ", ".join(profile.name for profile in EMULATOR_PROFILES)
    raise ValueError(f"unknown emulator {name!r}; choose {choices}")


@dataclass(frozen=True)
class ProgramResult:
    """Result of one source-modeled byte-program operation."""

    emulator: str
    old: int
    requested: int
    stored: int
    requested_zero_to_one: bool
    poll_behavior: str


def program_byte(emulator: str, old: int, requested: int) -> ProgramResult:
    """Apply one emulator's byte-program mutation and summarize its poll path."""

    profile = emulator_profile(emulator)
    old = _byte(old, "old value")
    requested = _byte(requested, "requested value")
    zero_to_one = bool((~old & requested) & 0xFF)

    if profile.name in {"TilEm", "Wabbitemu"}:
        stored = old & requested
    else:
        stored = requested

    if profile.name == "TilEm":
        poll = "error state" if zero_to_one else "modeled busy then array data"
    elif profile.name == "Wabbitemu":
        poll = "one transient error-status read" if zero_to_one else "array data"
    else:
        poll = "array data"

    return ProgramResult(
        emulator=profile.name,
        old=old,
        requested=requested,
        stored=stored,
        requested_zero_to_one=zero_to_one,
        poll_behavior=poll,
    )


def wabbitemu_program_error_read(requested: int, *, dq6: bool = False) -> int:
    """Return Wabbitemu's single error read after an illegal program request."""

    requested = _byte(requested, "requested value")
    return ((~requested) & 0x80) | 0x20 | (0x40 if dq6 else 0)


def mame_erase_duration_ms(address: int) -> int:
    """Return MAME 0.287's timer duration for a sector erase."""

    sector = flash_sector(address)
    if sector.size == 0x10000:
        return 1000
    if sector.size == 0x2000:
        return 250
    return 500


def mame_erase_status_reads(count: int, *, initial_status: int = 0x08) -> tuple[int, ...]:
    """Return MAME's in-sector erase reads, which toggle DQ6 and DQ2."""

    if count < 0:
        raise ValueError("read count must be nonnegative")
    status = _byte(initial_status, "initial status")
    reads = []
    for _ in range(count):
        status ^= 0x44
        reads.append(status)
    return tuple(reads)


def mame_erase_busy_read_range(address: int) -> tuple[int, int]:
    """Return the observable busy-read range in MAME 0.287.

    The generic device always tests a 64 KiB interval starting at its recorded
    sector base, even when the erased top-boot sector is smaller.  The returned
    end is clipped to the device's address space.
    """

    sector = flash_sector(address)
    return sector.start, min(FLASH_SIZE, sector.start + 0x10000)


def rom_program_poll_decision(
    requested: int,
    first_read: int,
    *,
    dq5_read: int | None = None,
    final_read: int | None = None,
) -> str:
    """Evaluate the OS block worker's DQ7/DQ5 program-poll decision.

    Returns ``success``, ``need-dq5-read``, ``retry``, ``need-final-read``, or
    ``failure``.
    """

    requested = _byte(requested, "requested value")
    first_read = _byte(first_read, "first read")
    if not ((requested ^ first_read) & 0x80):
        return "success"
    if dq5_read is None:
        return "need-dq5-read"
    dq5_read = _byte(dq5_read, "DQ5 read")
    if not (dq5_read & 0x20):
        return "retry"
    if final_read is None:
        return "need-final-read"
    final_read = _byte(final_read, "final read")
    return "failure" if ((requested ^ final_read) & 0x80) else "success"
