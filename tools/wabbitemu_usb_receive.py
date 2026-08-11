"""Oracle for a controlled retail USB installer-record execution."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from wabbitemu_headless import (
    WabbitemuHeadlessError,
    WabbitemuUsbRomReceiveReport,
)

ACK_PACKETS = (
    bytes.fromhex("0000000205"),
    bytes.fromhex("E000"),
)
INSTALLER_PACKET = bytes.fromhex(
    "0000000C04"
    "000000000005"
    "00003E000000"
)
RECEIVE_PACKETS = (*ACK_PACKETS, INSTALLER_PACKET)

INSTALLER_REQUEST = bytes.fromhex(
    "0000000E04"
    "0000000800030000010400000000"
)
ROM_ACK = bytes.fromhex("0000000205E000")
TRANSMIT_PACKETS = (INSTALLER_REQUEST, ROM_ACK)


@dataclass(frozen=True)
class UsbTransportFrame:
    """One five-byte-header transport frame."""

    frame_type: int
    payload: bytes

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["payload"] = self.payload.hex().upper()
        return result


def decode_transport_frame(packet: bytes) -> UsbTransportFrame:
    """Decode the ROM's big-endian length and one-byte frame type."""

    if len(packet) < 5:
        raise ValueError("USB transport frame is shorter than its five-byte header")
    prefix = int.from_bytes(packet[0:2], "big")
    payload_length = int.from_bytes(packet[2:4], "big")
    if prefix != 0:
        raise ValueError("USB transport frame prefix must be zero")
    if len(packet) != payload_length + 5:
        raise ValueError("USB transport payload length does not match the header")
    return UsbTransportFrame(frame_type=packet[4], payload=packet[5:])


def installer_record(packet: bytes) -> dict[str, object]:
    """Decode the service metadata and four-byte installer record prefix."""

    frame = decode_transport_frame(packet)
    if frame.frame_type != 0x04 or len(frame.payload) < 10:
        raise ValueError("installer packet must be a final type-0x04 service frame")
    service = int.from_bytes(frame.payload[4:6], "big")
    record = frame.payload[6:]
    return {
        "frame": frame.to_dict(),
        "service": service,
        "record_prefix": {
            "field": int.from_bytes(record[0:2], "big"),
            "page": record[2],
            "flags": record[3],
        },
        "record_tail": record[4:].hex().upper(),
    }


def validate_usb_rom_receive_report(
    report: WabbitemuUsbRomReceiveReport,
) -> dict[str, object]:
    """Require exact packets, ROM boundaries, intervention, and Flash result."""

    expected: dict[str, object] = {
        "boot_steps": 134_845,
        "boot_tstates": 1_746_999,
        "probe_steps": 78_862,
        "probe_tstates": 927_502,
        "init_visits": 1,
        "receive_entry_visits": 1,
        "control_start_visits": 1,
        "ack_parse_visits": 1,
        "stream_receive_visits": 1,
        "record_dispatch_visits": 1,
        "progress_visits": 1,
        "progress_state_seeded": True,
        "receive_iy": 0x89F0,
        "power_gate_value": 0x08,
        "page_check_visits": 1,
        "page_check_value": 0x3E,
        "invalid_page_visits": 1,
        "cleanup_visits": 1,
        "stop_visits": 1,
        "violation_resets": 0,
        "flash_changed_bytes": 0,
        "rx_packet_count": len(RECEIVE_PACKETS),
        "rx_bytes": sum(map(len, RECEIVE_PACKETS)),
        "rx_consumed": len(RECEIVE_PACKETS),
        "tx_packet_count": len(TRANSMIT_PACKETS),
        "tx_bytes": sum(map(len, TRANSMIT_PACKETS)),
        "script_error": False,
        "final_pc": 0x5000,
        "completed": True,
        "rx_packets": RECEIVE_PACKETS,
        "tx_packets": TRANSMIT_PACKETS,
    }
    observed = {
        name: getattr(report, name)
        for name in expected
    }
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native USB receive execution disagrees with the byte-derived model: "
            + json.dumps(disagreements, sort_keys=True, default=str)
        )

    ack = decode_transport_frame(b"".join(ACK_PACKETS))
    request = decode_transport_frame(INSTALLER_REQUEST)
    response = decode_transport_frame(ROM_ACK)
    return {
        "rom_entries": {
            "_InitUSB": "2F:52A4",
            "_ReceiveOS_USB": "2F:48CA",
            "stream_receive": "2F:4610",
            "record_dispatch": "2F:495B",
            "page_check": "2F:5079",
            "invalid_page_branch": "2F:49A2",
            "_USBErrorCleanup": "2F:5958",
            "stop_before_error_ui": "2F:5000",
        },
        "calling_context": {
            "iy": "0x89F0",
            "negotiated_frame_size": "0x0104",
            "staged_offset": 0,
            "timeout": "0x0014",
            "controller_status_read": "0x88 after _InitUSB",
            "progress_state_seed": "0x82A3 = 0x3E immediately before _DisplayOSProgress",
        },
        "host_ack": ack.to_dict(),
        "installer_request": request.to_dict(),
        "installer_record": installer_record(INSTALLER_PACKET),
        "rom_ack": response.to_dict(),
        "runtime": report.to_dict(),
        "evidence_limit": (
            "controlled Wabbitemu-core execution with scripted endpoint FIFOs and "
            "an explicit progress-state intervention; not a connected USB device, "
            "physical calculator, or natural full-OS-install session"
        ),
    }
