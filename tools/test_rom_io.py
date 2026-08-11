"""Regression tests for inline-data classification of ROM I/O candidates."""

import unittest

from rom_image import PAGE_SIZE, RomImage, RomLocation
from rom_io import inline_descriptor_at


def fixture(*, page: int, offset: int, data: bytes) -> RomImage:
    image = bytearray(PAGE_SIZE * (page + 1))
    image[page * PAGE_SIZE + offset : page * PAGE_SIZE + offset + len(data)] = data
    return RomImage(bytes(image))


class RomIoTests(unittest.TestCase):
    def test_classifies_both_bcall_operand_bytes(self):
        rom = fixture(page=3, offset=0x100, data=bytes.fromhex("EFDB52"))

        low = inline_descriptor_at(rom, RomLocation(3, 0x4101))
        high = inline_descriptor_at(rom, RomLocation(3, 0x4102))

        self.assertEqual("bcall-operand", low.kind)
        self.assertEqual(0x52DB, low.value)
        self.assertEqual("03:4100", high.owner_location)

    def test_classifies_every_bjump_descriptor_byte(self):
        rom = fixture(page=0, offset=0x200, data=bytes.fromhex("CD092BD35177"))

        reports = [
            inline_descriptor_at(rom, RomLocation(0, address))
            for address in range(0x203, 0x206)
        ]

        self.assertTrue(all(report.kind == "bjump-descriptor" for report in reports))
        self.assertTrue(all(report.target == "37:51D3" for report in reports))
        self.assertTrue(all(report.raw_page == 0x77 for report in reports))

    def test_returns_none_for_an_ordinary_instruction_location(self):
        rom = fixture(page=0, offset=0x100, data=bytes.fromhex("3E01D35A"))

        self.assertIsNone(inline_descriptor_at(rom, RomLocation(0, 0x102)))


if __name__ == "__main__":
    unittest.main()
