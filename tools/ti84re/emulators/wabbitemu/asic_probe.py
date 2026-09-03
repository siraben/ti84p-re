"""Reusable oracle for the native Wabbitemu ASIC-control edge probe."""

from __future__ import annotations

import json

from ti84re.hardware.asic_control import (
    asic_implementation,
    decode_port02,
    decode_port15,
    implementation_port21_readback,
)
from ti84re.emulators.wabbitemu.headless import WabbitemuAsicReport, WabbitemuHeadlessError


def expected_asic_values() -> dict[str, object]:
    """Return the pinned source-model value for every native ASIC case."""

    implementation = asic_implementation("Wabbitemu")
    locked = decode_port02(0xE3)
    unlocked = decode_port02(0xE7)
    identity_v0 = decode_port15(0x44)
    identity_v2 = decode_port15(0x55)
    assert identity_v0 is not None and identity_v2 is not None
    return {
        "initial_flash_locked": True,
        "port02_locked": locked.raw,
        "port02_unlocked": unlocked.raw,
        "port15_ram_v0": identity_v0.value,
        "port15_ram_v2": identity_v2.value,
        "port39_active": 0x39 in implementation.mapped_ports,
        "port39_read_accepted": False,
        "port39_read": 0xFF,
        "port3a_active": 0x3A in implementation.mapped_ports,
        "port3a_initial": 0,
        "port3a_first_written": 0xA5,
        "port3a_first_read": 0xA5,
        "port3a_second_written": 0x5A,
        "port3a_second_read": 0x5A,
        "port21_active": 0x21 in implementation.mapped_ports,
        "port21_protected": True,
        "locked_write_accepted": False,
        "locked_read": 0,
        "locked_internal_mode": 0,
        "locked_model_bits": 0,
        "mode3_write_accepted": True,
        "mode3_written": 0x30,
        "mode3_read": implementation_port21_readback("Wabbitemu", 0x30),
        "mode3_internal_mode": 3,
        "mode3_model_bits": 0,
        "group3_write_accepted": True,
        "group3_written": 0x03,
        "group3_read": implementation_port21_readback("Wabbitemu", 0x03),
        "group3_internal_mode": 0,
        "group3_model_bits": 3,
        "combined_write_accepted": True,
        "combined_written": 0x33,
        "combined_read": implementation_port21_readback("Wabbitemu", 0x33),
        "combined_internal_mode": 3,
        "combined_model_bits": 3,
        "tstates": 0,
    }


def validate_asic_report(report: WabbitemuAsicReport) -> dict[str, object]:
    """Check native ASIC-control observations against the source model."""

    expected = expected_asic_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native ASIC report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "port02_locked": "battery high, LCD ready, Flash locked, bits 5-7 set",
            "port02_unlocked": "locked status plus bit 2",
            "port15_ram_version_0": "0x44",
            "port15_ram_version_2": "0x55",
            "port21_write_gate": "accepted only while Flash is unlocked",
            "port21_internal_fields": "bits 0-1 and bits 4-5",
            "port21_readback": "internal mode is shifted right by four again",
            "port39": "unmapped",
            "port3a": "byte latch",
        },
        "native": observed,
    }
