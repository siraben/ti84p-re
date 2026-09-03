#!/usr/bin/env python3
"""Regression tests for length-prefixed Flash worker helpers."""

import unittest

from ti84re.flash.workers import compare_workers, extract_length_prefixed_worker
from ti84re.rom.image import RomImage, RomLocation


def rom_with_workers(*workers: tuple[int, bytes]) -> RomImage:
    data = bytearray(0x4000)
    for address, code in workers:
        offset = address & 0x3FFF
        data[offset : offset + 2] = len(code).to_bytes(2, "little")
        data[offset + 2 : offset + 2 + len(code)] = code
    return RomImage(bytes(data))


class FlashWorkerTests(unittest.TestCase):
    def test_extracts_length_entry_bytes_and_hash(self):
        rom = rom_with_workers((0x4100, bytes.fromhex("aabbcc")))

        worker = extract_length_prefixed_worker(rom, RomLocation(0, 0x4100))

        self.assertEqual(RomLocation(0, 0x4102), worker.entry)
        self.assertEqual(bytes.fromhex("aabbcc"), worker.code)
        self.assertEqual(3, worker.length)
        self.assertEqual(64, len(worker.sha256))

    def test_comparison_reports_insertions_and_matching_bytes(self):
        rom = rom_with_workers(
            (0x4100, bytes.fromhex("aabbccdd")),
            (0x4200, bytes.fromhex("aa11bbcc22dd")),
        )
        left = extract_length_prefixed_worker(rom, RomLocation(0, 0x4100))
        right = extract_length_prefixed_worker(rom, RomLocation(0, 0x4200))

        comparison = compare_workers(left, right)

        self.assertEqual(4, comparison.matching_bytes)
        self.assertEqual(
            ("insert", "insert"),
            tuple(
                difference.operation for difference in comparison.differences
            ),
        )


if __name__ == "__main__":
    unittest.main()
