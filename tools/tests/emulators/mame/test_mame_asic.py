"""Regression tests for the guarded MAME ASIC-control oracle."""

import unittest
from dataclasses import replace

from ti84re.emulators.mame.asic import (
    MameAsicReport,
    expected_mame_asic_report,
    mame_status_for_gate,
    parse_mame_asic_report,
    validate_mame_asic_report,
)
from ti84re.emulators.mame.runtime import MameRuntimeError

NATIVE_OUTPUT = """\
MAME_ASIC identity machine=ti84pv3 version=0.287
MAME_ASIC reset status02=C3 port14=00 identity15=33 speed20=00 control21=00 usb55=1F usb56=00 pc=0000
MAME_ASIC gate values=0001023F40FF status=C3C7CBFFC3FF readback=000000000000
MAME_ASIC speed values=00010203FF readback=00010203FF
MAME_ASIC control locked33=03 unlocked30=00 unlocked03=03 unlocked33=03 unlockedff=0F
MAME_ASIC mapping protection_initial=0000000000000000000000000000 protection_patterned=0000000000000000000000000000 gpio_initial=0000 gpio_patterned=0000 usb_initial=00000000000000000000001F000000000000 usb_patterned=00000000000000000000001F000000000000
MAME_ASIC clocks frames=5 low_count=2EE0 low_attoseconds=100000000000000000 high_count=7530 high_attoseconds=100000000000000000 control21=03 protection=0000000000
MAME_ASIC soft_reset status02=C7 port14=00 identity15=33 speed20=03 control21=0B usb55=1F usb56=00 pc=0000
"""


class MameAsicTests(unittest.TestCase):
    def test_parser_decodes_complete_control_surface(self):
        report = parse_mame_asic_report(NATIVE_OUTPUT)

        self.assertEqual(0xC3, report.reset_status02)
        self.assertEqual((0xC3, 0xC7, 0xCB, 0xFF, 0xC3, 0xFF), report.gate_status)
        self.assertEqual((0, 1, 2, 3, 0xFF), report.speed_readback)
        self.assertEqual(12000, report.clock_low_count)
        self.assertEqual(30000, report.clock_high_count)
        self.assertEqual(0x0B, report.soft_control21)

    def test_gate_status_uses_raw_byte_not_boolean_state(self):
        self.assertEqual(0xC7, mame_status_for_gate(1))
        self.assertEqual(0xCB, mame_status_for_gate(2))
        self.assertEqual(0xC3, mame_status_for_gate(0x40))
        self.assertEqual(0xFF, mame_status_for_gate(0xFF))

    def test_gate_status_rejects_non_byte(self):
        with self.assertRaisesRegex(ValueError, "byte"):
            mame_status_for_gate(0x100)

    def test_source_model_pins_raw_speed_and_clock_ratio(self):
        report = expected_mame_asic_report()

        self.assertEqual(report.speed_values, report.speed_readback)
        self.assertEqual(2.5, report.clock_high_count / report.clock_low_count)
        self.assertEqual(100_000_000_000_000_000, report.clock_low_attoseconds)

    def test_source_model_pins_missing_ranges_and_usb_constants(self):
        report = expected_mame_asic_report()

        self.assertEqual((0,) * 14, report.protection_patterned)
        self.assertEqual((0, 0), report.gpio_patterned)
        self.assertEqual(0x1F, report.usb_patterned[0x55 - 0x4A])
        self.assertEqual(0, report.usb_patterned[0x56 - 0x4A])

    def test_source_model_pins_soft_reset_retention(self):
        report = expected_mame_asic_report()

        self.assertEqual(0xC7, report.soft_status02)
        self.assertEqual(3, report.soft_speed20)
        self.assertEqual(0x0B, report.soft_control21)
        self.assertEqual(0, report.soft_pc)

    def test_oracle_accepts_exact_native_report(self):
        result = validate_mame_asic_report(parse_mame_asic_report(NATIVE_OUTPUT))

        self.assertEqual(2.5, result["source_model"]["clock_ratio"])
        self.assertTrue(
            result["source_model"]["ram_fetch_with_patterned_protection_ports"]
        )

    def test_oracle_rejects_booleanized_gate_status(self):
        expected = expected_mame_asic_report()
        changed = replace(
            expected,
            gate_status=(0xC3, 0xC7, 0xC7, 0xC7, 0xC7, 0xC7),
        )
        with self.assertRaisesRegex(MameRuntimeError, "disagrees"):
            validate_mame_asic_report(changed)

    def test_oracle_rejects_cold_style_soft_reset(self):
        changed = replace(
            expected_mame_asic_report(),
            soft_status02=0xC3,
            soft_speed20=0,
            soft_control21=0,
        )
        with self.assertRaisesRegex(MameRuntimeError, "disagrees"):
            validate_mame_asic_report(changed)

    def test_parser_rejects_short_protection_block(self):
        malformed = NATIVE_OUTPUT.replace(
            "protection_initial=0000000000000000000000000000",
            "protection_initial=0000",
        )
        with self.assertRaisesRegex(MameRuntimeError, "exactly 14 bytes"):
            parse_mame_asic_report(malformed)

    def test_report_remains_typed(self):
        self.assertIsInstance(parse_mame_asic_report(NATIVE_OUTPUT), MameAsicReport)


if __name__ == "__main__":
    unittest.main()
