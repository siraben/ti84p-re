"""Decode AMD command-shaped CPU write attempts in resolved Flash traces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from ti84re.flash.hardware import FLASH_SIZE
from ti84re.trace.hardware import ResolvedMemoryWrite


UNLOCK_ADDR_1 = 0x0AAAA
UNLOCK_ADDR_2 = 0x05555
PROGRAM_SUCCESS_RESET_PC = ("ram", 0x816B)
PROGRAM_FAILURE_RESET_PC = ("ram", 0x8175)
CERTIFICATE_PROGRAM_SUCCESS_RESET_PC = ("ram", 0x8172)
CERTIFICATE_PROGRAM_FAILURE_RESET_PC = ("ram", 0x817B)
FLASH_WRITE_SEMANTICS = (
    "resolved CPU write attempts targeting mapped Flash; "
    "TLMT does not record ASIC or device acceptance"
)


def program_transition_kind(previous_address: int, current_address: int) -> str:
    """Classify one pair of byte-program targets in physical address space."""

    for address in (previous_address, current_address):
        if not 0 <= address < FLASH_SIZE:
            raise ValueError(f"Flash address outside 1 MiB device: 0x{address:X}")
    if current_address == previous_address + 1:
        if previous_address // 0x4000 != current_address // 0x4000:
            return "next-page"
        return "contiguous"
    if (
        (previous_address & 0x3FFF) == 0x3FFF
        and current_address == (previous_address & ~0x3FFF)
    ):
        return "same-page-window-wrap"
    return "discontinuity"


@dataclass(frozen=True)
class FlashCommand:
    """One command-shaped write sequence, without an ASIC-acceptance claim."""

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


@dataclass(frozen=True)
class FlashProgramInvocation:
    """Byte-program commands terminated by one worker array-reset write."""

    commands: tuple[FlashCommand, ...]
    reset: FlashCommand | None

    @property
    def start_address(self) -> int:
        return self.commands[0].target_address

    @property
    def end_address(self) -> int:
        return self.commands[-1].target_address

    @property
    def pages(self) -> tuple[int, ...]:
        return tuple(
            dict.fromkeys(
                command.target_address // 0x4000 for command in self.commands
            )
        )

    @property
    def page_crossings(self) -> int:
        return sum(
            current.target_address // 0x4000
            != previous.target_address // 0x4000
            for previous, current in zip(self.commands, self.commands[1:])
        )

    @property
    def contiguous(self) -> bool:
        return all(
            current.target_address == previous.target_address + 1
            for previous, current in zip(self.commands, self.commands[1:])
        )

    @property
    def transition_kinds(self) -> tuple[str, ...]:
        return tuple(
            program_transition_kind(
                previous.target_address,
                current.target_address,
            )
            for previous, current in zip(self.commands, self.commands[1:])
        )

    @property
    def reset_matches_final_target(self) -> bool:
        return self.reset is not None and self.reset.target_address == self.end_address

    @property
    def reset_pc(self) -> tuple[str, int] | None:
        """Return the PC attributed to the terminal reset write, when known."""

        if self.reset is None or not self.reset.writes:
            return None
        reset_write = self.reset.writes[-1]
        return reset_write.pc_space, reset_write.pc_address

    @property
    def worker_outcome(self) -> str:
        """Classify the copied OS 2.55MP worker path that emitted the reset."""

        if self.reset is None:
            return "unterminated"
        if self.reset_pc == PROGRAM_SUCCESS_RESET_PC:
            return "success"
        if self.reset_pc == PROGRAM_FAILURE_RESET_PC:
            return "failure"
        if self.reset_pc == CERTIFICATE_PROGRAM_SUCCESS_RESET_PC:
            return "certificate-success"
        if self.reset_pc == CERTIFICATE_PROGRAM_FAILURE_RESET_PC:
            return "certificate-failure"
        return "unknown-reset"


def _at(event: ResolvedMemoryWrite, address: int, value: int) -> bool:
    return event.flat_address == address and event.value == value


def decode_amd_flash_commands(
    writes: Iterable[ResolvedMemoryWrite],
) -> Iterator[FlashCommand]:
    """Decode command shapes without inferring ASIC or device acceptance."""

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


def group_byte_program_invocations(
    commands: Iterable[FlashCommand],
) -> Iterator[FlashProgramInvocation]:
    """Group program commands by the worker's terminal ``0xF0`` reset.

    A sector erase or unmatched write closes an unterminated group. This keeps
    failure or truncated traces visible instead of merging them into the next
    successful invocation.
    """

    pending: list[FlashCommand] = []
    for command in commands:
        if command.kind == "byte_program":
            pending.append(command)
            continue
        if command.kind == "array_reset":
            if pending:
                yield FlashProgramInvocation(tuple(pending), command)
                pending.clear()
            continue
        if pending:
            yield FlashProgramInvocation(tuple(pending), None)
            pending.clear()
    if pending:
        yield FlashProgramInvocation(tuple(pending), None)
