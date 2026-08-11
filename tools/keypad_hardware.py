"""Reusable TI-84 Plus keypad, ON-edge, and App mouse models.

The emulator functions reproduce pinned source implementations. The App mouse
model reproduces byte-confirmed OS 2.55MP movement decisions. Neither replaces
electrical measurements of a physical diode-less keypad matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class KeypadEmulatorProfile:
    """Pinned keypad and ON-key policy for one emulator."""

    name: str
    revision: str
    matrix_algorithm: str
    matrix_groups: int
    settling: str
    on_interrupt_edge: str
    on_detection: str
    driver_status: str


KEYPAD_EMULATOR_PROFILES = (
    KeypadEmulatorProfile(
        name="TilEm",
        revision="f56ad637d0524ee841dd381be6ecbaf5b8975600",
        matrix_algorithm="iterated transitive closure across intersecting rows",
        matrix_groups=8,
        settling="immediate",
        on_interrupt_edge="press and release",
        on_detection="event-driven when the injected state changes",
        driver_status="TI-84 Plus model used for dynamic traces",
    ),
    KeypadEmulatorProfile(
        name="Wabbitemu",
        revision="48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422",
        matrix_algorithm="one pairwise-overlap pass for each selected row",
        matrix_groups=7,
        settling="immediate",
        on_interrupt_edge="press only",
        on_detection="polled when the standard-interrupt device runs",
        driver_status="source model; no physical timing claim",
    ),
    KeypadEmulatorProfile(
        name="MAME",
        revision="mame0287",
        matrix_algorithm="XOR of every pressed key in selected rows",
        matrix_groups=7,
        settling="immediate",
        on_interrupt_edge="press only",
        on_detection="polled by the fixed 256 Hz timer-1 callback",
        driver_status="TI-84 Plus driver is MACHINE_NOT_WORKING",
    ),
)


def keypad_emulator_profile(name: str) -> KeypadEmulatorProfile:
    """Return a pinned profile by case-insensitive emulator name."""

    normalized = name.casefold()
    for profile in KEYPAD_EMULATOR_PROFILES:
        if profile.name.casefold() == normalized:
            return profile
    choices = ", ".join(profile.name for profile in KEYPAD_EMULATOR_PROFILES)
    raise ValueError(f"unknown keypad emulator {name!r}; choose {choices}")


def _byte(value: int, name: str) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be a byte")
    return value


def _matrix_rows(keys: Iterable[tuple[int, int]]) -> tuple[int, ...]:
    rows = [0] * 8
    for group, bit in keys:
        if not 0 <= group <= 7:
            raise ValueError("key group must be between 0 and 7")
        if not 0 <= bit <= 7:
            raise ValueError("key bit must be between 0 and 7")
        rows[group] |= 1 << bit
    return tuple(rows)


def _tilem_read(group_mask: int, rows: tuple[int, ...]) -> int:
    closed = 0
    for group, row in enumerate(rows):
        if not group_mask & (1 << group):
            closed |= row
    previous = -1
    while closed != previous:
        previous = closed
        for row in rows:
            if closed & row:
                closed |= row
    return (~closed) & 0xFF


def _wabbitemu_read(group_mask: int, rows: tuple[int, ...]) -> int:
    pairwise = [0] * 7
    for group in range(7):
        for other in range(7):
            if rows[group] & rows[other]:
                pairwise[group] |= rows[group] | rows[other]
    selected = (~group_mask) & 0xFF
    closed = 0
    for group in range(7):
        if selected & (1 << group):
            closed |= pairwise[group]
    return (~closed) & 0xFF


def _mame_read(group_mask: int, rows: tuple[int, ...]) -> int:
    value = 0xFF
    for group in range(7):
        if not group_mask & (1 << group):
            value ^= rows[group]
    return value


@dataclass(frozen=True)
class MatrixRead:
    """One source-modeled port-``0x01`` matrix read."""

    emulator: str
    group_mask: int
    pressed_keys: tuple[tuple[int, int], ...]
    active_low_value: int
    apparent_closed_bits: int
    algorithm: str


def read_keypad_matrix(
    emulator: str,
    group_mask: int,
    keys: Iterable[tuple[int, int]],
) -> MatrixRead:
    """Reproduce one emulator's port-``0x01`` read for pressed positions."""

    profile = keypad_emulator_profile(emulator)
    group_mask = _byte(group_mask, "group mask")
    pressed = tuple(keys)
    rows = _matrix_rows(pressed)
    if profile.name == "TilEm":
        value = _tilem_read(group_mask, rows)
    elif profile.name == "Wabbitemu":
        value = _wabbitemu_read(group_mask, rows)
    else:
        value = _mame_read(group_mask, rows)
    return MatrixRead(
        emulator=profile.name,
        group_mask=group_mask,
        pressed_keys=pressed,
        active_low_value=value,
        apparent_closed_bits=(~value) & 0xFF,
        algorithm=profile.matrix_algorithm,
    )


def on_transition_requests_interrupt(
    emulator: str, transition: str, *, enabled: bool = True
) -> bool:
    """Return whether the pinned source latches the named ON transition."""

    profile = keypad_emulator_profile(emulator)
    transition = transition.casefold()
    if transition not in {"press", "release"}:
        raise ValueError("ON transition must be press or release")
    if not enabled:
        return False
    return transition == "press" or profile.name == "TilEm"


APP_MOUSE_MAX_ROW = 0x3F
APP_MOUSE_MAX_COLUMN = 0x5F


@dataclass(frozen=True)
class AppMouseKeyResult:
    """One OS 2.55MP App mouse decision for a raw scanner event."""

    start_row: int
    start_column: int
    scan_code: int
    key: str
    diagonal: bool
    delta_row: int
    delta_column: int
    row: int
    column: int
    outcome: str
    return_code: int | None
    coordinates_returned_in_hl: bool


APP_MOUSE_DIRECTIONS = {
    0x01: ("down", 1, 0),
    0x02: ("left", 0, -1),
    0x03: ("right", 0, 1),
    0x04: ("up", -1, 0),
    0xF3: ("up-right", -1, 1),
    0xF5: ("up-left", -1, -1),
    0xFA: ("down-right", 1, 1),
    0xFC: ("down-left", 1, -1),
}


def _coordinate(value: int, maximum: int, name: str) -> int:
    if not 0 <= value <= maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return value


def app_mouse_force_key(
    row: int,
    column: int,
    scan_code: int,
    *,
    second_modifier: bool = False,
) -> AppMouseKeyResult:
    """Model ``_AppMouseForceKey`` at ``3B:7913`` for one input event.

    ``wait`` means the routine branches back into ``_AppMouseGetKey`` because
    the key is unsupported or every requested movement axis is at its limit.
    """

    row = _coordinate(row, APP_MOUSE_MAX_ROW, "row")
    column = _coordinate(column, APP_MOUSE_MAX_COLUMN, "column")
    scan_code = _byte(scan_code, "scan code")
    if scan_code == 0x09:
        return AppMouseKeyResult(
            row,
            column,
            scan_code,
            "enter",
            False,
            0,
            0,
            row,
            column,
            "enter",
            0x0C,
            False,
        )

    direction = APP_MOUSE_DIRECTIONS.get(scan_code)
    if direction is None:
        return AppMouseKeyResult(
            row,
            column,
            scan_code,
            "unsupported",
            False,
            0,
            0,
            row,
            column,
            "wait",
            None,
            False,
        )

    key, requested_row, requested_column = direction
    new_row = min(APP_MOUSE_MAX_ROW, max(0, row + requested_row))
    new_column = min(APP_MOUSE_MAX_COLUMN, max(0, column + requested_column))
    delta_row = new_row - row
    delta_column = new_column - column
    if delta_row == 0 and delta_column == 0:
        outcome = "wait"
        return_code = None
    else:
        outcome = "move"
        return_code = 0x08 if second_modifier else 0x0A
    return AppMouseKeyResult(
        start_row=row,
        start_column=column,
        scan_code=scan_code,
        key=key,
        diagonal=scan_code >= 0xF3,
        delta_row=delta_row,
        delta_column=delta_column,
        row=new_row,
        column=new_column,
        outcome=outcome,
        return_code=return_code,
        coordinates_returned_in_hl=outcome == "move" and not second_modifier,
    )
