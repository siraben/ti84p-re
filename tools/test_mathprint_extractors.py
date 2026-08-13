#!/usr/bin/env python3
"""Schema and bounds regressions for committed MathPrint artifacts."""

import json
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from rom_signatures import TI84_PLUS_OS_255MP_SHA256


class ArtifactTests(unittest.TestCase):
    def load(self, name):
        return json.loads((ROOT / "web" / "mathprint" / name).read_text())

    def test_artifacts_identify_the_pinned_rom(self):
        for name in ("font.json", "layout.json", "token-strings.json"):
            self.assertEqual(TI84_PLUS_OS_255MP_SHA256,
                             self.load(name)["romSha256"])

    def test_single_byte_token_spellings_match_rom_table(self):
        artifact = self.load("token-strings.json")
        table = artifact["singleByte"]

        self.assertEqual(0x01, table["page"])
        self.assertEqual(0x4252, table["pointerTableAddress"])
        self.assertEqual(0x100, len(table["entries"]))
        self.assertEqual([0x41, 0x6E, 0x73], table["entries"][0x72]["codes"])
        self.assertEqual([0x73, 0x69, 0x6E, 0x28],
                         table["entries"][0xC2]["codes"])

    def test_two_byte_token_leads_remain_separate(self):
        artifact = self.load("token-strings.json")

        self.assertEqual(
            [0x5C, 0x5D, 0x5E, 0x60, 0x61, 0x62,
             0x63, 0x7E, 0xAA, 0xBB, 0xEF],
            artifact["twoByteLeadBytes"],
        )

    def test_descriptor_cells_match_declared_dimensions(self):
        for descriptor in self.load("layout.json")["descriptors"]:
            cols_rows = descriptor["cols_rows"]
            expected = (cols_rows & 0xFF) * (cols_rows >> 8)
            self.assertEqual(expected, len(descriptor["cells"]),
                             f"descriptor 39:{descriptor['addr']:04X}")

    def test_handler_records_match_row_and_cell_counts(self):
        layout = self.load("layout.json")
        self.assertEqual(layout["classCount"], len(layout["classes"]))
        for record in layout["classes"]:
            if "rows" not in record:
                continue
            self.assertEqual(record["rows"], len(record["items"]))
            for item in record["items"]:
                self.assertEqual(item["count"], len(item["cells"]))


if __name__ == "__main__":
    unittest.main()
