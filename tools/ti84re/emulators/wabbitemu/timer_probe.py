"""Reusable oracle for the native Wabbitemu timer and RTC edge probe."""

from __future__ import annotations

import json

from ti84re.hardware.timer import decode_timer_source, timer_duration, timer_expiry
from ti84re.emulators.wabbitemu.headless import WabbitemuHeadlessError, WabbitemuTimerReport


def expected_timer_values() -> dict[str, object]:
    """Return the pinned source-model value for every native timer case."""

    crystal = decode_timer_source("Wabbitemu", 0x41)
    cpu = decode_timer_source("Wabbitemu", 0x80)
    zero = timer_duration("Wabbitemu", 0x80, 0)
    ordinary_expiry = timer_expiry("Wabbitemu", 0x00)
    halted_expiry = timer_expiry("Wabbitemu", 0x02, halted=True)
    assert crystal is not None and cpu is not None
    return {
        "crystal_source": 0x41,
        "crystal_divisor": crystal.divisor,
        "crystal_elapsed_ticks": 320,
        "crystal_reads": (2, 1, 3),
        "crystal_status": ordinary_expiry.mode_read_after_expiry,
        "crystal_port4": 0x28,
        "cpu_source": 0x80,
        "cpu_divisor": cpu.divisor,
        "cpu_elapsed_tstates": 4,
        "cpu_count_read": 3,
        "cpu_status": ordinary_expiry.mode_read_after_expiry,
        "cpu_port4": 0x28,
        "zero_elapsed_tstates": zero.effective_counter_ticks + 1,
        "zero_count_read": 0,
        "zero_status": ordinary_expiry.mode_read_after_expiry,
        "zero_port4": 0x28,
        "acknowledged_status": 0,
        "acknowledged_port4": 0x08,
        "halted_count_read": 1,
        "halted_status": halted_expiry.mode_read_after_expiry,
        "interrupt_while_halted": False,
        "interrupt_after_resume": True,
        "rtc_initial": 0,
        "rtc_committed": 0x12345678,
        "rtc_running": 0x12345682,
        "rtc_frozen": 0x12345682,
        "rtc_late_disabled": 0x12345682,
        "final_elapsed": 100,
    }


def validate_timer_report(report: WabbitemuTimerReport) -> dict[str, object]:
    """Check native timer and RTC observations against the source model."""

    expected = expected_timer_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native timer report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "crystal_divisor_0x41": 32,
            "crystal_catch_up": "at most one decrement per device evaluation",
            "cpu_catch_up": "all elapsed divisors in one device evaluation",
            "counter_zero_ticks": 256,
            "first_underflow_sets_status_bit2": True,
            "halt_suppresses_interrupt_line": True,
            "pending_generation_survives_halt": True,
            "rtc_source": "emulated elapsed whole seconds plus stored base",
            "disabled_rtc_read": "frozen base",
        },
        "native": observed,
    }
