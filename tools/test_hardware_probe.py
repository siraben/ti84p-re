#!/usr/bin/env python3
"""Regression tests for physical hardware-probe result containers."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hardware_probe import (
    ProbeFormatError,
    ProbeFrame,
    decode_probe_appvar,
    decode_probe_frame,
    decode_probe_measurements,
    decode_ti_variable_file,
    encode_probe_appvar,
    encode_ti_variable_file,
    probe_appvar_report,
)


class HardwareProbeTests(unittest.TestCase):
    def test_probe_frame_round_trip(self):
        frame = ProbeFrame(probe_id=2, asic_id=0x55, status=0xE3, payload=b"\x10\x20")

        self.assertEqual(frame, decode_probe_frame(frame.encode()))

    def test_probe_appvar_round_trip_checks_both_containers(self):
        frame = ProbeFrame(probe_id=1, asic_id=0x45, status=0xE7, payload=b"result")

        variable, decoded = decode_probe_appvar(encode_probe_appvar("HWPMD51", frame))

        self.assertEqual("HWPMD51", variable.name)
        self.assertEqual(0x15, variable.variable_type)
        self.assertEqual(frame, decoded)

    def test_generic_ti_program_container_remains_compatible(self):
        body = b"\x01\x00\xC9"

        variable = decode_ti_variable_file(
            encode_ti_variable_file(0x05, "ASMRET", body, comment="fixture")
        )

        self.assertEqual(0x05, variable.variable_type)
        self.assertEqual("ASMRET", variable.name)
        self.assertEqual(body, variable.data)

    def test_archived_variable_uses_ti_archive_flag(self):
        encoded = encode_ti_variable_file(0x05, "ARCHIVE", b"x", archived=True)

        self.assertEqual(0x80, encoded[55 + 14])
        self.assertTrue(decode_ti_variable_file(encoded).archived)

    def test_rejects_ti_checksum_corruption(self):
        encoded = bytearray(
            encode_probe_appvar(
                "HWPRAM1",
                ProbeFrame(probe_id=2, asic_id=0x45, status=0xE3, payload=b"x"),
            )
        )
        encoded[-1] ^= 1

        with self.assertRaisesRegex(ProbeFormatError, "checksum"):
            decode_probe_appvar(bytes(encoded))

    def test_rejects_frame_length_mismatch(self):
        encoded = bytearray(
            ProbeFrame(probe_id=1, asic_id=0x45, status=0xE3, payload=b"abc").encode()
        )
        encoded[6:8] = (4).to_bytes(2, "little")

        with self.assertRaisesRegex(ProbeFormatError, "length"):
            decode_probe_frame(bytes(encoded))

    def test_rejects_unsupported_encode_version(self):
        frame = ProbeFrame(
            probe_id=1,
            asic_id=0x45,
            status=0xE3,
            payload=b"",
            format_version=2,
        )

        with self.assertRaisesRegex(ValueError, "version 2"):
            frame.encode()

    def test_md5_measurements_decode_little_endian_words(self):
        payload = (
            bytes.fromhex("B417D1D6")
            + bytes.fromhex("00000000")
            + bytes.fromhex("01020304")
            + bytes.fromhex("10203040")
            + bytes.fromhex("AABBCCDD")
        )

        report = decode_probe_measurements(
            ProbeFrame(probe_id=1, asic_id=0x55, status=0xE3, payload=payload)
        )

        self.assertEqual("0xD6D117B4", report["valid_result"])
        self.assertEqual("00000000", report["undefined_reads"])
        self.assertEqual("0x04030201", report["fifth_write_result"])

    def test_ram_measurements_report_alias_and_restore(self):
        original = bytes.fromhex("102030405060")
        payload = original + bytes((0x66,)) * 6 + original
        frame = ProbeFrame(probe_id=2, asic_id=0x55, status=0xE3, payload=payload)

        report = probe_appvar_report(encode_probe_appvar("HWPRAM21", frame))

        self.assertEqual("ram-alias", report["probe_name"])
        self.assertEqual(0x55, report["asic_id"])
        self.assertEqual("0x55", report["asic_id_hex"])
        self.assertEqual(
            "selectors-82-through-87-alias",
            report["measurements"]["topology_observation"],
        )
        self.assertTrue(report["measurements"]["restore_matches"])
        self.assertEqual(
            [["0x82", "0x83", "0x84", "0x85", "0x86", "0x87"]],
            report["measurements"]["alias_groups"],
        )

    def test_ram_measurements_report_partial_alias_groups(self):
        original = bytes.fromhex("102030405060")
        observed = bytes.fromhex("222244445566")
        frame = ProbeFrame(
            probe_id=2,
            asic_id=0x45,
            status=0xE3,
            payload=original + observed + original,
        )

        report = decode_probe_measurements(frame)

        self.assertEqual("partial-selector-aliases", report["topology_observation"])
        self.assertEqual(
            [["0x82", "0x83"], ["0x84", "0x85"], ["0x86"], ["0x87"]],
            report["alias_groups"],
        )

    def test_known_probe_rejects_wrong_payload_size(self):
        frame = ProbeFrame(probe_id=2, asic_id=0x55, status=0xE3, payload=b"x")

        with self.assertRaisesRegex(ProbeFormatError, "18 bytes"):
            decode_probe_measurements(frame)

    def test_asic_snapshot_maps_payload_bytes_to_ports(self):
        payload = bytes.fromhex("06013317272F3B454BF0A5")
        frame = ProbeFrame(probe_id=3, asic_id=0x45, status=0xE3, payload=payload)

        report = decode_probe_measurements(frame)

        self.assertEqual("0x06", report["registers"]["0x04"])
        self.assertEqual("0x01", report["registers"]["0x20"])
        self.assertEqual("0xF0", report["registers"]["0x39"])
        self.assertEqual("0xA5", report["registers"]["0x3A"])

    def test_execution_fetch_decodes_target_outcome_and_registers(self):
        payload = bytes.fromhex(
            "01820004000434420107821008292026"
        )
        frame = ProbeFrame(probe_id=4, asic_id=0x45, status=0xE3, payload=payload)

        report = decode_probe_measurements(frame)

        self.assertEqual("ram", report["target_kind"])
        self.assertEqual("0x82", report["target_selector"])
        self.assertEqual("0x0400", report["scan_start"])
        self.assertEqual("0x0400", report["scan_length"])
        self.assertEqual("0x4234", report["target_address"])
        self.assertEqual("returned", report["outcome"])
        self.assertEqual("0x07", report["registers"]["0x04"])
        self.assertEqual("0x08", report["registers"]["0x22"])

    def test_usb_snapshot_maps_payload_bytes_to_ports(self):
        payload = bytes(range(0x10, 0x1F))
        frame = ProbeFrame(probe_id=5, asic_id=0x45, status=0xE3, payload=payload)

        report = decode_probe_measurements(frame)

        self.assertEqual("0x10", report["registers"]["0x49"])
        self.assertEqual("0x17", report["registers"]["0x51"])
        self.assertEqual("0x18", report["registers"]["0x52"])
        self.assertEqual("0x1E", report["registers"]["0x5B"])


if __name__ == "__main__":
    unittest.main()
