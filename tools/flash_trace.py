"""Reusable decoding for AMD-compatible Flash command traces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from hardware_trace import ResolvedMemoryWrite


FLASH_SIZE = 0x100000
UNLOCK_ADDR_1 = 0x0AAAA
UNLOCK_ADDR_2 = 0x05555


@dataclass(frozen=True)
class FlashSector:
    start: int
    size: int


@dataclass(frozen=True)
class FlashCommand:
    kind: str
    instruction_index: int
    clock: int
    target_address: int
    value: int
    writes: tuple[ResolvedMemoryWrite, ...]


@dataclass(frozen=True)
class FlashCommandRun:
    """A contiguous run of byte-program commands."""

    commands: tuple[FlashCommand, ...]

    @property
    def start_address(self) -> int:
        return self.commands[0].target_address

    @property
    def end_address(self) -> int:
        return self.commands[-1].target_address


def flash_sector(address: int) -> FlashSector:
    """Return the Am29LV800B top-boot sector containing *address*."""

    if not 0 <= address < FLASH_SIZE:
        raise ValueError(f"Flash address outside 1 MiB device: 0x{address:X}")
    if address < 0xF0000:
        return FlashSector(address & ~0xFFFF, 0x10000)
    if address < 0xF8000:
        return FlashSector(0xF0000, 0x8000)
    if address < 0xFA000:
        return FlashSector(0xF8000, 0x2000)
    if address < 0xFC000:
        return FlashSector(0xFA000, 0x2000)
    return FlashSector(0xFC000, 0x4000)


def _at(event: ResolvedMemoryWrite, address: int, value: int) -> bool:
    return event.flat_address == address and event.value == value


def decode_amd_flash_commands(
    writes: Iterable[ResolvedMemoryWrite],
) -> Iterator[FlashCommand]:
    """Decode byte-program, sector-erase, reset, and unmatched Flash writes."""

    events = [event for event in writes if event.target_kind == "flash"]
    index = 0
    while index < len(events):
        event = events[index]
        if (
            index + 5 < len(events)
            and _at(events[index], UNLOCK_ADDR_1, 0xAA)
            and _at(events[index + 1], UNLOCK_ADDR_2, 0x55)
            and _at(events[index + 2], UNLOCK_ADDR_1, 0x80)
            and _at(events[index + 3], UNLOCK_ADDR_1, 0xAA)
            and _at(events[index + 4], UNLOCK_ADDR_2, 0x55)
            and events[index + 5].value == 0x30
            and events[index + 5].flat_address is not None
        ):
            sequence = tuple(events[index:index + 6])
            target = sequence[-1]
            yield FlashCommand(
                "sector_erase",
                target.instruction_index,
                target.clock,
                target.flat_address,
                target.value,
                sequence,
            )
            index += 6
            continue
        if (
            index + 3 < len(events)
            and _at(events[index], UNLOCK_ADDR_1, 0xAA)
            and _at(events[index + 1], UNLOCK_ADDR_2, 0x55)
            and _at(events[index + 2], UNLOCK_ADDR_1, 0xA0)
            and events[index + 3].flat_address is not None
        ):
            sequence = tuple(events[index:index + 4])
            target = sequence[-1]
            yield FlashCommand(
                "byte_program",
                target.instruction_index,
                target.clock,
                target.flat_address,
                target.value,
                sequence,
            )
            index += 4
            continue
        if event.value == 0xF0 and event.flat_address is not None:
            yield FlashCommand(
                "array_reset",
                event.instruction_index,
                event.clock,
                event.flat_address,
                event.value,
                (event,),
            )
        elif event.flat_address is not None:
            yield FlashCommand(
                "unmatched_write",
                event.instruction_index,
                event.clock,
                event.flat_address,
                event.value,
                (event,),
            )
        index += 1


def group_byte_program_runs(
    commands: Iterable[FlashCommand], *, max_clock_gap: int = 100_000
) -> Iterator[FlashCommandRun]:
    """Group adjacent byte-program targets into compact timeline runs."""

    pending: list[FlashCommand] = []
    for command in commands:
        if command.kind != "byte_program":
            if command.kind == "array_reset":
                continue
            if pending:
                yield FlashCommandRun(tuple(pending))
                pending.clear()
            continue
        if pending:
            previous = pending[-1]
            adjacent = command.target_address == previous.target_address + 1
            close = command.clock - previous.clock <= max_clock_gap
            if not adjacent or not close:
                yield FlashCommandRun(tuple(pending))
                pending.clear()
        pending.append(command)
    if pending:
        yield FlashCommandRun(tuple(pending))
