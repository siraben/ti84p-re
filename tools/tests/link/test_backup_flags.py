#!/usr/bin/env python3
"""Regression tests for the legacy backup system-flags audit."""

import unittest


from ti84re.link.backup_flags import audit_legacy_system_flags
from ti84re.rom.image import RomImage


class BackupFlagAuditTests(unittest.TestCase):
    def test_reports_normalized_bits_and_exact_iy_references(self):
        page0 = bytearray(0x4000)
        page1 = bytearray(0x4000)
        page0[0x100:0x104] = bytes.fromhex("FDCB0046")  # BIT 0,(IY+0)
        page0[0x110:0x114] = bytes.fromhex("FDCB00C6")  # SET 0,(IY+0)
        page0[0x120:0x124] = bytes.fromhex("FDCB0176")  # BIT 6,(IY+1)
        page1[0x200:0x204] = bytes.fromhex("FDCB00B6")  # RES 6,(IY+0)
        page1[0x210:0x214] = bytes.fromhex("DDCB00C6")  # ignored IX form
        rows = audit_legacy_system_flags(RomImage(bytes(page0 + page1)))

        bit_0 = rows[0]
        self.assertEqual(1, bit_0.normalized_value)
        self.assertEqual("inDelete", bit_0.public_symbol)
        self.assertEqual((1, 0, 1), (bit_0.bit_tests, bit_0.resets, bit_0.sets))

        bit_6 = rows[6]
        self.assertEqual(1, bit_6.normalized_value)
        self.assertEqual((0, 1, 0), (bit_6.bit_tests, bit_6.resets, bit_6.sets))

        byte_1_bit_6 = rows[14]
        self.assertEqual(0, byte_1_bit_6.normalized_value)
        self.assertEqual(1, byte_1_bit_6.bit_tests)

    def test_public_names_do_not_fill_unknown_bits(self):
        rows = audit_legacy_system_flags(RomImage(bytes(0x4000)))
        self.assertIsNone(rows[1].public_symbol)
        self.assertEqual("donePrgm", rows[5].public_symbol)
        self.assertEqual("editOpen", rows[10].public_symbol)


if __name__ == "__main__":
    unittest.main()
