"""Decode TI-84 Plus ASIC status, identity, protection, and GPIO operations.

The bit assignments in this module are mechanical decoders.  Their evidence
quality is deliberately left to callers: some names are established by the
retail ROM, while the identity and voltage tables come from public documents
or emulator implementations rather than physical measurements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

from execution_protection import tilem_ram_mask
from z80_disassembly import Z80Instruction
from z80_io import direct_io_access


GPIO_PORTS = frozenset({0x39, 0x3A})
TILEM_BATTERY_THRESHOLDS = (33, 39, 36, 43)
ASIC_CONTROL_PORTS = frozenset({0x02, 0x15, 0x21, 0x39, 0x3A})


def _byte(value: int) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError("register values must be bytes")
    return value


@dataclass(frozen=True)
class AsicImplementationProfile:
    """Pinned I/O coverage for the ASIC-control ports on this page."""

    key: str
    name: str
    revision: str
    mapped_ports: frozenset[int]
    fixed_port02_locked: int | None
    fixed_port15: int | None
    port21_read_policy: str
    gpio_policy: str
    driver_status: str


ASIC_IMPLEMENTATIONS = {
    profile.key: profile
    for profile in (
        AsicImplementationProfile(
            "tilem",
            "TilEm",
            "f56ad637d0524ee841dd381be6ecbaf5b8975600",
            frozenset({0x02, 0x15, 0x21, 0x39}),
            None,
            0x45,
            "accepted write masked with 0x33",
            "port 0x39 reads fixed 0xF0; port 0x3A has no TI-84 Plus model",
            "usable emulator with unmeasured battery thresholds",
        ),
        AsicImplementationProfile(
            "wabbitemu",
            "Wabbitemu",
            "48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422",
            frozenset({0x02, 0x15, 0x21, 0x3A}),
            None,
            None,
            "readback retains only written bits 0-1",
            "port 0x3A is a latch; port 0x39 is absent",
            "usable emulator with model-dependent identity",
        ),
        AsicImplementationProfile(
            "mame",
            "MAME",
            "mame0287",
            frozenset({0x02, 0x15, 0x21}),
            0xC3,
            0x33,
            "write and readback masked with 0x0F",
            "ports 0x39 and 0x3A are absent",
            "MACHINE_NOT_WORKING TI-84 Plus driver",
        ),
    )
}


def asic_implementation(profile: str) -> AsicImplementationProfile:
    """Return one pinned ASIC-control implementation profile."""

    try:
        return ASIC_IMPLEMENTATIONS[profile.lower()]
    except KeyError:
        choices = ", ".join(ASIC_IMPLEMENTATIONS)
        raise ValueError(f"unknown ASIC profile {profile!r}; choose {choices}") from None


def implementation_port21_readback(profile: str, written: int) -> int:
    """Return port-``0x21`` readback after an accepted implementation write."""

    written = _byte(written)
    key = asic_implementation(profile).key
    if key == "tilem":
        return written & 0x33
    if key == "wabbitemu":
        return written & 0x03
    return written & 0x0F


@dataclass(frozen=True)
class Port02Status:
    """Bitwise decode of one port-``0x02`` read."""

    raw: int
    battery_comparator_high: bool
    lcd_ready: bool
    flash_unlocked: bool
    bit3: bool
    bit4: bool
    usb_capable: bool
    link_assist: bool
    advanced_family: bool


def decode_port02(value: int) -> Port02Status:
    """Decode the eight status bits returned by port ``0x02``."""

    value = _byte(value)
    return Port02Status(
        raw=value,
        battery_comparator_high=bool(value & 0x01),
        lcd_ready=bool(value & 0x02),
        flash_unlocked=bool(value & 0x04),
        bit3=bool(value & 0x08),
        bit4=bool(value & 0x10),
        usb_capable=bool(value & 0x20),
        link_assist=bool(value & 0x40),
        advanced_family=bool(value & 0x80),
    )


@dataclass(frozen=True)
class AsicIdentity:
    """One publicly reported port-``0x15`` identity value."""

    value: int
    reference: str
    usb_driver: str
    ram_kib: int
    ram_location: str | None


ASIC_IDENTITIES = {
    identity.value: identity
    for identity in (
        AsicIdentity(0x33, "83PL2M/TA2", "none", 128, "external"),
        AsicIdentity(0x44, "83PLUSB/TA2", "old", 128, None),
        AsicIdentity(0x45, "84PLUSB/TA3", "new", 128, None),
        AsicIdentity(0x55, "84PLC/TA1", "new", 48, None),
    )
}


def decode_port15(value: int) -> AsicIdentity | None:
    """Return the public identity-table row for ``value``, if one exists."""

    return ASIC_IDENTITIES.get(_byte(value))


@dataclass(frozen=True)
class Port21Control:
    """Decode the writable fields exposed by port ``0x21``."""

    raw: int
    visible_value: int
    flash_group: int
    documented_flash_kib: int
    ram_execution_mode: int
    documented_ram_kib: int
    tilem_ram_address_mask: int


def decode_port21(value: int) -> Port21Control:
    """Decode Flash grouping and RAM-execution mode from port ``0x21``.

    TilEm exposes only mask ``0x33`` on reads.  Its implementation converts
    bits 4-5 to a repeating address mask.  Ports ``0x25`` and ``0x26`` supply
    separate chunk bounds, so page coverage belongs to
    :mod:`execution_protection` rather than this register-only decoder.
    """

    value = _byte(value)
    flash_group = value & 0x03
    ram_mode = (value >> 4) & 0x03
    return Port21Control(
        raw=value,
        visible_value=value & 0x33,
        flash_group=flash_group,
        documented_flash_kib=1024 << flash_group,
        ram_execution_mode=ram_mode,
        documented_ram_kib=32 << ram_mode,
        tilem_ram_address_mask=tilem_ram_mask(ram_mode),
    )


@dataclass(frozen=True)
class BatteryConfiguration:
    """Decode the port-``0x04`` selector used before a battery comparison."""

    raw: int
    selector: int
    other_bits: int
    tilem_threshold_tenths_volt: int


def decode_battery_configuration(value: int) -> BatteryConfiguration:
    """Decode TilEm's unmeasured voltage selector for a port-``0x04`` write."""

    value = _byte(value)
    selector = value >> 6
    return BatteryConfiguration(
        raw=value,
        selector=selector,
        other_bits=value & 0x3F,
        tilem_threshold_tenths_volt=TILEM_BATTERY_THRESHOLDS[selector],
    )


@dataclass(frozen=True)
class GpioReadModifyWrite:
    """One adjacent ``IN``/mask/``OUT`` update of a GPIO register."""

    port: int
    operation: str
    mask: int
    read: Z80Instruction
    modify: Z80Instruction
    write: Z80Instruction


def _literal_byte(operand: str) -> int | None:
    operand = operand.strip().lower()
    if not operand.endswith("h"):
        return None
    try:
        value = int(operand[:-1], 16)
    except ValueError:
        return None
    return value if 0 <= value <= 0xFF else None


def gpio_read_modify_write(
    instructions: Sequence[Z80Instruction], index: int
) -> GpioReadModifyWrite | None:
    """Decode an adjacent GPIO ``IN A``/``AND|OR``/``OUT A`` sequence."""

    if index < 0 or index + 2 >= len(instructions):
        return None
    read, modify, write = instructions[index : index + 3]
    read_access = direct_io_access(read)
    write_access = direct_io_access(write)
    if (
        read_access is None
        or write_access is None
        or read_access.direction != "in"
        or write_access.direction != "out"
        or read_access.port != write_access.port
        or read_access.port not in GPIO_PORTS
        or read.operands.split(",", 1)[0].strip() != "a"
        or not write.operands.rstrip().endswith(",a")
        or modify.mnemonic not in {"and", "or"}
    ):
        return None
    literal = _literal_byte(modify.operands)
    if literal is None:
        return None
    if modify.mnemonic == "or":
        operation, mask = "set", literal
    else:
        operation, mask = "clear", (~literal) & 0xFF
    return GpioReadModifyWrite(
        port=read_access.port,
        operation=operation,
        mask=mask,
        read=read,
        modify=modify,
        write=write,
    )


def iter_gpio_read_modify_writes(
    instructions: Iterable[Z80Instruction],
) -> Iterator[GpioReadModifyWrite]:
    """Yield adjacent GPIO read-modify-write sequences."""

    sequence = tuple(instructions)
    for index in range(len(sequence) - 2):
        operation = gpio_read_modify_write(sequence, index)
        if operation is not None:
            yield operation
