"""Tests for normalized exact-emulator hardware-probe reports."""

from __future__ import annotations

import unittest

from run_exact_hardware_probe import parse_exact_output


class ExactHardwareProbeTest(unittest.TestCase):
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
