#!/usr/bin/env python3
"""Tests for live MathPrint render-record decoding."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_mathprint_records import (
    HEADER_SIZE,
    DecodedRecord,
    decode_record_header,
    record,
    root_child_ids,
    word,
)


class MathPrintRecordTests(unittest.TestCase):
    def test_reads_little_endian_word(self):
        memory = bytearray(0x10000)
        memory[0x8DF2:0x8DF4] = bytes((0xE9, 0x9D))
        self.assertEqual(0x9DE9, word(memory, 0x8DF2))

    def test_snapshots_twenty_byte_header(self):
        memory = bytearray(0x10000)
        header = bytes(range(HEADER_SIZE))
        memory[0x9DE9:0x9DE9 + HEADER_SIZE] = header
        snapshot = record(memory, 0x9DE9)
        self.assertEqual(0x9DE9, snapshot.pointer)
        self.assertEqual(tuple(header), snapshot.header)

    def test_reads_root_child_id_table(self):
        memory = bytearray(0x10000)
        table = 0x9DE9 + HEADER_SIZE
        memory[table:table + 6] = bytes((0x0E, 0x00, 0x0F, 0x00, 0x07, 0x00))
        self.assertEqual((0x000E, 0x000F, 0x0007), root_child_ids(memory, 0x9DE9, 3))

    def test_decodes_unaligned_header_words(self):
        header = (
            0x10, 0x00, 0x27, 0x0F, 0x00, 0x01, 0x00, 0x0C, 0x00, 0x1B,
            0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0xEF,
        )
        self.assertEqual(
            DecodedRecord(0x10, 0x27, 0x0F, 1, 0x0C, 0x1B, 8, 0, 0, 1, 0xEF),
            decode_record_header(header),
        )

    def test_rejects_header_past_memory_end(self):
        with self.assertRaises(ValueError):
            record(bytearray(0x10000), 0xFFFF)


if __name__ == "__main__":
    unittest.main()
