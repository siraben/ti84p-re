#!/usr/bin/env python3
"""Tests for BootFree versus retail boot-table classification."""

import csv
import hashlib
import unittest


from ti84re.boot.compare_boot_pages import rows
from ti84re.rom.image import RomImage
from ti84re.rom.signatures import (
    TI84_PLUS_OS_255MP_BOOTFREE_SHA256,
    TI84_PLUS_OS_255MP_SHA256,
)
from ti84re.paths import ROOT, DATA, DEFAULT_ROM




@unittest.skipUnless(
    (DEFAULT_ROM).is_file() and (ROOT / "ti84plus_patched.rom").is_file(),
    "local ignored BootFree and retail ROM inputs are unavailable",
)
class CompareBootPagesLocalRomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bootfree = RomImage.from_path(DEFAULT_ROM)
        cls.retail = RomImage.from_path(ROOT / "ti84plus_patched.rom")

    def test_all_boot_entries_are_accounted_for(self):
        bootfree_hash = hashlib.sha256((DEFAULT_ROM).read_bytes()).hexdigest()
        retail_hash = hashlib.sha256(
            (ROOT / "ti84plus_patched.rom").read_bytes()
        ).hexdigest()
        result = rows(
            self.bootfree,
            self.retail,
            bootfree_hash=bootfree_hash,
            retail_hash=retail_hash,
        )
        self.assertEqual(87, len(result))
        self.assertTrue(all(row["same_target"] == "false" for row in result))
        self.assertEqual(
            {bootfree_hash},
            {row["bootfree_rom_sha256"] for row in result},
        )
        self.assertEqual(
            {retail_hash},
            {row["retail_rom_sha256"] for row in result},
        )

    def test_bootfree_stub_and_implemented_counts(self):
        result = rows(
            self.bootfree,
            self.retail,
            bootfree_hash="bootfree",
            retail_hash="retail",
        )
        no_op = [row for row in result if row["bootfree_disposition"] == "stub-ret"]
        implemented = [row for row in result if row["bootfree_disposition"] == "implemented"]
        self.assertEqual(45, len(no_op))
        self.assertEqual(38, len(implemented))


class CompareBootPagesCheckedTableTests(unittest.TestCase):
    def test_checked_table_accounts_for_every_entry(self):
        with (DATA / "boot-page-comparison.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            result = list(csv.DictReader(stream))
        self.assertEqual(87, len(result))
        self.assertTrue(all(row["same_target"] == "false" for row in result))
        self.assertEqual(
            45,
            sum(row["bootfree_disposition"] == "stub-ret" for row in result),
        )
        self.assertEqual(
            {TI84_PLUS_OS_255MP_BOOTFREE_SHA256},
            {row["bootfree_rom_sha256"] for row in result},
        )
        self.assertEqual(
            {TI84_PLUS_OS_255MP_SHA256},
            {row["retail_rom_sha256"] for row in result},
        )


if __name__ == "__main__":
    unittest.main()
