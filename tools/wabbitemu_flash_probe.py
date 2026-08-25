"""Reusable cases and oracles for native Wabbitemu Flash probes."""

from __future__ import annotations

from dataclasses import dataclass
import json

from execution_protection import TI84P_BOOT_PROTECTION
from flash_hardware import (
    PAGE_SIZE,
    flash_sector,
    program_byte,
    simulate_wabbitemu_rom_program_poll,
    wabbitemu_program_error_read,
)
from wabbitemu_headless import (
    WabbitemuFlashCommandReport,
    WabbitemuFlashPreflightReport,
    WabbitemuFlashProgramReport,
    WabbitemuFlashWorkerReport,
    WabbitemuHeadlessError,
)

ARCHIVE_FLASH_START = 0x08 * PAGE_SIZE
ARCHIVE_FLASH_END = 0x2A * PAGE_SIZE
FAILURE_FIXTURE_PAGE = 0x08
FAILURE_FIXTURE_OFFSET = 0x0100
FAILURE_FIXTURE_PHYSICAL = 0x20100
FAILURE_FIXTURE_SECTOR = (0x20000, 0x30000)


@dataclass(frozen=True)
class FlashProgramCase:
    """One initial byte, requested byte, and initial DQ6 toggle state."""

    initial: int
    requested: int
    initial_toggle: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.initial <= 0xFF or not 0 <= self.requested <= 0xFF:
            raise ValueError("Flash program bytes must be between 0 and 255")
        if self.initial_toggle not in (0, 0x40):
            raise ValueError("initial DQ6 toggle must be 0 or 0x40")

    @property
    def name(self) -> str:
        return (
            f"old-{self.initial:02x}-requested-{self.requested:02x}-"
            f"toggle-{self.initial_toggle:02x}"
        )


DIRECT_PROGRAM_CASES = (
    FlashProgramCase(0xFF, 0x50),
    FlashProgramCase(0x50, 0x40),
    FlashProgramCase(0x80, 0x00),
    FlashProgramCase(0x50, 0xD0),
    FlashProgramCase(0x50, 0xD0, 0x40),
    FlashProgramCase(0x00, 0x80),
    FlashProgramCase(0x00, 0x01),
)

WORKER_PROGRAM_CASES = (
    FlashProgramCase(0xFF, 0x50),
    FlashProgramCase(0x00, 0x01),
    FlashProgramCase(0x20, 0xA0),
    FlashProgramCase(0x50, 0xD0),
    FlashProgramCase(0x50, 0xD0, 0x40),
)


def validate_failure_fixture_target(
    page: int,
    offset: int,
    physical: int,
) -> dict[str, object]:
    """Require the one disposable archive-sector byte allowed by the fixture."""

    expected = (
        FAILURE_FIXTURE_PAGE,
        FAILURE_FIXTURE_OFFSET,
        FAILURE_FIXTURE_PHYSICAL,
    )
    if (page, offset, physical) != expected:
        raise WabbitemuHeadlessError(
            "Flash failure fixture target is not the fixed disposable archive byte"
        )
    if physical != page * PAGE_SIZE + offset:
        raise WabbitemuHeadlessError(
            "Flash failure fixture page, offset, and physical address disagree"
        )
    sector = flash_sector(physical)
    if (sector.start, sector.end) != FAILURE_FIXTURE_SECTOR:
        raise WabbitemuHeadlessError(
            "Flash failure fixture target is outside its fixed 64 KiB sector"
        )
    if sector.start < ARCHIVE_FLASH_START or sector.end > ARCHIVE_FLASH_END:
        raise WabbitemuHeadlessError(
            "Flash failure fixture sector overlaps OS, certificate, or boot pages"
        )
    return {
        "target_page": page,
        "target_offset": offset,
        "target_physical": physical,
        "sector": [sector.start, sector.end],
        "archive_writable_window": [ARCHIVE_FLASH_START, ARCHIVE_FLASH_END],
        "source_image_written": False,
    }


def parse_flash_program_case(value: str) -> FlashProgramCase:
    """Parse ``INITIAL:REQUESTED[:TOGGLE]`` with prefixed integers."""

    fields = value.split(":")
    if len(fields) not in (2, 3):
        raise ValueError("case must have INITIAL:REQUESTED[:TOGGLE] form")
    try:
        values = [int(field, 0) for field in fields]
        return FlashProgramCase(*values)
    except ValueError as error:
        raise ValueError(
            "case must have INITIAL:REQUESTED[:TOGGLE] form"
        ) from error


def _check_expected(
    case: FlashProgramCase,
    observed: dict[str, object],
    expected: dict[str, object],
    mode: str,
) -> None:
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            f"{case.name}: native {mode} report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )


def validate_program_report(
    case: FlashProgramCase,
    report: WabbitemuFlashProgramReport,
) -> dict[str, object]:
    """Check a direct command-state report against the source model."""

    modeled = program_byte("Wabbitemu", case.initial, case.requested)
    expected_error = modeled.requested_zero_to_one
    expected_first = (
        wabbitemu_program_error_read(
            case.requested,
            dq6=bool(case.initial_toggle),
        )
        if expected_error
        else modeled.stored
    )
    expected_toggle_after_first = (
        case.initial_toggle ^ 0x40 if expected_error else case.initial_toggle
    )
    expected = {
        "target_page": 0x08,
        "target_offset": 0x0100,
        "target_address": 0x4100,
        "target_physical": 0x20100,
        "original_rom_byte": 0xFF,
        "configured_flash_locked": False,
        "initial": case.initial,
        "requested": case.requested,
        "initial_toggle": case.initial_toggle,
        "command_writes": 4,
        "stored": modeled.stored,
        "step_after_write": "read",
        "error_after_write": expected_error,
        "toggle_after_write": case.initial_toggle,
        "first_read": expected_first,
        "error_after_first": False,
        "toggle_after_first": expected_toggle_after_first,
        "second_read": modeled.stored,
        "error_after_second": False,
        "toggle_after_second": expected_toggle_after_first,
        "tstates": 0,
    }
    observed = report.to_dict()
    _check_expected(case, observed, expected, "command-state")
    return {
        "name": case.name,
        "requested_zero_to_one": modeled.requested_zero_to_one,
        "source_model": {
            "stored": modeled.stored,
            "poll_behavior": modeled.poll_behavior,
            "first_read": expected_first,
            "second_read": modeled.stored,
        },
        "native": observed,
    }


def validate_command_report(
    report: WabbitemuFlashCommandReport,
) -> dict[str, object]:
    """Check native command-family behavior against the pinned source model."""

    expected = {
        "flash_size": 0x100000,
        "flash_version": 3,
        "configured_flash_locked": False,
        "initial_step": "read",
        "autoselect_entry_step": "autoselect",
        "autoselect_maker": 0x01,
        "autoselect_device": 0xDA,
        "autoselect_protection": 0,
        "autoselect_reset_step": "read",
        "autoselect_array_byte": 0xFF,
        "partial_step_before_reset": "aa",
        "partial_reset_step": "read",
        "cfi_step": "read",
        "cfi_changed_bytes": 0,
        "suspend_window_step": "erase-55",
        "suspend_step": "read",
        "suspend_changed_bytes": 0,
        "resume_step": "read",
        "resume_changed_bytes": 0,
        "fast_entry_step": "fast",
        "fast_first_select_step": "fast-program",
        "fast_first_initial": 0xF0,
        "fast_first_requested": 0x50,
        "fast_first_stored": 0x50,
        "fast_after_first_step": "fast",
        "fast_second_select_step": "fast-program",
        "fast_second_initial": 0xAA,
        "fast_second_requested": 0xA0,
        "fast_second_stored": 0xA0,
        "fast_after_second_step": "fast",
        "fast_exit_select_step": "fast-exit",
        "fast_exit_step": "read",
        "sector_target_page": 0x08,
        "sector_target_address": 0x4100,
        "sector_start": 0x20000,
        "sector_size": 0x10000,
        "sector_step": "read",
        "sector_erased_bytes": 0x10000,
        "sector_changed_bytes": 0x10000,
        "sector_outside_changed_bytes": 0,
        "chip_step": "read",
        "chip_non_ff_after": 0,
        "chip_boot_before": 0,
        "chip_boot_after": 0xFF,
        "tstates": 0,
    }
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if report.chip_non_ff_before <= 0:
        disagreements["chip_non_ff_before"] = {
            "expected": "positive",
            "observed": report.chip_non_ff_before,
        }
    if report.chip_changed_bytes != report.chip_non_ff_before:
        disagreements["chip_changed_bytes"] = {
            "expected": report.chip_non_ff_before,
            "observed": report.chip_changed_bytes,
        }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native Flash command report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "autoselect_ids": [0x01, 0xDA],
            "fast_program_stored": [0x50, 0xA0],
            "sector_range": [0x20000, 0x30000],
            "chip_erase_fills_complete_array": True,
            "erase_suspend_state": False,
            "cfi_query_state": False,
        },
        "native": observed,
    }


def validate_worker_report(
    case: FlashProgramCase,
    report: WabbitemuFlashWorkerReport,
) -> dict[str, object]:
    """Check a retail-ROM worker report against byte and source models."""

    target_guard = validate_failure_fixture_target(
        report.target_page,
        report.target_offset,
        report.target_physical,
    )
    modeled = simulate_wabbitemu_rom_program_poll(
        case.initial,
        case.requested,
        initial_error_dq6=bool(case.initial_toggle),
    )
    illegal = modeled.requested_zero_to_one
    success = modeled.outcome == "success"
    expected = {
        "target_page": 0x08,
        "target_offset": 0x0100,
        "target_address": 0x4100,
        "target_physical": 0x20100,
        "original_rom_byte": 0xFF,
        "initial": case.initial,
        "requested": case.requested,
        "initial_toggle": case.initial_toggle,
        "boot_steps": 134_845,
        "boot_tstates": 1_746_999,
        "boot_pc": 0x4223,
        "boot_page": "3F",
        "boot_flash_locked": True,
        "boot_flash_lower": TI84P_BOOT_PROTECTION.flash_lower,
        "boot_flash_upper": TI84P_BOOT_PROTECTION.flash_upper,
        "configured_flash_locked": False,
        "source_page": 0x01,
        "source_address": 0x9D99,
        "harness_size": 4,
        "return_address": 0x9D98,
        "probe_steps": 348 if not illegal else 355 if success else 347,
        "probe_tstates": 5_375 if not illegal else 5_425 if success else 5_379,
        "bcall_visits": 1,
        "worker_entry_visits": 1,
        "program_write_visits": 1,
        "dq7_read_visits": 1,
        "final_dq7_read_visits": 1 if illegal else 0,
        "success_reset_visits": 1 if success else 0,
        "failure_reset_visits": 0 if success else 1,
        "return_visits": 1,
        "violation_resets": 0,
        "poll_reads": tuple(read.value for read in modeled.reads),
        "stored": modeled.stored,
        "flash_step": "read",
        "flash_error": False,
        "flash_toggle": (
            case.initial_toggle ^ 0x40 if illegal else case.initial_toggle
        ),
        "return_af": 0x0044 if success else 0x3F2C,
        "return_bc": 0,
        "return_de": 0x4101 if success else 0x4100,
        "return_hl": 0x9D9A if success else 0x9D99,
        "port06": 0x3F,
        "bank1_page": "3F",
        "flash_changed_bytes": int(modeled.stored != 0xFF),
        "target_sector_changed_bytes": int(modeled.stored != 0xFF),
        "protected_changed_bytes": 0,
        "outside_target_changed_bytes": 0,
        "final_pc": 0x9D98,
        "classification": modeled.outcome,
    }
    observed = report.to_dict()
    _check_expected(case, observed, expected, "retail-worker")
    if report.max_probe_steps <= report.probe_steps:
        raise WabbitemuHeadlessError(
            f"{case.name}: retail worker did not return within its step bound"
        )
    return {
        "name": case.name,
        "requested_zero_to_one": modeled.requested_zero_to_one,
        "target_guard": target_guard,
        "source_model": {
            "stored": modeled.stored,
            "reads": [read.value for read in modeled.reads],
            "outcome": modeled.outcome,
        },
        "native": observed,
    }


def validate_flash_preflight_report(
    report: WabbitemuFlashPreflightReport,
) -> dict[str, object]:
    """Check the locked bad-stack reset path and completed retail restart."""

    expected = {
        "status": 0,
        "preflight_address": 0x02BF,
        "failure_address": 0x02CE,
        "reset_address": 0x0000,
        "configured_sp": 0xBFFE,
        "signature_size": 18,
        "source_signature_match": True,
        "mapped_signature_match": True,
        "boot_pc": 0x4223,
        "boot_page": "3F",
        "boot_flash_locked": True,
        "harness_visits": 1,
        "preflight_visits": 1,
        "failure_visits": 1,
        "reset_visits": 1,
        "return_visits": 0,
        "violation_resets": 0,
        "gate_locked_before_restart": True,
        "step_before_restart": "read",
        "flash_changed_before_restart": 0,
        "restart_reset_pc": 0x0000,
        "restart_pc": 0x4223,
        "restart_page": "3F",
        "restart_ready": True,
        "flash_changed_after_restart": 0,
    }
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if report.boot_steps <= 0 or report.boot_tstates <= 0:
        disagreements["boot_progress"] = {
            "expected": "positive instruction and T-state counts",
            "observed": [report.boot_steps, report.boot_tstates],
        }
    if report.probe_steps >= report.max_probe_steps:
        disagreements["probe_step_bound"] = {
            "expected": f"less than {report.max_probe_steps}",
            "observed": report.probe_steps,
        }
    if not 0 < report.restart_steps < report.max_restart_steps:
        disagreements["restart_step_bound"] = {
            "expected": f"between 1 and {report.max_restart_steps - 1}",
            "observed": report.restart_steps,
        }
    if report.restart_tstates <= 0:
        disagreements["restart_tstates"] = {
            "expected": "positive",
            "observed": report.restart_tstates,
        }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native Flash preflight report disagrees with the guarded path: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "numeric_status": report.status,
        "source_model": {
            "failure_condition": "saved SP high bits are not 0xC0",
            "failure_transfer": "00:02CE jumps to 00:0000",
            "gate_unlocks": 0,
            "flash_changes": 0,
            "restart_completed": True,
        },
        "native": observed,
    }
