"""Regression tests for the guarded MAME legacy-interrupt oracle."""

import unittest
from dataclasses import replace

from interrupt_controller import MameLegacyInterruptState
from mame_interrupt import (
    MameInterruptReport,
    expected_mame_interrupt_report,
    parse_mame_interrupt_report,
    validate_mame_interrupt_report,
)
from mame_runtime import MameRuntimeError

NATIVE_OUTPUT = """\
MAME_INTERRUPT identity machine=ti84pv3 version=0.287
MAME_INTERRUPT reset status02=C3 status03=08 status04=08
MAME_INTERRUPT masks values=000102040810FF status03=08080808080808 status04=08080808080808
MAME_INTERRUPT injected seed07=0F keep_on=09 keep_timers=0E keep_all=0F clear=08 status02=C3
MAME_INTERRUPT on masked_press=00 held_enable=00 release=08 enabled_press=01 enabled_release=09 after_ack=08
MAME_INTERRUPT timers timer1=0A timer2=0C both=0E config00=0A config06=0A
MAME_INTERRUPT soft_reset before=0F immediate03=0F immediate04=0F after_timers=0E after_on=07 pc=0000
"""


class MameLegacyInterruptStateTests(unittest.TestCase):
    def test_port02_injects_and_port03_masks_pending_fields(self):
        seeded = MameLegacyInterruptState().write_port02(0x07)

        self.assertEqual(0x0F, seeded.status)
        self.assertEqual(0x09, seeded.write_port03(0x01).status)
        self.assertEqual(0x0E, seeded.write_port03(0x06).status)
        self.assertEqual(0x08, seeded.write_port03(0x00).status)

    def test_on_sampling_requires_enabled_press_edge(self):
        state = MameLegacyInterruptState().sample_on(True)
        self.assertEqual(0x00, state.status)

        held = state.write_port03(0x01).sample_on(True)
        self.assertEqual(0x00, held.status)
        released = held.sample_on(False)
        self.assertEqual(0x08, released.status)
        self.assertEqual(0x01, released.sample_on(True).status)

    def test_standard_timer_ticks_follow_only_low_mask_bits(self):
        state = MameLegacyInterruptState().write_port03(0xFF)
        state = state.standard_timer_tick(1).standard_timer_tick(2)

        self.assertEqual(0x0E, state.status)
        self.assertEqual(0x08, state.write_port03(0xF8).status)

    def test_state_rejects_impossible_source_bits(self):
        with self.assertRaisesRegex(ValueError, "bits 1-2"):
            MameLegacyInterruptState(timer_mask=0x10)


class MameInterruptReportTests(unittest.TestCase):
    def test_parser_decodes_complete_runtime_report(self):
        report = parse_mame_interrupt_report(NATIVE_OUTPUT)

        self.assertIsInstance(report, MameInterruptReport)
        self.assertEqual((0x08,) * 7, report.mask_status03)
        self.assertEqual(0x01, report.on_enabled_press)
        self.assertEqual(0x07, report.soft_after_on)

    def test_source_model_pins_shared_status_and_reset_retention(self):
        report = expected_mame_interrupt_report()

        self.assertEqual(report.mask_status03, report.mask_status04)
        self.assertEqual(0x0F, report.soft_immediate03)
        self.assertEqual(0x0E, report.soft_after_timers)

    def test_oracle_accepts_exact_native_report(self):
        result = validate_mame_interrupt_report(
            parse_mame_interrupt_report(NATIVE_OUTPUT)
        )

        self.assertEqual(
            "bits 0-2 only; clear pending on zero",
            result["source_model"]["port03_write_mask"],
        )
        self.assertFalse(result["source_model"]["low_power_control"])

    def test_oracle_rejects_stored_mask_readback(self):
        changed = replace(
            expected_mame_interrupt_report(),
            mask_status03=(0x08, 0x09, 0x0A, 0x0C, 0x08, 0x08, 0x0F),
        )
        with self.assertRaisesRegex(MameRuntimeError, "disagrees"):
            validate_mame_interrupt_report(changed)

    def test_parser_rejects_short_mask_matrix(self):
        malformed = NATIVE_OUTPUT.replace("status03=08080808080808", "status03=0808")
        with self.assertRaisesRegex(MameRuntimeError, "exactly 7 bytes"):
            parse_mame_interrupt_report(malformed)


if __name__ == "__main__":
    unittest.main()
