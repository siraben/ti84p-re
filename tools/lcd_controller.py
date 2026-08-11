"""Reusable T6A04 command and emulator pointer models.

The transfer walkers reproduce pinned TilEm, Wabbitemu, and MAME source.  They
are debugging oracles for those implementations, not physical-controller
claims.
"""

from __future__ import annotations

from dataclasses import dataclass


LCD_ROWS = 64


def _byte(value: int, name: str) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be a byte")
    return value


def _movement(value: int) -> int:
    if not 4 <= value <= 7:
        raise ValueError("movement command must be between 4 and 7")
    return value


def _word_length(value: int) -> int:
    if value not in {6, 8}:
        raise ValueError("word length must be 6 or 8")
    return value


@dataclass(frozen=True)
class LcdCommand:
    """Decoded T6A04-compatible controller command."""

    value: int
    kind: str
    argument: int


def decode_lcd_command(value: int) -> LcdCommand:
    """Decode a controller command using the shared T6A04 command map."""

    value = _byte(value, "command")
    if value >= 0xC0:
        return LcdCommand(value, "contrast", value & 0x3F)
    if value >= 0x80:
        return LcdCommand(value, "row", value & 0x3F)
    if value >= 0x40:
        return LcdCommand(value, "row_shift", value & 0x3F)
    if value >= 0x20:
        return LcdCommand(value, "column", value & 0x1F)
    if 0x18 <= value <= 0x1F:
        return LcdCommand(value, "test_mode", value & 0x07)
    if 0x10 <= value <= 0x17:
        return LcdCommand(value, "power_level", value & 0x07)
    if 0x08 <= value <= 0x0F:
        return LcdCommand(value, "power_enhancement", value & 0x07)
    if 0x04 <= value <= 0x07:
        return LcdCommand(value, "movement", value)
    if value in {0x02, 0x03}:
        return LcdCommand(value, "display", value & 1)
    return LcdCommand(value, "word_length", 8 if value & 1 else 6)


@dataclass(frozen=True)
class LcdEmulatorProfile:
    """Pinned source characteristics for one monochrome LCD model."""

    name: str
    revision: str
    row_stride: int
    ram_size: int
    busy_model: str
    asic_ready_model: str
    mirrors_12_13: bool
    out_of_range_columns: str
    driver_status: str


LCD_EMULATOR_PROFILES = (
    LcdEmulatorProfile(
        name="TilEm",
        revision="f56ad637d0524ee841dd381be6ecbaf5b8975600",
        row_stride=16,
        ram_size=1024,
        busy_model="50 cycles, or 70 with long-delay flag",
        asic_ready_model="port 0x2F timer after every LCD read or write",
        mirrors_12_13=True,
        out_of_range_columns="normalize to column 0 before transfer",
        driver_status="TI-84 Plus model used for dynamic traces",
    ),
    LcdEmulatorProfile(
        name="Wabbitemu",
        revision="48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422",
        row_stride=16,
        ram_size=1024,
        busy_model="fixed 60 T-state guard measured from successful writes",
        asic_ready_model="port 0x2F interval measured from successful writes",
        mirrors_12_13=False,
        out_of_range_columns="memory index wraps modulo 16",
        driver_status="source model; no physical timing claim",
    ),
    LcdEmulatorProfile(
        name="MAME",
        revision="mame0287",
        row_stride=15,
        ram_size=960,
        busy_model="none; status busy bit is always zero",
        asic_ready_model="port 0x02 ready bit is always one",
        mirrors_12_13=True,
        out_of_range_columns="unchecked five-bit index",
        driver_status="TI-84 Plus driver is MACHINE_NOT_WORKING",
    ),
)


def lcd_emulator_profile(name: str) -> LcdEmulatorProfile:
    """Return a pinned profile by case-insensitive emulator name."""

    normalized = name.casefold()
    for profile in LCD_EMULATOR_PROFILES:
        if profile.name.casefold() == normalized:
            return profile
    choices = ", ".join(profile.name for profile in LCD_EMULATOR_PROFILES)
    raise ValueError(f"unknown emulator {name!r}; choose {choices}")


def lcd_status(
    *,
    word_length: int,
    display_on: bool,
    movement: int,
    busy: bool = False,
) -> int:
    """Compose the common status bits implemented by the three emulators."""

    word_length = _word_length(word_length)
    movement = _movement(movement)
    return (
        (0x80 if busy else 0)
        | (0x40 if word_length == 8 else 0)
        | (0x20 if display_on else 0)
        | (movement & 3)
    )


@dataclass(frozen=True)
class LcdTransferAccess:
    """One source-modeled data transfer and its following pointer state."""

    transfer_index: int
    requested_row: int
    requested_column: int
    accessed_row: int
    accessed_column: int
    array_index: int
    logical_column_in_range: bool
    array_index_in_range: bool
    next_row: int
    next_column: int


def _tilem_access(
    row: int, column: int, stride: int, word_length: int
) -> tuple[int, int]:
    column_limit = stride if word_length == 8 else (stride * 8 + 5) // 6
    if column >= column_limit:
        column = 0
    elif column < 0:
        column = column_limit - 1
    if row >= LCD_ROWS:
        row = 0
    elif row < 0:
        row = LCD_ROWS - 1
    return row, column


def _array_index(
    profile: LcdEmulatorProfile,
    row: int,
    column: int,
    word_length: int,
) -> tuple[int, int]:
    """Return the first backing-array byte and logical column limit."""

    if word_length == 8:
        column_limit = profile.row_stride
    elif profile.name == "Wabbitemu":
        column_limit = 19
    else:
        column_limit = (profile.row_stride * 8 + 5) // 6
    if word_length == 8:
        byte_column = column
    else:
        byte_column = (column * 6) >> 3
    if profile.name == "Wabbitemu":
        byte_column %= profile.row_stride
    return row * profile.row_stride + byte_column, column_limit


def _advance_tilem(row: int, column: int, movement: int) -> tuple[int, int]:
    if movement == 4:
        row -= 1
    elif movement == 5:
        row += 1
    elif movement == 6:
        column -= 1
    else:
        column += 1
    return row, column


def _advance_wabbitemu(
    row: int, column: int, movement: int, word_length: int
) -> tuple[int, int]:
    if movement == 4:
        row = (row - 1) % LCD_ROWS
    elif movement == 5:
        row = (row + 1) % LCD_ROWS
    elif movement == 6:
        column = (14 if word_length == 8 else 18) if column <= 0 else column - 1
    else:
        column += 1
        if column >= (15 if word_length == 8 else 19):
            column = 0
    return row, column


def _advance_mame(row: int, column: int, movement: int) -> tuple[int, int]:
    if movement & 2:
        column = (column + (1 if movement & 1 else -1)) & 0x1F
    else:
        row = (row + (1 if movement & 1 else -1)) & 0x3F
    return row, column


def walk_lcd_transfers(
    emulator: str,
    *,
    row: int,
    column: int,
    movement: int,
    count: int,
    word_length: int = 8,
) -> tuple[LcdTransferAccess, ...]:
    """Walk successive data transfers through one emulator's pointer rules."""

    profile = lcd_emulator_profile(emulator)
    movement = _movement(movement)
    word_length = _word_length(word_length)
    if not 0 <= row <= 0x3F:
        raise ValueError("row command argument must be between 0 and 63")
    if not 0 <= column <= 0x1F:
        raise ValueError("column command argument must be between 0 and 31")
    if count < 0:
        raise ValueError("transfer count must be nonnegative")

    accesses = []
    current_row, current_column = row, column
    for index in range(count):
        requested_row, requested_column = current_row, current_column
        if profile.name == "TilEm":
            accessed_row, accessed_column = _tilem_access(
                current_row, current_column, profile.row_stride, word_length
            )
            current_row, current_column = _advance_tilem(
                accessed_row, accessed_column, movement
            )
        elif profile.name == "Wabbitemu":
            accessed_row = current_row % LCD_ROWS
            accessed_column = current_column
            current_row, current_column = _advance_wabbitemu(
                current_row, current_column, movement, word_length
            )
        else:
            accessed_row, accessed_column = current_row, current_column
            current_row, current_column = _advance_mame(
                current_row, current_column, movement
            )

        array_index, column_limit = _array_index(
            profile, accessed_row, accessed_column, word_length
        )
        accesses.append(
            LcdTransferAccess(
                transfer_index=index,
                requested_row=requested_row,
                requested_column=requested_column,
                accessed_row=accessed_row,
                accessed_column=accessed_column,
                array_index=array_index,
                logical_column_in_range=0 <= accessed_column < column_limit,
                array_index_in_range=0 <= array_index < profile.ram_size,
                next_row=current_row,
                next_column=current_column,
            )
        )
    return tuple(accesses)


def read_latch_sequence(
    memory_values: tuple[int, ...], *, initial_latch: int = 0
) -> tuple[int, ...]:
    """Return the values observed across sequential dummy-latched reads."""

    latch = _byte(initial_latch, "initial latch")
    observed = []
    for value in memory_values:
        observed.append(latch)
        latch = _byte(value, "memory value")
    return tuple(observed)
