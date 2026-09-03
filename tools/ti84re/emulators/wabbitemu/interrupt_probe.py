"""Reusable oracle for the native Wabbitemu interrupt-controller probe."""

from __future__ import annotations

from fractions import Fraction
import json

from ti84re.hardware.interrupt_controller import (
    decode_port03,
    decode_port04_status,
    wabbitemu_standard_timer_period,
)
from ti84re.emulators.wabbitemu.headless import (
    WabbitemuHeadlessError,
    WabbitemuInterruptReport,
)


def _nanoseconds(period: Fraction) -> int:
    """Round a positive exact period like C ``llround``."""

    scaled = period * 1_000_000_000
    quotient, remainder = divmod(scaled.numerator, scaled.denominator)
    return quotient + int(remainder * 2 >= scaled.denominator)


def expected_interrupt_values() -> dict[str, object]:
    """Return the pinned source-model value for every native interrupt case."""

    powered_timer1 = decode_port03(0x0A)
    released = decode_port04_status(0x08)
    overdue = decode_port04_status(0x0A)
    completion = decode_port04_status(0xE8)
    return {
        "initial_mask": 0,
        "stored_mask": 0xFF,
        "on_latch_before_ack": True,
        "on_latch_after_ack": False,
        "mask_after_on_ack": 0xFE,
        "rate0_timer1_ns": _nanoseconds(wabbitemu_standard_timer_period(0x00)),
        "rate1_timer1_ns": _nanoseconds(wabbitemu_standard_timer_period(0x02)),
        "rate2_timer1_ns": _nanoseconds(wabbitemu_standard_timer_period(0x04)),
        "rate3_timer1_ns": _nanoseconds(wabbitemu_standard_timer_period(0x06)),
        "rate3_timer2_ns": _nanoseconds(
            wabbitemu_standard_timer_period(0x06, timer=2)
        ),
        "rate3_timer2_offset_ns": _nanoseconds(
            wabbitemu_standard_timer_period(0x06) / 4
        ),
        "exact_boundary_status": released.raw,
        "exact_boundary_interrupt": False,
        "after_boundary_status": overdue.raw,
        "after_boundary_interrupt": powered_timer1.standard_timer_1_enabled,
        "after_port3_ack_status": released.raw,
        "before_port2_ack_status": overdue.raw,
        "after_port2_ack_status": released.raw,
        "completion_status": completion.raw,
        "low_power_lcd_active": False,
        "restored_lcd_active": True,
        "tstates": 0,
    }


def validate_interrupt_report(
    report: WabbitemuInterruptReport,
) -> dict[str, object]:
    """Check native interrupt observations against reusable source models."""

    expected = expected_interrupt_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native interrupt report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "mask_readback": "complete stored byte",
            "on_acknowledgement": "port 0x03 bit 0 clear removes the latch",
            "timer_rates_hz": [512, 227, 158, 108],
            "timer_expiry_comparison": "elapsed interval > selected period",
            "port03_timer_acknowledgement": (
                "disabling an overdue timer catches its phase up in the same handler"
            ),
            "port02_timer_acknowledgement": "also catches overdue phases up",
            "completion_status": "programmable timers 1-3 set bits 5-7",
            "low_power_model": "halt plus port-0x03 bit 3 clear blanks LCD activity",
        },
        "native": observed,
    }
