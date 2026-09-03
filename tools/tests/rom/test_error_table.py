#!/usr/bin/env python3
"""Regression tests for reusable ROM error-message decoding."""

import unittest


from ti84re.rom.error_table import (
    ERROR_MESSAGE_FALLBACK,
    ERROR_MESSAGE_PAGE,
    ERROR_MESSAGE_POINTER_TABLE,
    error_message,
    read_c_string,
)
from ti84re.rom.image import PAGE_SIZE, RomFormatError, RomImage


def put(data: bytearray, page: int, address: int, value: bytes) -> None:
    start = page * PAGE_SIZE + (address & (PAGE_SIZE - 1))
    data[start : start + len(value)] = value


class ErrorTableTests(unittest.TestCase):
    def setUp(self):
        data = bytearray(8 * PAGE_SIZE)
        link = 0x6C55
        for code in (0x1F, 0x22):
            entry = ERROR_MESSAGE_POINTER_TABLE + 2 * (code - 1)
            put(data, ERROR_MESSAGE_PAGE, entry, link.to_bytes(2, "little"))
        put(data, ERROR_MESSAGE_PAGE, link, b"LINK\x00")
        put(data, ERROR_MESSAGE_PAGE, ERROR_MESSAGE_FALLBACK, b"?\x00")
        self.rom = RomImage(bytes(data))

    def test_link_error_aliases_share_the_display_string(self):
        obsolete = error_message(self.rom, 0x22)
        ordinary = error_message(self.rom, 0x9F)

        self.assertEqual("LINK", obsolete.message)
        self.assertEqual("LINK", ordinary.message)
        self.assertEqual(obsolete.message_address, ordinary.message_address)
        self.assertFalse(obsolete.editable)
        self.assertTrue(ordinary.editable)

    def test_out_of_range_code_uses_question_mark_fallback(self):
        report = error_message(self.rom, 0x3A)
        self.assertTrue(report.fallback)
        self.assertIsNone(report.pointer_entry)
        self.assertEqual("?", report.message)

    def test_unterminated_string_is_rejected(self):
        data = bytearray(PAGE_SIZE)
        data[-4:] = b"ABCD"
        with self.assertRaises(RomFormatError):
            read_c_string(RomImage(bytes(data)), 0, 0x7FFC, max_length=4)

    def test_error_code_range_is_checked(self):
        with self.assertRaises(ValueError):
            error_message(self.rom, 0x100)


if __name__ == "__main__":
    unittest.main()
