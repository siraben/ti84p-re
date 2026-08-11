"""Typed report and source oracle for the pinned TilEm Flash probe."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from dataclasses import fields as dataclass_fields
from pathlib import Path

from tilem_core import TilemCoreError, run_probe

REPORT_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")
TilemFlashError = TilemCoreError

FLASH_STATES = {
    0: "read",
    1: "aa",
    2: "55",
    3: "program",
    4: "erase",
    5: "erase-aa",
    6: "erase-55",
    7: "error",
    8: "fast",
    9: "fast-program",
    10: "fast-exit",
}

FLASH_BUSY_STATES = {
    0: "idle",
    1: "program",
    2: "erase-window",
    3: "erase",
}

EXPECTED_DIAGNOSTICS = (
    "TilEm warning: Flash error (autoselect is not implemented)",
    "TilEm warning: Flash error (undefined command b0->020100 after pre-erase AA,55)",
    "TilEm warning: Flash error (bad program d0 over 50)",
    "TilEm message: Erasing Flash sector at 020100",
    "TilEm message: Erasing entire Flash chip",
    "TilEm message: Erasing entire Flash chip",
)


@dataclass(frozen=True)
class TilemFlashReport:
    """Stable fields emitted by the direct TilEm Flash-command probe."""

    flash_size: int
    sector_count: int
    locked_state: int
    locked_byte: int
    autoselect_state: int
    autoselect_byte: int
    partial_state_before_reset: int
    partial_reset_state: int
    cfi_state: int
    cfi_byte: int
    suspend_window_state: int
    suspend_state: int
    resume_state: int
    suspend_changed: int
    fast_entry_state: int
    fast_first_select_state: int
    fast_first_stored: int
    fast_after_first_state: int
    fast_second_select_state: int
    fast_second_stored: int
    fast_after_second_state: int
    fast_exit_select_state: int
    fast_exit_state: int
    legal_state: int
    legal_busy: int
    legal_timer: int
    legal_stored: int
    legal_reads: tuple[int, ...]
    legal_final_busy: int
    legal_final_read: int
    illegal_initial_state: int
    illegal_initial_busy: int
    illegal_timer: int
    illegal_stored: int
    illegal_busy_reads: tuple[int, ...]
    illegal_error_state: int
    illegal_error_reads: tuple[int, ...]
    illegal_reset_state: int
    illegal_final_read: int
    sector_start: int
    sector_size: int
    sector_state: int
    sector_busy: int
    sector_wait_timer: int
    sector_progaddr: int
    sector_erased: int
    sector_changed: int
    sector_outside_changed: int
    erase_wait_reads: tuple[int, ...]
    erase_busy: int
    sector_erase_timer: int
    erase_busy_reads: tuple[int, ...]
    sector_final_busy: int
    sector_final_read: int
    chip_default_non_ff: int
    chip_default_changed: int
    chip_default_b_byte: int
    chip_default_boot_byte: int
    chip_default_state: int
    chip_default_busy: int
    chip_default_timer: int
    chip_default_progaddr: int
    chip_override_non_ff: int
    chip_override_changed: int
    chip_override_boot_byte: int
    chip_override_state: int
    chip_override_busy: int
    chip_override_timer: int
    chip_override_progaddr: int
    diagnostics: tuple[str, ...] = ()
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_hex_vector(value: str, name: str) -> tuple[int, ...]:
    values = tuple(int(item, 16) for item in value.split(","))
    if len(values) != 2:
        raise ValueError(f"{name} must contain two values")
    return values


def parse_flash_report(line: str) -> TilemFlashReport:
    """Parse one direct TilEm Flash command and status report."""

    raw = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    field_names = {
        field.name
        for field in dataclass_fields(TilemFlashReport)
        if field.name not in {"diagnostics", "binary_sha256"}
    }
    missing = sorted({"mode", *field_names} - raw.keys())
    if missing:
        raise TilemFlashError("native TilEm Flash report omits " + ", ".join(missing))
    if raw["mode"] != "tilem-flash-probe":
        raise TilemFlashError(f"unexpected TilEm Flash mode {raw['mode']!r}")
    vectors = {
        "legal_reads",
        "illegal_busy_reads",
        "illegal_error_reads",
        "erase_wait_reads",
        "erase_busy_reads",
    }
    try:
        values: dict[str, object] = {
            name: _parse_hex_vector(raw[name], name)
            if name in vectors
            else int(raw[name], 0)
            for name in field_names
        }
        return TilemFlashReport(**values)
    except (TypeError, ValueError) as error:
        raise TilemFlashError(
            f"invalid native TilEm Flash report: {line.strip()}"
        ) from error


def expected_flash_values() -> dict[str, object]:
    """Return exact native observations implied by the pinned source model."""

    return {
        "flash_size": 0x100000,
        "sector_count": 19,
        "locked_state": 0,
        "locked_byte": 0xFF,
        "autoselect_state": 0,
        "autoselect_byte": 0xFF,
        "partial_state_before_reset": 1,
        "partial_reset_state": 0,
        "cfi_state": 0,
        "cfi_byte": 0xFF,
        "suspend_window_state": 6,
        "suspend_state": 0,
        "resume_state": 0,
        "suspend_changed": 0,
        "fast_entry_state": 8,
        "fast_first_select_state": 9,
        "fast_first_stored": 0x50,
        "fast_after_first_state": 8,
        "fast_second_select_state": 9,
        "fast_second_stored": 0xA0,
        "fast_after_second_state": 8,
        "fast_exit_select_state": 10,
        "fast_exit_state": 0,
        "legal_state": 0,
        "legal_busy": 1,
        "legal_timer": 42,
        "legal_stored": 0x50,
        "legal_reads": (0x80, 0xC0),
        "legal_final_busy": 0,
        "legal_final_read": 0x50,
        "illegal_initial_state": 7,
        "illegal_initial_busy": 1,
        "illegal_timer": 42,
        "illegal_stored": 0x50,
        "illegal_busy_reads": (0x00, 0x40),
        "illegal_error_state": 7,
        "illegal_error_reads": (0x20, 0x60),
        "illegal_reset_state": 0,
        "illegal_final_read": 0x50,
        "sector_start": 0x20000,
        "sector_size": 0x10000,
        "sector_state": 0,
        "sector_busy": 2,
        "sector_wait_timer": 300,
        "sector_progaddr": 0x20000,
        "sector_erased": 0x10000,
        "sector_changed": 0x10000,
        "sector_outside_changed": 0,
        "erase_wait_reads": (0x00, 0x44),
        "erase_busy": 3,
        "sector_erase_timer": 1_200_000,
        "erase_busy_reads": (0x08, 0x4C),
        "sector_final_busy": 0,
        "sector_final_read": 0xFF,
        "chip_default_non_ff": 0x14000,
        "chip_default_changed": 0xEC000,
        "chip_default_b_byte": 0,
        "chip_default_boot_byte": 0,
        "chip_default_state": 0,
        "chip_default_busy": 2,
        "chip_default_timer": 300,
        "chip_default_progaddr": 0xFA000,
        "chip_override_non_ff": 0,
        "chip_override_changed": 0x100000,
        "chip_override_boot_byte": 0xFF,
        "chip_override_state": 0,
        "chip_override_busy": 2,
        "chip_override_timer": 300,
        "chip_override_progaddr": 0xFC000,
        "diagnostics": EXPECTED_DIAGNOSTICS,
    }


def validate_flash_report(report: TilemFlashReport) -> dict[str, object]:
    """Check native Flash observations against the pinned TilEm source model."""

    expected = expected_flash_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise TilemFlashError(
            "native TilEm Flash report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "states": FLASH_STATES,
            "busy_states": FLASH_BUSY_STATES,
            "timer_inputs_microseconds": {
                "program": 7,
                "erase_window": 50,
                "erase": 200_000,
            },
            "timer_deadlines_at_reset_speed_clocks": {
                "program": 42,
                "erase_window": 300,
                "erase": 1_200_000,
            },
            "program_rule": "stored &= requested",
            "illegal_program_order": (
                "program-busy DQ7/DQ6 status precedes persistent DQ5/DQ6 error status"
            ),
            "default_protected_ranges": [[0xB0000, 0xC0000], [0xFC000, 0x100000]],
            "unimplemented_commands": ["autoselect", "CFI", "erase suspend"],
            "timer_transition_scope": (
                "the probe reads each scheduler deadline, removes the timer as "
                "TilEm does on expiry, and invokes the registered Flash callback"
            ),
            "direct_seed_scope": (
                "the probe calls libtilemcore Flash entry points on synthetic memory; "
                "it does not execute TI-OS or model physical Flash"
            ),
        },
        "native": observed,
    }


def run_flash_probe(binary: Path) -> TilemFlashReport:
    """Run the direct command/status matrix through one built TilEm probe."""

    completed = run_probe(binary, ["--flash-probe"])
    report = parse_flash_report(completed.stdout)
    return TilemFlashReport(
        **{
            **report.to_dict(),
            "diagnostics": completed.stderr_lines,
            "binary_sha256": completed.binary_sha256,
        }
    )
