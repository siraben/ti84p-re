#!/usr/bin/env python3
"""Regression tests for reversible physical-probe compact codes."""

from __future__ import annotations

import binascii
import unittest


from ti84re.hardware.build_probes import PROBES, initial_probe_payload
from ti84re.hardware.compact_probe_code import (
    CompactProbeCodeError,
    base32_decode,
    base32_encode,
    decode_compact_probe_code,
    encode_compact_probe_code,
    rle_compress,
    rle_decompress,
)
from ti84re.hardware.probe import ProbeFrame


class CompactProbeCodeTests(unittest.TestCase):
    def test_base32_round_trip_and_human_aliases(self):
        encoded = base32_encode(bytes.fromhex("0001FEFF102030"))

        self.assertEqual(bytes.fromhex("0001FEFF102030"), base32_decode(encoded))
        self.assertEqual(b"\x00", base32_decode("O0"))

        for size in range(65):
            with self.subTest(size=size):
                raw = bytes((index * 37 + size) & 0xFF for index in range(size))
                self.assertEqual(raw, base32_decode(base32_encode(raw)))

    def test_rle_compresses_runs_and_escapes_ff(self):
        raw = b"AAAB\xFF\xFFCCCCCC"
        compressed = rle_compress(raw)

        self.assertLess(len(compressed), len(raw))
        self.assertEqual(raw, rle_decompress(compressed, len(raw)))

    def test_rle_splits_long_runs_without_losing_literal_ff(self):
        raw = bytes(300) + bytes((0xFF,)) * 300

        self.assertEqual(raw, rle_decompress(rle_compress(raw), len(raw)))

    def test_every_built_probe_initial_frame_round_trips(self):
        for name, probe in PROBES.items():
            with self.subTest(probe=name):
                frame = ProbeFrame(
                    probe_id=probe.probe_id,
                    asic_id=0x45,
                    status=0xE3,
                    payload=initial_probe_payload(probe),
                ).encode()
                code = encode_compact_probe_code(frame)
                self.assertTrue(code.startswith("HWPZ1-"))
                self.assertEqual(frame, decode_compact_probe_code(code))

    def test_compact_code_is_shorter_for_repeated_measurements(self):
        frame = ProbeFrame(
            probe_id=9,
            asic_id=0x45,
            status=0xE3,
            payload=bytes((0xFE,)) * 500,
        ).encode()

        code = encode_compact_probe_code(frame)

        self.assertLess(len(code), len(frame) // 4)
        self.assertEqual(frame, decode_compact_probe_code(code))

    def test_crc_rejects_a_changed_valid_character(self):
        frame = ProbeFrame(3, 0x45, 0xE3, bytes.fromhex("06013317272F3B454BF0A5")).encode()
        code = encode_compact_probe_code(frame)
        replacement = "1" if code[-2] != "1" else "2"
        changed = code[:-2] + replacement + code[-1]

        with self.assertRaises(CompactProbeCodeError):
            decode_compact_probe_code(changed)

    def test_appended_zero_symbol_is_rejected_as_noncanonical(self):
        code = base32_encode(b"\0")

        with self.assertRaisesRegex(CompactProbeCodeError, "noncanonical"):
            base32_decode(code + "0")

    def test_rejects_zero_run_and_wrong_prefix(self):
        with self.assertRaisesRegex(CompactProbeCodeError, "begin"):
            decode_compact_probe_code("NOPE")
        with self.assertRaisesRegex(CompactProbeCodeError, "count is zero"):
            rle_decompress(bytes((0xFF, 0, 1)), 1)

    def test_rejects_crc_valid_noncanonical_escape_runs(self):
        frame = ProbeFrame(3, 0x45, 0xE3, b"A").encode()
        compressed = b"".join(bytes((0xFF, 1, value)) for value in frame)
        envelope = (
            len(frame).to_bytes(2, "little")
            + binascii.crc_hqx(frame, 0xFFFF).to_bytes(2, "little")
            + compressed
        )

        with self.assertRaisesRegex(CompactProbeCodeError, "noncanonical escape-run"):
            decode_compact_probe_code("HWPZ1-" + base32_encode(envelope))

    def test_encoder_wraps_invalid_frame_errors(self):
        with self.assertRaisesRegex(CompactProbeCodeError, "frame is invalid"):
            encode_compact_probe_code(b"not an HWP1 frame")

    def test_crc_correct_non_frame_is_reported_as_compact_code_error(self):
        invalid = b"not an HWP1 frame"
        envelope = (
            len(invalid).to_bytes(2, "little")
            + binascii.crc_hqx(invalid, 0xFFFF).to_bytes(2, "little")
            + rle_compress(invalid)
        )

        with self.assertRaisesRegex(CompactProbeCodeError, "decoded frame is invalid"):
            decode_compact_probe_code("HWPZ1-" + base32_encode(envelope))


if __name__ == "__main__":
    unittest.main()
