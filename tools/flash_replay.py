"""Replay accepted AMD Flash commands over a source TI-84 Plus ROM image."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from flash_hardware import FLASH_SIZE, flash_sector
from flash_trace import FlashCommand
from gc_journal import (
    CERTIFICATE_HALF_BASES,
    GC_BLOCK_OFFSET,
    MASTER_PHASE_OFFSET,
)


class FlashReplayError(ValueError):
    """A command stream cannot be replayed without hiding an ambiguity."""


@dataclass(frozen=True)
class FlashMutation:
    """One accepted command's observable array mutation."""

    kind: str
    clock: int
    target_address: int
    start: int
    end: int
    changed_bytes: int


@dataclass(frozen=True)
class FlashReplayResult:
    """A replayed Flash image plus command and mutation accounting."""

    image: bytes
    commands_applied: int
    command_counts: tuple[tuple[str, int], ...]
    mutations: tuple[FlashMutation, ...]
    last_clock: int | None


@dataclass(frozen=True)
class GcPhaseSnapshot:
    """A replay image with one active, non-erased GC journal phase."""

    phase: int
    half_base: int
    trigger_clock: int
    trigger_kind: str
    trigger_address: int
    replay: FlashReplayResult


def _validate_image(image: bytes | bytearray) -> None:
    if len(image) != FLASH_SIZE:
        raise FlashReplayError(
            f"Flash image must contain 0x{FLASH_SIZE:X} bytes, got 0x{len(image):X}"
        )


def apply_accepted_command(
    image: bytearray,
    command: FlashCommand,
) -> FlashMutation | None:
    """Apply one command under explicit device-acceptance semantics.

    Byte programming uses the NOR ``old & requested`` rule. Sector erase uses
    the compatible top-boot geometry. Array-reset writes do not change array
    data. An unmatched CPU write is rejected because its device effect is not
    defined by the command decoder.
    """

    _validate_image(image)
    if command.kind == "array_reset":
        return None
    if command.kind == "unmatched_write":
        raise FlashReplayError(
            "cannot replay unmatched Flash write at "
            f"clock {command.clock}, address 0x{command.target_address:05X}"
        )
    if command.kind == "byte_program":
        if not 0 <= command.target_address < FLASH_SIZE:
            raise FlashReplayError(
                f"byte-program target outside Flash: 0x{command.target_address:X}"
            )
        address = command.target_address
        previous = image[address]
        image[address] &= command.value
        return FlashMutation(
            kind=command.kind,
            clock=command.clock,
            target_address=address,
            start=address,
            end=address + 1,
            changed_bytes=int(image[address] != previous),
        )
    if command.kind == "sector_erase":
        sector = flash_sector(command.target_address)
        changed = sum(value != 0xFF for value in image[sector.start:sector.end])
        image[sector.start:sector.end] = b"\xFF" * sector.size
        return FlashMutation(
            kind=command.kind,
            clock=command.clock,
            target_address=command.target_address,
            start=sector.start,
            end=sector.end,
            changed_bytes=changed,
        )
    raise FlashReplayError(f"unknown Flash command kind {command.kind!r}")


def replay_accepted_commands(
    source: bytes,
    commands: Iterable[FlashCommand],
    *,
    stop_clock: int | None = None,
) -> FlashReplayResult:
    """Replay accepted commands through an optional inclusive clock cutoff."""

    _validate_image(source)
    image = bytearray(source)
    counts: Counter[str] = Counter()
    mutations = []
    last_clock = None
    previous_clock = None
    for command in commands:
        if previous_clock is not None and command.clock < previous_clock:
            raise FlashReplayError(
                f"command clocks are not monotonic: {command.clock} after {previous_clock}"
            )
        previous_clock = command.clock
        if stop_clock is not None and command.clock > stop_clock:
            break
        mutation = apply_accepted_command(image, command)
        counts[command.kind] += 1
        if mutation is not None:
            mutations.append(mutation)
        last_clock = command.clock
    return FlashReplayResult(
        image=bytes(image),
        commands_applied=sum(counts.values()),
        command_counts=tuple(sorted(counts.items())),
        mutations=tuple(mutations),
        last_clock=last_clock,
    )


def active_certificate_half(image: bytes | bytearray) -> int | None:
    """Return the sole certificate half whose base marker is ``0x00``."""

    _validate_image(image)
    active = tuple(base for base in CERTIFICATE_HALF_BASES if image[base] == 0)
    return active[0] if len(active) == 1 else None


def gc_journal_phase(image: bytes | bytearray) -> tuple[int, int] | None:
    """Return ``(active half, phase)`` for a non-erased GC journal block.

    An ordinary certificate half can contain an erased ``0xFF`` master byte.
    The GC flags byte distinguishes that idle image from the initialized
    interruption journal used by the phase dispatcher.
    """

    half = active_certificate_half(image)
    if half is None or image[half + GC_BLOCK_OFFSET] == 0xFF:
        return None
    return half, image[half + MASTER_PHASE_OFFSET]


def find_gc_phase_snapshots(
    source: bytes,
    commands: Iterable[FlashCommand],
    phases: Iterable[int],
) -> tuple[GcPhaseSnapshot, ...]:
    """Return the first active replay image observed for each requested phase."""

    _validate_image(source)
    requested = tuple(dict.fromkeys(phases))
    for phase in requested:
        if not 0 <= phase <= 0xFF:
            raise FlashReplayError(f"journal phase must be a byte, got {phase}")
    pending = set(requested)
    image = bytearray(source)
    counts: Counter[str] = Counter()
    mutations: list[FlashMutation] = []
    snapshots: dict[int, GcPhaseSnapshot] = {}
    previous_clock = None
    for command in commands:
        if previous_clock is not None and command.clock < previous_clock:
            raise FlashReplayError(
                f"command clocks are not monotonic: {command.clock} after {previous_clock}"
            )
        previous_clock = command.clock
        mutation = apply_accepted_command(image, command)
        counts[command.kind] += 1
        if mutation is not None:
            mutations.append(mutation)
        journal = gc_journal_phase(image)
        if journal is None or journal[1] not in pending:
            continue
        half, phase = journal
        replay = FlashReplayResult(
            image=bytes(image),
            commands_applied=sum(counts.values()),
            command_counts=tuple(sorted(counts.items())),
            mutations=tuple(mutations),
            last_clock=command.clock,
        )
        snapshots[phase] = GcPhaseSnapshot(
            phase=phase,
            half_base=half,
            trigger_clock=command.clock,
            trigger_kind=command.kind,
            trigger_address=command.target_address,
            replay=replay,
        )
        pending.remove(phase)
        if not pending:
            break
    if pending:
        missing = ", ".join(f"0x{phase:02X}" for phase in requested if phase in pending)
        raise FlashReplayError(f"trace never exposes active GC phase(s): {missing}")
    return tuple(snapshots[phase] for phase in requested)
