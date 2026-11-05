"""Tests for normalized exact-emulator hardware-probe reports."""

from __future__ import annotations

import unittest

from ti84re.hardware.build_probes import PROBES, initial_probe_payload
from ti84re.hardware.probe import decode_probe_frame, probe_verification_code
from ti84re.paths import PROBES as PROBE_SOURCES
from ti84re.hardware.run_exact_probe import (
    DISPLAYED_PROBES,
    parse_exact_output,
    validate_exact_capture,
)


class ExactHardwareProbeTest(unittest.TestCase):
    def test_every_built_probe_is_selectable(self) -> None:
        self.assertEqual(set(PROBES), set(DISPLAYED_PROBES))

    def test_execution_return_uses_mutated_resident_frame_crc(self) -> None:
        probe = PROBES["exec-flash-07"]
        staging_payload = bytearray(initial_probe_payload(probe))
        resident_payload = bytearray(staging_payload)
        resident_payload[8] = 1
        staging_bytes = (
            b"HWP1"
            + bytes((1, probe.probe_id))
            + probe.payload_size.to_bytes(2, "little")
            + bytes((0x00, 0x00))
            + staging_payload
        )
        resident_bytes = staging_bytes[:10] + resident_payload
        resident_frame = decode_probe_frame(resident_bytes)
        code = probe_verification_code(resident_frame)
        fields = {
            "probe_id": str(probe.probe_id),
            "payload_size": str(probe.payload_size),
            "probe_size": "407",
            "appvar_matches": "0",
            "display_code": str(code),
            "frame_hex": staging_bytes.hex(),
            "appvar_frame_hex": resident_bytes.hex(),
        }

        captured, captured_code = validate_exact_capture(
            "exec-flash-07", fields, 407
        )
        self.assertEqual(captured.payload[8], 1)
        self.assertEqual(captured, resident_frame)
        self.assertEqual(captured_code, code)

        invalid = dict(fields)
        invalid_payload = bytearray(resident_payload)
        invalid_payload[8] = 2
        invalid["appvar_frame_hex"] = (
            staging_bytes[:10] + invalid_payload
        ).hex()
        with self.assertRaisesRegex(ValueError, "invalid outcome transition"):
            validate_exact_capture("exec-flash-07", invalid, 407)

    def test_both_exact_adapters_accept_execution_frame_transitions(self) -> None:
        for source in (
            PROBE_SOURCES / "tilem" / "tilem_exact_probe.c",
            PROBE_SOURCES / "wabbitemu" / "wabbitemu_exact_probe.cpp",
        ):
            with self.subTest(source=source.name):
                text = source.read_text()
                self.assertIn("execution_frame_transition_valid", text)
                self.assertIn("probe_id == 4", text)

    def test_tilem_exact_adapter_continues_an_ordinary_clock_slice(self) -> None:
        text = (PROBE_SOURCES / "tilem" / "tilem_exact_probe.c").read_text()

        self.assertIn("if (reason == 0) {\n            continue;", text)

    def test_parse_complete_line(self) -> None:
        fields = parse_exact_output(
            "mode=exact-probe probe_id=14 payload_size=47 probe_size=1325 "
            "create_intercepts=1 appvar_matches=1 completed=1 "
            "display_code=21062 frame_hex=48575031 "
            "appvar_frame_hex=48575031\n"
        )
        self.assertEqual(fields["display_code"], "21062")
        self.assertEqual(fields["frame_hex"], "48575031")

    def test_reject_missing_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "omitted fields"):
            parse_exact_output("mode=exact-probe frame_hex=48575031\n")

    def test_reject_multiple_frames(self) -> None:
        line = (
            "mode=x probe_id=1 payload_size=1 probe_size=1 "
            "create_intercepts=1 appvar_matches=1 completed=1 display_code=1 "
            "frame_hex=00 appvar_frame_hex=00\n"
        )
        with self.assertRaisesRegex(ValueError, "one frame status line"):
            parse_exact_output(line + line)


if __name__ == "__main__":
    unittest.main()
