#!/usr/bin/env python3
"""Regression checks for the 24 include-backed bcall rows found by the corpus audit."""

from __future__ import annotations

import csv
import re
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bcall_tables import find_main_table_page, main_target, read_main_names, target_is_valid
from rom_image import RomImage


TOOLS = Path(__file__).resolve().parent
EXPECTED = {
    0x4030: ("_newContext", 0x00, 0x077E),
    0x4051: ("_lcd_busy", 0x00, 0x0CC3),
    0x41D4: ("_ShRAcc", 0x00, 0x1BCB),
    0x4744: ("_GetK", 0x37, 0x746D),
    0x4909: ("_bufInsert", 0x06, 0x42E5),
    0x4936: ("_BufClear", 0x00, 0x222E),
    0x4A02: ("_ConvKeyToTok", 0x07, 0x44DE),
    0x4D41: ("_ErrCustom1", 0x00, 0x2771),
    0x4E61: ("_GetStringInput2", 0x37, 0x5194),
    0x4ED6: ("_SendPacket", 0x3C, 0x4139),
    0x4F3C: ("_FlashWriteDisable", 0x3C, 0x66D5),
    0x4F66: ("_SetGetKeyHook", 0x3B, 0x7D00),
    0x4F69: ("_ClrCursorHook", 0x3B, 0x7AEA),
    0x4F6F: ("_ClrRawKeyHook", 0x3B, 0x7B88),
    0x4F99: ("_SetTokenHook", 0x3B, 0x7D0B),
    0x500B: ("_GetKeyRetOff", 0x06, 0x491A),
    0x5011: ("_FillBasePageTable", 0x00, 0x2692),
    0x5014: ("_ArcChk", 0x3D, 0x61AF),
    0x5026: ("_SetParserHook", 0x3B, 0x7D6E),
    0x5029: ("_ClearParserHook", 0x3B, 0x7C3B),
    0x50C8: ("_UngroupVar", 0x39, 0x764A),
    0x50CE: ("_SetSilentLinkHook", 0x3B, 0x7DBB),
    0x50E0: ("_NZIf83Plus", 0x00, 0x1837),
    0x5221: ("_Chk_Batt_Level", 0x33, 0x4E9B),
}


def include_equates() -> dict[int, str]:
    equates: dict[int, str] = {}
    pattern = re.compile(r"^\s*(\S+)\s+equ\s+([0-9A-Fa-f]+)h\b", re.IGNORECASE)
    for line in (TOOLS / "ti83plus.inc").read_text(encoding="latin-1").splitlines():
        match = pattern.match(line)
        if match:
            equates[int(match.group(2), 16)] = match.group(1)
    return equates


def target_rows() -> dict[int, tuple[str, int, int]]:
    rows: dict[int, tuple[str, int, int]] = {}
    for line in (TOOLS / "bcall_targets.txt").read_text(encoding="ascii").splitlines():
        name, id_text, address, page = line.split()
        rows[int(id_text, 16)] = (name, int(page, 16), int(address, 16))
    return rows


class CommunityBcallCoverageTests(unittest.TestCase):
    def test_all_24_are_official_include_equates_and_curated_rows(self) -> None:
        curated = read_main_names(TOOLS / "bcalls.txt")
        official = include_equates()
        generated = target_rows()
        self.assertEqual(len(EXPECTED), 24)
        for bcall_id, expected in EXPECTED.items():
            name, page, address = expected
            self.assertEqual(official.get(bcall_id), name)
            self.assertEqual(curated.get(bcall_id), name)
            self.assertEqual(generated.get(bcall_id), (name, page, address))

    def test_each_table_entry_decodes_to_the_committed_valid_target(self) -> None:
        rom = RomImage.from_path(TOOLS / "rom.bin")
        names = read_main_names(TOOLS / "bcalls.txt")
        page, _score = find_main_table_page(rom, names)
        self.assertEqual(page, 0x3B)
        for bcall_id, (name, expected_page, expected_address) in EXPECTED.items():
            target = main_target(rom, page, bcall_id, name)
            self.assertEqual((target.page, target.address), (expected_page, expected_address))
            self.assertTrue(target_is_valid(rom, target))

    def test_map_provenance_counts_remain_separated(self) -> None:
        curated = read_main_names(TOOLS / "bcalls.txt")
        official = include_equates()
        include_backed = {bcall_id for bcall_id in curated if bcall_id in official}
        inferred = set(curated) - include_backed
        self.assertEqual(len(curated), 645)
        self.assertEqual(len(include_backed), 623)
        self.assertEqual(len(inferred), 22)

    def test_every_row_has_a_behavior_class_and_existing_documentation(self) -> None:
        with (TOOLS / "data/community-bcall-behavior-coverage.csv").open(
            newline="", encoding="ascii"
        ) as stream:
            rows = list(csv.DictReader(stream))
        by_id = {int(row["id"], 16): row for row in rows}
        self.assertEqual(set(by_id), set(EXPECTED))
        for bcall_id, row in by_id.items():
            self.assertEqual(row["name"], EXPECTED[bcall_id][0])
            self.assertEqual(row["rom_status"], "decoded")
            self.assertIn(
                row["dynamic_status"],
                {
                    "traced",
                    "partial-trace",
                    "return-traced",
                    "model-probed",
                    "not-run",
                },
            )
            self.assertTrue((TOOLS.parent / row["documentation"]).is_file())
            if row["evidence_file"]:
                self.assertTrue((TOOLS / "data" / row["evidence_file"]).is_file())


if __name__ == "__main__":
    unittest.main()
