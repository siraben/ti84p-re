"""Reusable oracle for the native Wabbitemu Fake USB edge probe."""

from __future__ import annotations

import json

from ti84re.hardware.usb import (
    WABBITEMU_USB_PORTS,
    emulator_initial_usb_read,
    wabbitemu_port4a_read,
    wabbitemu_port4a_write,
    wabbitemu_port4c_read,
    wabbitemu_port4d_read,
    wabbitemu_usb_summary,
)
from ti84re.emulators.wabbitemu.headless import WabbitemuHeadlessError, WabbitemuUsbReport


def expected_usb_values() -> dict[str, object]:
    """Return the pinned source-model value for every native USB case."""

    initial = {
        port: emulator_initial_usb_read("Wabbitemu", port)
        for port in WABBITEMU_USB_PORTS
    }
    event = wabbitemu_port4a_write(0x08)
    repeated = wabbitemu_port4a_write(
        0x08,
        line_state=event.line_state_after,
        events=event.events_after,
    )
    return {
        "port4a_active": True,
        "port4c_active": True,
        "port4d_active": True,
        "port54_active": False,
        "port54_read_accepted": False,
        "port54_read": 0xFF,
        "port55_active": True,
        "port56_active": True,
        "port57_active": True,
        "port5b_active": True,
        "port80_active": True,
        "initial_port4a": initial[0x4A],
        "initial_port4c": initial[0x4C],
        "initial_port4d": initial[0x4D],
        "initial_port55": initial[0x55],
        "initial_port56": initial[0x56],
        "initial_port57": initial[0x57],
        "initial_port5b": initial[0x5B],
        "initial_port80": initial[0x80],
        "initial_line_state": 0xA5,
        "initial_events": 0x50,
        "initial_event_mask": 0,
        "initial_line_interrupt": False,
        "initial_protocol_interrupt": False,
        "initial_stored_port4a": 0,
        "initial_stored_port4c": 0,
        "initial_stored_port54": 0,
        "mask_ff_read": 0xFF,
        "mask_zero_read": 0,
        "event_interrupt": event.line_interrupt,
        "event_line_interrupt": event.line_interrupt,
        "event_line_state": event.line_state_after,
        "event_events": event.events_after,
        "event_port4a": wabbitemu_port4a_read(
            event.stored_port4a, port54=0, port4c=0, line_state=event.line_state_after
        ),
        "event_port4d": wabbitemu_port4d_read(
            event.line_state_after, port54=0, port4c=0
        ),
        "event_port55": wabbitemu_usb_summary(
            line_interrupt=True, protocol_interrupt=False
        ),
        "event_port56": event.events_after,
        "repeated_event_interrupt": repeated.line_interrupt,
        "repeated_events": repeated.events_after,
        "summary_none": wabbitemu_usb_summary(
            line_interrupt=False, protocol_interrupt=False
        ),
        "summary_line": wabbitemu_usb_summary(
            line_interrupt=True, protocol_interrupt=False
        ),
        "summary_protocol": wabbitemu_usb_summary(
            line_interrupt=False, protocol_interrupt=True
        ),
        "summary_both": wabbitemu_usb_summary(
            line_interrupt=True, protocol_interrupt=True
        ),
        "port5b_ff_read": 1,
        "protocol_interrupt_enabled": True,
        "port80_ff_read": 0x7F,
        "stored_dev_address": 0x7F,
        "port4c_ff_read": wabbitemu_port4c_read(0x08, port54=0),
        "stored_port4c": 0x08,
        "port4d_false_pair": wabbitemu_port4d_read(
            0xA6, port54=0, port4c=0
        ),
        "port4d_true_pair": wabbitemu_port4d_read(
            0xE5, port54=0x44, port4c=0x08
        ),
        "port4a_true_condition": wabbitemu_port4a_read(
            0x08, port54=0x44, port4c=0x08, line_state=0xE5
        ),
        "port4a_false_condition": wabbitemu_port4a_read(
            0x08, port54=0, port4c=0x08, line_state=0xE5
        ),
        "tstates": 0,
    }


def validate_usb_report(report: WabbitemuUsbReport) -> dict[str, object]:
    """Check native Fake USB observations against reusable source models."""

    expected = expected_usb_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native USB report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "mapped_ports": list(WABBITEMU_USB_PORTS),
            "missing_port54_cause": "duplicate registration writes both handlers to port 0x55",
            "event_mask_effect": "stored at port 0x57 but not consulted by GenerateUSBEvent",
            "repeat_event_cause": "port 0x4A tests D-minus-high bit 3 but sets VBUS-high bit 6",
            "summary": "port 0x55 reports line bit 2 and protocol bit 4 active low",
            "direct_seed_scope": (
                "port 0x4D pair and port 0x4A condition cases test handler contracts, "
                "not naturally reached states"
            ),
        },
        "native": observed,
    }
