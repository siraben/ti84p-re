"""Regression tests for the retail USB installer-record oracle."""

import unittest
from dataclasses import fields

from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuUsbRomReceiveReport
from wabbitemu_usb_receive import (
    ACK_PACKETS,
    INSTALLER_PACKET,
    RECEIVE_PACKETS,
    TRANSMIT_PACKETS,
    decode_transport_frame,
    installer_record,
    validate_usb_rom_receive_report,
)


def matching_report() -> WabbitemuUsbRomReceiveReport:
    values = {
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
        "rx_packet_count": 3,
        "rx_bytes": 24,
        "rx_consumed": 3,
        "tx_packet_count": 2,
        "tx_bytes": 26,
        "script_error": False,
        "final_pc": 0x5000,
        "completed": True,
        "rx_packets": RECEIVE_PACKETS,
        "tx_packets": TRANSMIT_PACKETS,
    }
    values.update({
        field.name: ""
        for field in fields(WabbitemuUsbRomReceiveReport)
        if field.name not in values
    })
    return WabbitemuUsbRomReceiveReport(**values)


class WabbitemuUsbReceiveTests(unittest.TestCase):
    def test_decodes_ack_and_installer_record(self):
        ack = decode_transport_frame(b"".join(ACK_PACKETS))
        record = installer_record(INSTALLER_PACKET)

        self.assertEqual((0x05, bytes.fromhex("E000")), (ack.frame_type, ack.payload))
        self.assertEqual(5, record["service"])
        self.assertEqual(0x3E, record["record_prefix"]["page"])

    def test_rejects_invalid_transport_framing(self):
        with self.assertRaisesRegex(ValueError, "shorter"):
            decode_transport_frame(b"\0" * 4)
        with self.assertRaisesRegex(ValueError, "prefix"):
            decode_transport_frame(bytes.fromhex("0001000005"))
        with self.assertRaisesRegex(ValueError, "length"):
            decode_transport_frame(bytes.fromhex("0000000205E0"))

    def test_validates_exact_runtime(self):
        result = validate_usb_rom_receive_report(matching_report())

        self.assertEqual("2F:49A2", result["rom_entries"]["invalid_page_branch"])
        self.assertIn("progress-state intervention", result["evidence_limit"])

    def test_rejects_packet_or_runtime_drift(self):
        report = matching_report()
        values = report.to_dict()
        values["rx_packets"] = report.rx_packets
        values["tx_packets"] = (*report.tx_packets[:-1], b"drift")
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_usb_rom_receive_report(WabbitemuUsbRomReceiveReport(**values))


if __name__ == "__main__":
    unittest.main()
