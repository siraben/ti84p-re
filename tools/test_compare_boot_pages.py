#!/usr/bin/env python3
"""Tests for BootFree versus retail boot-table classification."""

import csv
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare_boot_pages import rows  # noqa: E402
from rom_image import RomImage  # noqa: E402


TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent


@unittest.skipUnless(
    (TOOLS / "rom.bin").is_file() and (ROOT / "ti84plus_patched.rom").is_file(),
    "local ignored BootFree and retail ROM inputs are unavailable",
)
class CompareBootPagesLocalRomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bootfree = RomImage.from_path(TOOLS / "rom.bin")
        cls.retail = RomImage.from_path(ROOT / "ti84plus_patched.rom")

    def test_all_boot_entries_are_accounted_for(self):
        result = rows(self.bootfree, self.retail)
        self.assertEqual(87, len(result))
        self.assertTrue(all(row["same_target"] == "false" for row in result))

    def test_bootfree_stub_and_implemented_counts(self):
        result = rows(self.bootfree, self.retail)
        no_op = [row for row in result if row["bootfree_disposition"] == "stub-ret"]
        implemented = [row for row in result if row["bootfree_disposition"] == "implemented"]
        self.assertEqual(45, len(no_op))
        self.assertEqual(38, len(implemented))


class CompareBootPagesCheckedTableTests(unittest.TestCase):
    def test_checked_table_accounts_for_every_entry(self):
        with (TOOLS / "data" / "boot-page-comparison.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            result = list(csv.DictReader(stream))
        self.assertEqual(87, len(result))
        self.assertTrue(all(row["same_target"] == "false" for row in result))
        self.assertEqual(
            45,
            sum(row["bootfree_disposition"] == "stub-ret" for row in result),
        )


if __name__ == "__main__":
    unittest.main()
