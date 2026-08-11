#!/usr/bin/env python3
"""Regression tests for raw-ROM Flash-gate sequence recognition."""

import unittest
from collections import Counter
from pathlib import Path

from flash_gate import (
    LOCK_SEQUENCES,
    PORT_14_WRITE,
    UNLOCK_SEQUENCES,
    scan_flash_gate,
)
from rom_image import RomImage, RomLocation


ROM = Path(__file__).resolve().parent / "rom.bin"


class FlashGateTests(unittest.TestCase):
    def test_classifies_complete_unlock_and_lock_sequences(self):
        page = bytearray(b"\xFF" * 0x4000)
        unlock = UNLOCK_SEQUENCES[1]
        lock = LOCK_SEQUENCES[1]
        page[0x0100 : 0x0100 + len(unlock)] = unlock
        page[0x0200 : 0x0200 + len(lock)] = lock

        result = scan_flash_gate(RomImage(bytes(page)))

        self.assertEqual(("unlock", "lock"), tuple(item.kind for item in result.sequences))
        self.assertEqual((1, 0), tuple(item.requested_value for item in result.sequences))
        self.assertEqual(RomLocation(0, 0x010A), result.sequences[0].output)
        self.assertEqual(RomLocation(0, 0x0209), result.sequences[1].output)
        self.assertEqual((), result.unclassified_candidates)

    def test_classifies_short_boot_spellings(self):
        page = bytearray(b"\xFF" * 0x4000)
        unlock = UNLOCK_SEQUENCES[0]
        lock = LOCK_SEQUENCES[0]
        page[0x0100 : 0x0100 + len(unlock)] = unlock
        page[0x0200 : 0x0200 + len(lock)] = lock

        result = scan_flash_gate(RomImage(bytes(page)))

        self.assertEqual(("unlock", "lock"), tuple(item.kind for item in result.sequences))
        self.assertEqual(RomLocation(0, 0x0108), result.sequences[0].output)
        self.assertEqual(RomLocation(0, 0x0207), result.sequences[1].output)

    def test_reports_unclassified_immediate_write_separately(self):
        page = bytearray(b"\xFF" * 0x4000)
        page[0x0123 : 0x0125] = PORT_14_WRITE

        result = scan_flash_gate(RomImage(bytes(page)))

        self.assertEqual((), result.sequences)
        self.assertEqual((RomLocation(0, 0x0123),), result.unclassified_candidates)

    def test_keeps_physical_page_identity_and_selection(self):
        rom_data = bytearray(b"\xFF" * 0x8000)
        unlock = UNLOCK_SEQUENCES[1]
        rom_data[0x4000 + 0x0200 : 0x4000 + 0x0200 + len(unlock)] = unlock
        rom = RomImage(bytes(rom_data))

        self.assertEqual((), scan_flash_gate(rom, (0,)).sequences)
        sequence = scan_flash_gate(rom, (1,)).sequences[0]
        self.assertEqual(RomLocation(1, 0x4200), sequence.start)
        self.assertEqual(RomLocation(1, 0x420A), sequence.output)

    def test_rejects_page_outside_rom(self):
        with self.assertRaisesRegex(ValueError, "outside this ROM"):
            scan_flash_gate(RomImage(bytes(0x4000)), (1,))

    def test_pinned_rom_accounts_for_every_port_14_opcode_pair(self):
        rom = RomImage.from_path(ROM)

        result = scan_flash_gate(rom)
        page_3d = scan_flash_gate(rom, (0x3D,))

        self.assertEqual(Counter({"unlock": 70, "lock": 20}), Counter(
            item.kind for item in result.sequences
        ))
        self.assertEqual((), result.unclassified_candidates)
        self.assertEqual(Counter({"unlock": 34, "lock": 1}), Counter(
            item.kind for item in page_3d.sequences
        ))
        self.assertEqual((), page_3d.unclassified_candidates)


if __name__ == "__main__":
    unittest.main()
