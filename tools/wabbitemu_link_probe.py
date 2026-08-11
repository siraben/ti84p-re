"""Reusable oracle for the native Wabbitemu raw-link and assist probe."""

from __future__ import annotations

import json

from link_port import (
    WABBITEMU_ASSIST_PORTS,
    byte_drive_sequence,
    emulator_port_write,
    link_port_profile,
    port_read_value,
    raw_port_truth_table,
    wabbitemu_assist_status,
)
from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuLinkReport


def expected_link_values() -> dict[str, object]:
    """Return the pinned source-model value for every native link case."""

    profile = link_port_profile("wabbitemu")
    return {
        "port08_active": 0x08 in WABBITEMU_ASSIST_PORTS,
        "port09_active": 0x09 in WABBITEMU_ASSIST_PORTS,
        "port0a_active": 0x0A in WABBITEMU_ASSIST_PORTS,
        "port0b_active": 0x0B in WABBITEMU_ASSIST_PORTS,
        "port0b_read_accepted": False,
        "port0b_read": 0xFF,
        "port0c_active": 0x0C in WABBITEMU_ASSIST_PORTS,
        "port0c_read_accepted": False,
        "port0c_read": 0xFF,
        "port0d_active": 0x0D in WABBITEMU_ASSIST_PORTS,
        "initial_enable": 0x80,
        "initial_status": 0,
        "initial_in": 0,
        "initial_out": 0,
        "raw_reads": raw_port_truth_table(),
        "raw_high_write": emulator_port_write("wabbitemu", 0xA6).port_read,
        "raw_peer_read": port_read_value(0, 1),
        "raw_peer_interrupt": profile.raw_activity_interrupt,
        "idle_ready_status": wabbitemu_assist_status(0x02, ready=True),
        "idle_ready_interrupt": True,
        "idle_after_out_status": 0,
        "assist_send_drives": byte_drive_sequence(0xA5),
        "assist_send_status": wabbitemu_assist_status(0x02, ready=True),
        "assist_send_interrupt": True,
        "assist_send_out": 0xA5,
        "assist_send_after_out_status": 0,
        "assist_receive_status": wabbitemu_assist_status(
            0x01, read_ready=True
        ),
        "assist_receive_interrupt": True,
        "assist_receive_in": 0xA5,
        "assist_receive_after_in_status": 0,
        "assist_error_status": wabbitemu_assist_status(
            0x04, receiving=True, error=True
        ),
        "assist_error_interrupt": True,
        "assist_error_after_read_status": wabbitemu_assist_status(
            0x04, receiving=True
        ),
        "tstates": 0,
    }


def validate_link_report(report: WabbitemuLinkReport) -> dict[str, object]:
    """Check native raw-link and assist observations against reusable models."""

    expected = expected_link_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native link report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "raw_port": "open-collector OR plus inverted low bits and local latch",
            "raw_activity_interrupt": False,
            "assist_ports": [8, 9, 10, 13],
            "assist_reset_enable": "0x80 disabled",
            "assist_send_order": "eight LSB-first four-phase handshakes",
            "assist_receive_order": "eight LSB-first four-phase handshakes",
            "ready_and_read_acknowledgement": "data-port reads clear their flags",
            "error_acknowledgement": "status read clears error after reporting it",
        },
        "native": observed,
    }
