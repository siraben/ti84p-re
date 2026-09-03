#!/usr/bin/env python3
"""Regression tests for reusable binary-memory checks."""

import tempfile
import unittest
from pathlib import Path


from ti84re.hardware.debug import (
    MemoryExpectation,
    MemoryMismatch,
    check_memory_expectation,
    read_memory_region,
)


class HardwareDebugTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.dump = Path(self.temporary_directory.name) / "ram.bin"
        self.dump.write_bytes(bytes(range(32)))

    def test_read_memory_region_uses_file_offsets(self):
        self.assertEqual(bytes(range(8, 12)), read_memory_region(self.dump, 8, 4))

    def test_read_memory_region_rejects_truncation(self):
        with self.assertRaisesRegex(MemoryMismatch, "expected 4"):
            read_memory_region(self.dump, 30, 4)

    def test_check_memory_expectation_returns_matching_bytes(self):
        expectation = MemoryExpectation(
            "test word", self.dump, 4, bytes.fromhex("04050607")
        )

        self.assertEqual(expectation.expected, check_memory_expectation(expectation))

    def test_check_memory_expectation_reports_actual_and_expected(self):
        expectation = MemoryExpectation(
            "test word", self.dump, 4, bytes.fromhex("DEADBEEF")
        )

        with self.assertRaisesRegex(MemoryMismatch, "04050607.*deadbeef"):
            check_memory_expectation(expectation)


if __name__ == "__main__":
    unittest.main()
