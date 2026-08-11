"""Reusable oracle for the native Wabbitemu LCD and bus-timing probe."""

from __future__ import annotations

from dataclasses import asdict
import json

from bus_timing import BusTiming, TimingImplementation
from lcd_controller import (
    lcd_emulator_profile,
    lcd_status,
    read_latch_sequence,
    walk_lcd_transfers,
)
from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuLcdReport


LCD_TRANSFER_GUARD = 60


def expected_lcd_values() -> dict[str, object]:
    """Return the pinned source-model value for every native LCD case."""

    profile = lcd_emulator_profile("Wabbitemu")
    increment = walk_lcd_transfers(
        "Wabbitemu", row=0, column=14, movement=7, count=4
    )
    direct = walk_lcd_transfers(
        "Wabbitemu", row=1, column=15, movement=7, count=1
    )[0]
    alias = walk_lcd_transfers(
        "Wabbitemu", row=1, column=31, movement=7, count=1
    )[0]
    latch = walk_lcd_transfers(
        "Wabbitemu", row=2, column=0, movement=7, count=3
    )

    timing = BusTiming(speed_mode=1, port2a=0, port2f=3)
    ready_hold = timing.lcd_ready_hold()
    timing.write_port(0x2A, 0x27)
    timing.write_port(0x2E, 0x45)
    waits = timing.memory_waits()
    implementation = TimingImplementation(profile="wabbitemu")
    implementation.write_port(0x20, 3)

    # lcd_reset stores word_len=8, although lcd_status shifts it as a Boolean.
    # The reset-state transfer mode is 8-bit, but the emitted status lacks bit 6.
    reset_status = lcd_status(
        word_length=8, display_on=True, movement=7
    ) & ~0x40
    configured_status = lcd_status(
        word_length=8, display_on=True, movement=7
    )
    return {
        "configured_lcd_delay": LCD_TRANSFER_GUARD,
        "port12_active": profile.mirrors_12_13,
        "port12_read_accepted": False,
        "port12_read": 0xFF,
        "port13_active": profile.mirrors_12_13,
        "port13_read_accepted": False,
        "port13_read": 0xFF,
        "early_status": 0x80,
        "boundary_status": reset_status,
        "status_last_tstate": LCD_TRANSFER_GUARD,
        "early_write_cell": 0,
        "early_write_column": increment[1].requested_column,
        "wrap_column14": 0xA0,
        "wrap_column15": 0,
        "wrap_column0": 0xA1,
        "wrap_column1": 0xA2,
        "wrap_column2": 0xA3,
        "wrap_final_column": increment[-1].next_column,
        "direct_column15": 0xB5,
        "alias_column31": 0xBF,
        "alias_final_column": alias.next_column,
        "latch_reads": read_latch_sequence((0x12, 0x34, 0)),
        "latch_read_tstates": 1380,
        "latch_last_tstate": 1320,
        "latch_final_column": latch[-1].next_column,
        "ready_field": timing.port2f_field(),
        "ready_hold": ready_hold,
        "ready_last_tstate": 2000,
        "ready_at_240": 0xE1,
        "ready_at_241": 0xE3,
        "accepted_status_read": configured_status,
        "ready_after_read_last_tstate": 2000,
        "ready_after_read": 0xE3,
        "delay_register": 0x27,
        "delay_before": 3000,
        "delay_after": 3000 + timing.lcd_access_wait(),
        "delayed_status": configured_status,
        "flash_opcode_wait": bool(waits.flash_opcode),
        "flash_read_wait": bool(waits.flash_read),
        "flash_write_wait": bool(waits.flash_write),
        "ram_opcode_wait": bool(waits.ram_opcode),
        "ram_read_wait": bool(waits.ram_read),
        "ram_write_wait": bool(waits.ram_write),
        "requested_speed": 3,
        "clamped_speed": implementation.decoder.speed_mode,
        "timer_version": 0,
    }


def validate_lcd_report(report: WabbitemuLcdReport) -> dict[str, object]:
    """Check native LCD and bus observations against reusable source models."""

    expected = expected_lcd_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native LCD report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    direct = walk_lcd_transfers(
        "Wabbitemu", row=1, column=15, movement=7, count=1
    )[0]
    alias = walk_lcd_transfers(
        "Wabbitemu", row=1, column=31, movement=7, count=1
    )[0]
    timing = BusTiming(speed_mode=1, port2a=0x27, port2e=0x45, port2f=3)
    return {
        "source_model": {
            "controller_guard_tstates": LCD_TRANSFER_GUARD,
            "reset_status_quirk": (
                "word_len resets to 8 but status treats it as a Boolean, yielding 0x23"
            ),
            "ports_12_13": "unmapped",
            "increment_columns": "14, 0, 1, 2",
            "direct_column_15_index": direct.array_index,
            "column_31_alias_index": alias.array_index,
            "read_latch": "one accepted transfer behind controller RAM",
            "ready_formula": "48 + 64 * field",
            "ready_hold_tstates": timing.lcd_ready_hold(),
            "accepted_reads_update_write_timestamp": False,
            "delay_and_waits": {
                "delay_port": timing.active_delay_port()[0],
                "delay_value": timing.active_delay_port()[1],
                "lcd_access_wait": timing.lcd_access_wait(),
                "memory_waits": asdict(timing.memory_waits()),
            },
            "default_speed_modes": [0, 1],
        },
        "native": observed,
    }
