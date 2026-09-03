"""Typed report and oracle for MAME's TI-84 Plus T6A04 LCD model."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ti84re.hardware.lcd_controller import (
    lcd_emulator_profile,
    lcd_status,
    read_latch_sequence,
    walk_lcd_transfers,
)
from ti84re.emulators.mame.runtime import MAME_VERSION, MameRuntimeError, parse_report_fields


@dataclass(frozen=True)
class MameLcdReport:
    """Complete native controller-state, pointer, latch, and port observations."""

    machine: str
    version: str
    reset_status10: int
    reset_status12: int
    reset_port2: int
    reset_ram_nonzero: int
    reset_x: int
    reset_y: int
    reset_z: int
    reset_output: int
    reset_word: int
    reset_display: int
    reset_active: int
    reset_direction: int
    rapid_status: tuple[int, ...]
    movement_status: tuple[int, ...]
    six_status: int
    eight_status: int
    mirror_off_status: int
    mirror_on_status: int
    contrast: int
    opa1: int
    opa2: int
    z: int
    increment_cells: tuple[int, ...]
    increment_final_x: int
    increment_final_y: int
    direct_column15_cell: int
    direct_column15_final_y: int
    direct_column31_cell: int
    direct_column31_final_y: int
    latch_reads: tuple[int, ...]
    latch_final_x: int
    latch_final_y: int
    six_cells: tuple[int, ...]
    six_final_y: int
    delay_initial: tuple[int, ...]
    delay_patterned: tuple[int, ...]
    ready: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _line(output: str, prefix: str) -> dict[str, str]:
    lines = [line for line in output.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        raise MameRuntimeError(f"MAME LCD output omits {prefix.strip()} report")
    return parse_report_fields(lines[0])


def _bytes(value: str, expected: int, name: str) -> tuple[int, ...]:
    if len(value) != expected * 2:
        raise MameRuntimeError(f"MAME LCD {name} must contain {expected} bytes")
    try:
        return tuple(
            int(value[index : index + 2], 16) for index in range(0, len(value), 2)
        )
    except ValueError as error:
        raise MameRuntimeError(f"invalid MAME LCD {name}") from error


def parse_mame_lcd_report(output: str) -> MameLcdReport:
    """Parse every native MAME LCD report line."""

    identity = _line(output, "MAME_LCD identity ")
    reset = _line(output, "MAME_LCD reset ")
    control = _line(output, "MAME_LCD control ")
    increment = _line(output, "MAME_LCD increment ")
    direct = _line(output, "MAME_LCD direct ")
    latch = _line(output, "MAME_LCD latch ")
    six = _line(output, "MAME_LCD six_bit ")
    mapping = _line(output, "MAME_LCD mapping ")
    try:
        return MameLcdReport(
            machine=identity["machine"],
            version=identity["version"],
            reset_status10=int(reset["status10"], 16),
            reset_status12=int(reset["status12"], 16),
            reset_port2=int(reset["port2"], 16),
            reset_ram_nonzero=int(reset["ram_nonzero"], 10),
            reset_x=int(reset["x"], 16),
            reset_y=int(reset["y"], 16),
            reset_z=int(reset["z"], 16),
            reset_output=int(reset["output"], 16),
            reset_word=int(reset["word"], 16),
            reset_display=int(reset["display"], 16),
            reset_active=int(reset["active"], 16),
            reset_direction=int(reset["direction"], 10),
            rapid_status=_bytes(control["rapid_status"], 4, "rapid status"),
            movement_status=_bytes(control["movement_status"], 4, "movement status"),
            six_status=int(control["six_status"], 16),
            eight_status=int(control["eight_status"], 16),
            mirror_off_status=int(control["mirror_off_status"], 16),
            mirror_on_status=int(control["mirror_on_status"], 16),
            contrast=int(control["contrast"], 16),
            opa1=int(control["opa1"], 16),
            opa2=int(control["opa2"], 16),
            z=int(control["z"], 16),
            increment_cells=_bytes(increment["cells"], 4, "increment cells"),
            increment_final_x=int(increment["final_x"], 16),
            increment_final_y=int(increment["final_y"], 16),
            direct_column15_cell=int(direct["column15_cell"], 16),
            direct_column15_final_y=int(direct["column15_final_y"], 16),
            direct_column31_cell=int(direct["column31_cell"], 16),
            direct_column31_final_y=int(direct["column31_final_y"], 16),
            latch_reads=_bytes(latch["reads"], 3, "latch reads"),
            latch_final_x=int(latch["final_x"], 16),
            latch_final_y=int(latch["final_y"], 16),
            six_cells=_bytes(six["cells"], 2, "six-bit cells"),
            six_final_y=int(six["final_y"], 16),
            delay_initial=_bytes(mapping["delay_initial"], 7, "delay block"),
            delay_patterned=_bytes(mapping["delay_patterned"], 7, "delay block"),
            ready=int(mapping["ready"], 16),
        )
    except KeyError as error:
        raise MameRuntimeError(
            f"MAME LCD report omits field {error.args[0]}"
        ) from error
    except MameRuntimeError:
        raise
    except ValueError as error:
        raise MameRuntimeError("invalid numeric MAME LCD report field") from error


def expected_mame_lcd_report() -> MameLcdReport:
    """Return exact observations derived from the reusable MAME LCD model."""

    increment = walk_lcd_transfers("MAME", row=0, column=14, movement=7, count=4)
    direct15 = walk_lcd_transfers("MAME", row=0, column=15, movement=7, count=1)[0]
    direct31 = walk_lcd_transfers("MAME", row=0, column=31, movement=7, count=1)[0]
    return MameLcdReport(
        machine="ti84pv3",
        version=MAME_VERSION,
        reset_status10=lcd_status(word_length=8, display_on=False, movement=7),
        reset_status12=lcd_status(word_length=8, display_on=False, movement=7),
        reset_port2=0xC3,
        reset_ram_nonzero=0,
        reset_x=0,
        reset_y=0,
        reset_z=0,
        reset_output=0,
        reset_word=1,
        reset_display=0,
        reset_active=1,
        reset_direction=1,
        rapid_status=(lcd_status(word_length=8, display_on=True, movement=7),) * 4,
        movement_status=tuple(
            lcd_status(word_length=8, display_on=True, movement=movement)
            for movement in range(4, 8)
        ),
        six_status=lcd_status(word_length=6, display_on=True, movement=7),
        eight_status=lcd_status(word_length=8, display_on=True, movement=7),
        mirror_off_status=lcd_status(word_length=8, display_on=False, movement=7),
        mirror_on_status=lcd_status(word_length=8, display_on=True, movement=7),
        contrast=0x2F,
        opa1=3,
        opa2=3,
        z=0x3F,
        increment_cells=(0xA0, 0xA1, 0xA2, 0xA3),
        increment_final_x=increment[-1].next_row,
        increment_final_y=increment[-1].next_column,
        direct_column15_cell=0xB5,
        direct_column15_final_y=direct15.next_column,
        direct_column31_cell=0xBF,
        direct_column31_final_y=direct31.next_column,
        latch_reads=read_latch_sequence((0x12, 0x34, 0x56)),
        latch_final_x=2,
        latch_final_y=3,
        six_cells=(0xFD, 0x50),
        six_final_y=2,
        delay_initial=(0,) * 7,
        delay_patterned=(0,) * 7,
        ready=0xC3,
    )


def validate_mame_lcd_report(report: MameLcdReport) -> dict[str, object]:
    """Require the native values implied by MAME 0.287's pinned source."""

    expected = expected_mame_lcd_report()
    if report != expected:
        raise MameRuntimeError("MAME LCD report disagrees with the 0.287 source model")
    profile = lcd_emulator_profile("MAME")
    direct15 = walk_lcd_transfers("MAME", row=0, column=15, movement=7, count=1)[0]
    direct31 = walk_lcd_transfers("MAME", row=0, column=31, movement=7, count=1)[0]
    return {
        "source_model": {
            "device": "generic T6A04",
            "row_stride": profile.row_stride,
            "ram_size": profile.ram_size,
            "busy_model": profile.busy_model,
            "asic_ready_model": profile.asic_ready_model,
            "mirror_ports": profile.mirrors_12_13,
            "column_15_array_index": direct15.array_index,
            "column_31_array_index": direct31.array_index,
            "unsafe_row63_column31_executed": False,
            "unsafe_row63_column31_array_index": 63 * profile.row_stride + 31,
            "delay_ports": list(range(0x29, 0x30)),
        },
        "native": report.to_dict(),
    }
