"""Oracle for controlled execution of the retail USB boot routines."""

from __future__ import annotations

import json

from ti84re.emulators.wabbitemu.headless import (
    WabbitemuHeadlessError,
    WabbitemuUsbRomCaseReport,
)

INIT_WRITES = (
    (0x57, 0x80),
    (0x4C, 0x00),
    (0x54, 0x02),
    (0x4A, 0x20),
    (0x4B, 0x00),
    (0x54, 0x00),
    (0x54, 0xC4),
    (0x4C, 0x08),
)
CONNECTED_WRITES = (
    (0x87, 0xFF),
    (0x92, 0x00),
    (0x89, 0x0E),
    (0x8B, 0x21),
)
COMMON_CLEANUP_WRITES = (
    (0x4C, 0x00),
    (0x54, 0x02),
    (0x57, 0x50),
)
HANDSHAKE_CLEANUP_WRITES = (
    (0x5B, 0x00),
    *COMMON_CLEANUP_WRITES,
)

EXPECTED_CASES: dict[str, dict[str, object]] = {
    "init-success": {
        "handshake": True,
        "frame": True,
        "probe_steps": 5_923,
        "probe_tstates": 62_196,
        "timeout_tick_visits": 2,
        "cleanup_visits": 0,
        "receive_boundary_visits": 0,
        "return_visits": 1,
        "input_4c": 2,
        "input_4d": 0,
        "input_8c": 1,
        "final_a": 0x01,
        "final_f": 0x00,
        "final_pc": 0x9D98,
        "writes": INIT_WRITES + CONNECTED_WRITES,
    },
    "handshake-timeout": {
        "handshake": False,
        "frame": True,
        "probe_steps": 783_929,
        "probe_tstates": 7_739_783,
        "timeout_tick_visits": 65_535,
        "cleanup_visits": 1,
        "receive_boundary_visits": 0,
        "return_visits": 1,
        "input_4c": 65_535,
        "input_4d": 5,
        "input_8c": 0,
        "final_a": 0x50,
        "final_f": 0x45,
        "final_pc": 0x9D98,
        "writes": INIT_WRITES + HANDSHAKE_CLEANUP_WRITES,
    },
    "frame-timeout": {
        "handshake": True,
        "frame": False,
        "probe_steps": 3_012_144,
        "probe_tstates": 28_842_346,
        "timeout_tick_visits": 327_676,
        "cleanup_visits": 1,
        "receive_boundary_visits": 0,
        "return_visits": 1,
        "input_4c": 2,
        "input_4d": 5,
        "input_8c": 327_670,
        "final_a": 0x50,
        "final_f": 0x45,
        "final_pc": 0x9D98,
        "writes": INIT_WRITES + CONNECTED_WRITES + COMMON_CLEANUP_WRITES,
    },
    "attempt-event-40": {
        "handshake": True,
        "frame": True,
        "probe_steps": 5_935,
        "probe_tstates": 62_310,
        "timeout_tick_visits": 2,
        "cleanup_visits": 0,
        "receive_boundary_visits": 1,
        "return_visits": 0,
        "input_4c": 2,
        "input_4d": 0,
        "input_8c": 1,
        "final_a": 0x01,
        "final_f": 0x00,
        "final_pc": 0x4170,
        "writes": INIT_WRITES + CONNECTED_WRITES,
    },
}


def validate_usb_rom_reports(
    reports: tuple[WabbitemuUsbRomCaseReport, ...],
) -> dict[str, object]:
    """Require the exact ROM paths and controlled-port outcomes."""

    observed = {report.case: report for report in reports}
    if set(observed) != set(EXPECTED_CASES) or len(observed) != len(reports):
        raise WabbitemuHeadlessError("USB ROM report cases are incomplete or duplicated")

    disagreements: dict[str, dict[str, object]] = {}
    common_expected: dict[str, object] = {
        "boot_steps": 134_845,
        "boot_tstates": 1_746_999,
        "init_visits": 1,
        "reset_helper_visits": 1,
        "violation_resets": 0,
        "flash_changed_bytes": 0,
        "completed": True,
    }
    for case, expected in EXPECTED_CASES.items():
        report_values = observed[case].to_dict()
        for field, expected_value in {**common_expected, **expected}.items():
            if report_values[field] != expected_value:
                disagreements[f"{case}.{field}"] = {
                    "expected": expected_value,
                    "observed": report_values[field],
                }

        output_fields = {
            0x4A: "output_4a",
            0x4B: "output_4b",
            0x4C: "output_4c",
            0x54: "output_54",
            0x57: "output_57",
            0x87: "output_87",
            0x89: "output_89",
            0x8B: "output_8b",
            0x92: "output_92",
        }
        writes = report_values["writes"]
        for port, field in output_fields.items():
            expected_count = sum(write_port == port for write_port, _ in writes)
            if report_values[field] != expected_count:
                disagreements[f"{case}.{field}"] = {
                    "expected": expected_count,
                    "observed": report_values[field],
                }

    if disagreements:
        raise WabbitemuHeadlessError(
            "native USB ROM execution disagrees with the byte-derived model: "
            + json.dumps(disagreements, sort_keys=True)
        )

    ordered = tuple(observed[name] for name in EXPECTED_CASES)
    return {
        "rom_entries": {
            "_AttemptUSBOSReceive": "2F:4145",
            "receive_boundary": "2F:4170",
            "_InitUSB": "2F:52A4",
            "timeout_tick": "2F:5313",
            "reset_helper": "2F:59C3",
        },
        "controlled_port_contract": {
            "port_0x4C_success": "0x5A",
            "port_0x4C_timeout": "0x02",
            "port_0x8C_ready": "nonzero",
            "port_0x8C_timeout": "zero",
            "port_0x4D_cleanup": "0xA5",
        },
        "cases": [report.to_dict() for report in ordered],
    }
