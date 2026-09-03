"""Regression tests for executable Flash bcall documentation examples."""

import unittest
from dataclasses import replace

from ti84re.flash.bcall_examples import (
    parse_flash_bcall_usage_report,
    validate_flash_bcall_usage_report,
)
from ti84re.emulators.wabbitemu.headless import WabbitemuHeadlessError

NATIVE_REPORT = (
    "mode=flash-bcall-usage-probe probe_size=264 boot_steps=100 "
    "boot_tstates=200 max_probe_steps=250000 probe_steps=5000 "
    "probe_tstates=30000 writeflash_visits=1 "
    "writeflashunsafe_visits=4 writeabytesafe_visits=1 "
    "writeabyte_visits=2 erasepage_visits=1 eraseflash_visits=3 "
    "erasecertificate_visits=1 setbound_visits=1 flashtoram_visits=7 "
    "worker_entry_visits=14 violation_resets=0 completed=1 "
    "writeflash_af=0x0044 writeflashunsafe_af=0x0044 "
    "writeabytesafe_af=0x0044 writeabyte_af=0x0044 "
    "erasepage_af=0x0044 eraseflash_af=0x0044 "
    "erasecertificate_af=0xA545 bound_iff_af=0x0040 "
    "writeflash_stored=A5,5A writeflash_copy=A5,5A "
    "writeflashunsafe_stored=3C,C3 writeflashunsafe_copy=3C,C3 "
    "writeabytesafe_stored=0xFC writeabytesafe_copy=0xFC "
    "writeabyte_stored=0xF8 writeabyte_copy=0xF8 "
    "erasepage_stored=0xFF erasepage_copy=0xFF "
    "eraseflash_stored=0xFF eraseflash_copy=0xFF "
    "erasecertificate_stored=0xFF erasecertificate_copy=0xFF "
    "op1=0xF8 context_bit1=0 flash_upper=0x2A "
    "flash_locked=0 final_pc=0x9E00"
)


class FlashBcallUsageReportTests(unittest.TestCase):
    def test_parser_decodes_complete_native_report(self):
        report = parse_flash_bcall_usage_report(NATIVE_REPORT)

        self.assertEqual((0xA5, 0x5A), report.writeflash_copy)
        self.assertEqual((0x3C, 0xC3), report.writeflashunsafe_copy)
        self.assertEqual(0xA545, report.erasecertificate_af)
        self.assertEqual(0xF8, report.op1)
        self.assertFalse(report.context_bit1)

    def test_oracle_accepts_documented_bcall_sequence(self):
        result = validate_flash_bcall_usage_report(
            parse_flash_bcall_usage_report(NATIVE_REPORT)
        )

        self.assertEqual(
            [
                0x80C9,
                0x8087,
                0x80C6,
                0x8021,
                0x8084,
                0x8024,
                0x8060,
                0x80CF,
                0x5017,
            ],
            result["source_model"]["bcall_ids"],
        )
        self.assertFalse(result["source_model"]["physical_scope"])

    def test_oracle_rejects_readback_mismatch(self):
        report = replace(
            parse_flash_bcall_usage_report(NATIVE_REPORT),
            writeflash_copy=(0xA5, 0xFF),
        )

        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_flash_bcall_usage_report(report)

    def test_oracle_requires_setbound_to_leave_iff2_clear(self):
        report = replace(
            parse_flash_bcall_usage_report(NATIVE_REPORT),
            bound_iff_af=0x0044,
        )

        with self.assertRaisesRegex(WabbitemuHeadlessError, "IFF2"):
            validate_flash_bcall_usage_report(report)

    def test_oracle_requires_certificate_wrapper_to_restore_af(self):
        report = replace(
            parse_flash_bcall_usage_report(NATIVE_REPORT),
            erasecertificate_af=0x0044,
        )

        with self.assertRaisesRegex(WabbitemuHeadlessError, "erasecertificate_af"):
            validate_flash_bcall_usage_report(report)

    def test_parser_rejects_short_block_vector(self):
        malformed = NATIVE_REPORT.replace("writeflash_copy=A5,5A", "writeflash_copy=A5")

        with self.assertRaisesRegex(WabbitemuHeadlessError, "two bytes"):
            parse_flash_bcall_usage_report(malformed)


if __name__ == "__main__":
    unittest.main()
