"""Structural candidates for Flash command writes in linear ROM disassembly.

These helpers identify exact Z80 encodings.  Linear disassembly can decode data
as instructions or lose the intended alignment after data, so every result is a
candidate for control-flow confirmation rather than proof of execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

from z80_disassembly import Z80Instruction


FLASH_UNLOCK_LOGICAL_ADDRESSES = frozenset((0x5555, 0x6AAA))
FLASH_COMMAND_BYTES = {
    0x00: "fast_exit_zero",
    0x10: "chip_erase",
    0x20: "fast_enter",
    0x30: "sector_erase_or_resume",
    0x55: "unlock_55",
    0x80: "erase_setup",
    0x90: "autoselect_or_fast_exit",
    0x98: "cfi_query",
    0xA0: "byte_program",
    0xAA: "unlock_aa",
    0xB0: "erase_suspend",
    0xF0: "read_reset_or_fast_exit",
}


@dataclass(frozen=True)
class ImmediateALoad:
    """One nearby ``LD A,n`` whose byte has a Flash-command meaning."""

    instruction: Z80Instruction
    distance: int
    value: int
    meaning: str


@dataclass(frozen=True)
class FlashUnlockWriteCandidate:
    """One instruction-aligned ``LD (unlock_address),A`` candidate."""

    instruction: Z80Instruction
    target_address: int
    nearby_command_loads: tuple[ImmediateALoad, ...]


def direct_store_a_address(instruction: Z80Instruction) -> int | None:
    """Decode an exact ``LD (nn),A`` instruction from its bytes."""

    if len(instruction.data) != 3 or instruction.data[0] != 0x32:
        return None
    return int.from_bytes(instruction.data[1:], "little")


def immediate_a_value(instruction: Z80Instruction) -> int | None:
    """Decode an exact ``LD A,n`` instruction from its bytes."""

    if len(instruction.data) != 2 or instruction.data[0] != 0x3E:
        return None
    return instruction.data[1]


def nearby_flash_command_loads(
    instructions: Sequence[Z80Instruction],
    index: int,
    *,
    before: int = 8,
    after: int = 3,
) -> tuple[ImmediateALoad, ...]:
    """Return command-valued immediate A loads around one instruction."""

    if before < 0 or after < 0:
        raise ValueError("context distances must be nonnegative")
    start = max(0, index - before)
    stop = min(len(instructions), index + after + 1)
    loads = []
    for load_index in range(start, stop):
        value = immediate_a_value(instructions[load_index])
        if value not in FLASH_COMMAND_BYTES:
            continue
        loads.append(
            ImmediateALoad(
                instruction=instructions[load_index],
                distance=load_index - index,
                value=value,
                meaning=FLASH_COMMAND_BYTES[value],
            )
        )
    return tuple(loads)


def find_flash_unlock_write_candidates(
    instructions: Sequence[Z80Instruction],
    *,
    before: int = 8,
    after: int = 3,
) -> Iterator[FlashUnlockWriteCandidate]:
    """Yield linear-disassembly stores to either OS-visible unlock address."""

    if before < 0 or after < 0:
        raise ValueError("context distances must be nonnegative")
    for index, instruction in enumerate(instructions):
        target = direct_store_a_address(instruction)
        if target not in FLASH_UNLOCK_LOGICAL_ADDRESSES:
            continue
        yield FlashUnlockWriteCandidate(
            instruction=instruction,
            target_address=target,
            nearby_command_loads=nearby_flash_command_loads(
                instructions, index, before=before, after=after
            ),
        )


def command_values(candidates: Iterable[FlashUnlockWriteCandidate]) -> frozenset[int]:
    """Return distinct nearby command-valued A loads from candidates."""

    return frozenset(
        load.value
        for candidate in candidates
        for load in candidate.nearby_command_loads
    )
