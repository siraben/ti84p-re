"""Decode TI-84 Plus ASIC status, identity, protection, and GPIO operations.

The bit assignments in this module are mechanical decoders.  Their evidence
quality is deliberately left to callers: some names are established by the
retail ROM, while the identity and voltage tables come from public documents
or emulator implementations rather than physical measurements.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from execution_protection import tilem_ram_mask
from rom_image import RomImage, RomLocation
from z80_disassembly import Z80Instruction
from z80_io import direct_io_access

GPIO_PORTS = frozenset({0x39, 0x3A})
TILEM_BATTERY_THRESHOLDS = (33, 39, 36, 43)
ASIC_CONTROL_PORTS = frozenset({0x02, 0x15, 0x21, 0x39, 0x3A})
_BIT_A_RE = re.compile(r"^([0-7]),\s*a$")

# Linear disassembly renders this table byte pair as ``IN A,(0x39)``.  The
# rebuilt Ghidra database has no containing function or references at the
# location, and the surrounding bytes form an address table rather than code.
REVIEWED_ASIC_IO_DATA = {
    RomLocation(0x02, 0x5142): "table-shaped data with no function or xrefs",
}


def _byte(value: int) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError("register values must be bytes")
    return value


def _literal_byte(operand: str) -> int | None:
    operand = operand.strip().lower()
    if not operand.endswith("h"):
        return None
    try:
        value = int(operand[:-1], 16)
    except ValueError:
        return None
    return value if 0 <= value <= 0xFF else None


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
class ImmediatePortConsumer:
    """First conservative mask or bit test consuming one immediate-port read."""

    port: int
    read: Z80Instruction
    test: Z80Instruction | None
    form: str
    mask: int | None
    intervening: tuple[Z80Instruction, ...]

    @property
    def bits(self) -> tuple[int, ...]:
        """Return every bit selected by the consumer mask."""

        if self.mask is None:
            return ()
        return tuple(bit for bit in range(8) if self.mask & (1 << bit))


def _a_test(instruction: Z80Instruction) -> tuple[str, int] | None:
    if instruction.mnemonic == "and":
        mask = _literal_byte(instruction.operands)
        return None if mask is None else ("and-mask", mask)
    if instruction.mnemonic == "bit":
        match = _BIT_A_RE.fullmatch(instruction.operands)
        if match is not None:
            return "bit-test", 1 << int(match.group(1))
    return None


def _preserves_a(instruction: Z80Instruction) -> bool:
    """Recognize a small set of instructions safe to cross before an A test."""

    if instruction.mnemonic == "ld":
        destination = instruction.operands.split(",", 1)[0].strip()
        return destination not in {"a", "af"}
    return instruction.mnemonic in {"nop", "di", "ei", "push"}


def immediate_port_consumer(
    instructions: Sequence[Z80Instruction],
    index: int,
    *,
    port: int,
    max_distance: int = 3,
) -> ImmediatePortConsumer | None:
    """Classify one direct ``IN A,(port)`` and its first nearby A test.

    The scan crosses only instructions that mechanically preserve ``A``. It
    stops rather than guessing across calls, branches, arithmetic, or unknown
    data decoded as instructions.
    """

    if max_distance <= 0:
        raise ValueError("maximum consumer distance must be positive")
    _byte(port)
    if not 0 <= index < len(instructions):
        raise IndexError("status-read instruction index is outside the sequence")
    read = instructions[index]
    access = direct_io_access(read)
    if (
        access is None
        or access.direction != "in"
        or access.port != port
        or read.operands.split(",", 1)[0].strip() != "a"
    ):
        return None

    intervening: list[Z80Instruction] = []
    stop = min(len(instructions), index + max_distance + 1)
    for candidate in instructions[index + 1 : stop]:
        test = _a_test(candidate)
        if test is not None:
            form, mask = test
            return ImmediatePortConsumer(
                port=port,
                read=read,
                test=candidate,
                form=form,
                mask=mask,
                intervening=tuple(intervening),
            )
        if not _preserves_a(candidate):
            break
        intervening.append(candidate)
    return ImmediatePortConsumer(
        port=port,
        read=read,
        test=None,
        form="unclassified",
        mask=None,
        intervening=tuple(intervening),
    )


def iter_immediate_port_consumers(
    instructions: Iterable[Z80Instruction],
    port: int,
) -> Iterator[ImmediatePortConsumer]:
    """Yield every direct read of ``port`` with its conservative consumer."""

    _byte(port)
    sequence = tuple(instructions)
    for index, instruction in enumerate(sequence):
        access = direct_io_access(instruction)
        if access is None or access.direction != "in" or access.port != port:
            continue
        consumer = immediate_port_consumer(sequence, index, port=port)
        if consumer is not None:
            yield consumer


def summarize_immediate_port_consumers(
    consumers: Iterable[ImmediatePortConsumer],
) -> dict[int | None, int]:
    """Count immediate-port reads by consumer mask; ``None`` is unclassified."""

    return dict(Counter(consumer.mask for consumer in consumers))


@dataclass(frozen=True)
class RawImmediateIO:
    """One raw immediate-port opcode pair in a physical ROM page."""

    location: RomLocation
    direction: str
    port: int


def raw_immediate_io_locations(
    rom: RomImage,
    ports: Iterable[int],
    pages: Iterable[int] | None = None,
    *,
    directions: Iterable[str] = ("in", "out"),
) -> tuple[RawImmediateIO, ...]:
    """Return raw immediate-port opcode pairs in selected physical pages."""

    selected_ports = tuple(sorted({_byte(port) for port in ports}))
    selected_directions = frozenset(directions)
    invalid_directions = selected_directions - {"in", "out"}
    if invalid_directions:
        invalid = ", ".join(sorted(invalid_directions))
        raise ValueError(f"unknown I/O direction: {invalid}")
    selected_pages = range(rom.page_count) if pages is None else tuple(pages)
    candidates: list[RawImmediateIO] = []
    for page_number in selected_pages:
        if not 0 <= page_number < rom.page_count:
            raise ValueError(f"page 0x{page_number:X} is outside this ROM")
        page = rom.page(page_number)
        origin = 0 if page_number == 0 else 0x4000
        for offset in range(len(page) - 1):
            opcode, port = page[offset : offset + 2]
            direction = {0xDB: "in", 0xD3: "out"}.get(opcode)
            if direction in selected_directions and port in selected_ports:
                candidates.append(
                    RawImmediateIO(
                        RomLocation(page_number, origin + offset), direction, port
                    )
                )
    return tuple(candidates)


@dataclass(frozen=True)
class ImmediateIOClassification:
    """Static classification of one raw immediate-port opcode pair."""

    candidate: RawImmediateIO
    classification: str
    instruction: Z80Instruction | None
    note: str | None = None


@dataclass(frozen=True)
class ImmediateIOAudit:
    """Raw-byte coverage for selected immediate-port reads and writes."""

    ports: tuple[int, ...]
    classifications: tuple[ImmediateIOClassification, ...]
    decoded_without_raw: tuple[Z80Instruction, ...]

    @property
    def classification_counts(self) -> dict[str, int]:
        """Count raw pairs by reviewed classification."""

        return dict(Counter(item.classification for item in self.classifications))

    @property
    def complete(self) -> bool:
        """Return whether every raw and decoded candidate is accounted for."""

        return (
            not self.decoded_without_raw
            and all(
                item.classification != "unclassified"
                for item in self.classifications
            )
        )


def audit_immediate_io(
    rom: RomImage,
    instructions: Iterable[Z80Instruction],
    ports: Iterable[int],
    pages: Iterable[int] | None = None,
    *,
    directions: Iterable[str] = ("in", "out"),
    reviewed_data: dict[RomLocation, str] | None = None,
) -> ImmediateIOAudit:
    """Reconcile raw opcode pairs with linear instructions and reviewed data.

    ``operand-overlap`` means the would-be opcode byte is inside another
    instruction; a pair can also cross into the following instruction. Linear
    instruction matches still require control-flow review. Callers can mark
    known false decodes through ``reviewed_data``.
    """

    selected_ports = tuple(sorted({_byte(port) for port in ports}))
    selected_directions = frozenset(directions)
    sequence = tuple(instructions)
    raw = raw_immediate_io_locations(
        rom,
        selected_ports,
        pages,
        directions=selected_directions,
    )
    raw_keys = {
        (item.location, item.direction, item.port)
        for item in raw
    }
    decoded = []
    decoded_by_key = {}
    for instruction in sequence:
        access = direct_io_access(instruction)
        if (
            access is not None
            and access.port in selected_ports
            and access.direction in selected_directions
        ):
            key = (instruction.location, access.direction, access.port)
            decoded.append((key, instruction))
            decoded_by_key[key] = instruction

    owners_by_page: dict[int, list[Z80Instruction]] = {}
    for instruction in sequence:
        owners_by_page.setdefault(instruction.location.page, []).append(instruction)
    reviewed = reviewed_data or {}
    classifications = []
    for candidate in raw:
        key = (candidate.location, candidate.direction, candidate.port)
        instruction = decoded_by_key.get(key)
        note = reviewed.get(candidate.location)
        if note is not None:
            classification = "reviewed-data"
        elif instruction is not None:
            classification = "instruction"
        else:
            instruction = next(
                (
                    owner
                    for owner in owners_by_page.get(candidate.location.page, ())
                    if owner.location.address < candidate.location.address
                    < owner.end_address
                ),
                None,
            )
            classification = (
                "operand-overlap" if instruction is not None else "unclassified"
            )
        classifications.append(
            ImmediateIOClassification(candidate, classification, instruction, note)
        )

    return ImmediateIOAudit(
        selected_ports,
        tuple(classifications),
        tuple(
            instruction
            for key, instruction in decoded
            if key not in raw_keys and instruction.location not in reviewed
        ),
    )


# Compatibility wrappers keep the port-0x02 API stable for existing callers.
Port02Consumer = ImmediatePortConsumer


def port02_consumer(
    instructions: Sequence[Z80Instruction],
    index: int,
    *,
    max_distance: int = 3,
) -> ImmediatePortConsumer | None:
    """Classify one direct port-``0x02`` read and its nearby A test."""

    return immediate_port_consumer(
        instructions, index, port=0x02, max_distance=max_distance
    )


def iter_port02_consumers(
    instructions: Iterable[Z80Instruction],
) -> Iterator[ImmediatePortConsumer]:
    """Yield direct port-``0x02`` reads with conservative consumers."""

    return iter_immediate_port_consumers(instructions, 0x02)


def summarize_port02_consumers(
    consumers: Iterable[ImmediatePortConsumer],
) -> dict[int | None, int]:
    """Count direct port-``0x02`` consumers by mask."""

    return summarize_immediate_port_consumers(consumers)


def raw_port02_read_locations(
    rom: RomImage,
    pages: Iterable[int] | None = None,
) -> tuple[RomLocation, ...]:
    """Return every raw ``DB 02`` pair in selected physical ROM pages."""

    return tuple(
        candidate.location
        for candidate in raw_immediate_io_locations(
            rom, (0x02,), pages, directions=("in",)
        )
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
