"""Oracle for direct-entry execution of retail-ROM LCD diagnostic helpers."""

from __future__ import annotations

import json

from boot_lcd_diagnostic import fnv1a64, visible_pattern
from wabbitemu_headless import (
    WabbitemuHeadlessError,
    WabbitemuLcdDiagnosticReport,
)


def expected_lcd_diagnostic_values() -> dict[str, object]:
    """Return stable values expected from the injected direct-entry harness."""

    fill = visible_pattern(0x55, 0xAA)
    line = fill[:-12] + bytes((0xFF,)) * 12
    return {
        "probe_size": 30,
        "init_visits": 1,
        "fill_visits": 1,
        "line_visits": 1,
        "contrast_visits": 2,
        "init_commands": 7,
        "init_data": 0,
        "fill_commands": 24,
        "fill_data": 768,
        "line_commands": 24,
        "line_data": 12,
        "contrast_commands": 1,
        "contrast_data": 0,
        "command_writes": 56,
        "data_writes": 780,
        "init_active": True,
        "init_word_length": 1,
        "init_cursor_mode": 1,
        "fill_hash": fnv1a64(fill),
        "line_hash": fnv1a64(line),
        "fill_row0_col0": 0x55,
        "fill_row1_col0": 0xAA,
        "fill_row0_col11": 0x55,
        "fill_row0_col12": 0x00,
        "line_row63_col0": 0xFF,
        "line_row63_col11": 0xFF,
        "line_row62_col0": 0x55,
        "contrast_out": 0xFF,
        "contrast_level": 39,
        "violation_resets": 0,
        "completed": True,
        "final_pc": 0x9DB3,
    }


def validate_lcd_diagnostic_report(
    report: WabbitemuLcdDiagnosticReport,
) -> dict[str, object]:
    """Check native observations against the decoded helper model."""

    expected = expected_lcd_diagnostic_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "retail LCD helper execution disagrees with the decoded model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "decoded_model": expected,
        "native": observed,
    }
