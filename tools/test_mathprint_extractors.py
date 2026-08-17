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
        self.assertEqual(3, artifact["schema"])
        table = artifact["singleByte"]

        self.assertEqual(0x01, table["page"])
        self.assertEqual(0x4252, table["pointerTableAddress"])
        self.assertEqual(0x100, len(table["entries"]))
        self.assertEqual([0x41, 0x6E, 0x73], table["entries"][0x72]["codes"])
        self.assertEqual([0x73, 0x69, 0x6E, 0x28],
                         table["entries"][0xC2]["codes"])

    def test_two_byte_token_tables_match_rom_spellings(self):
        artifact = self.load("token-strings.json")
        two_byte = artifact["twoByte"]

        self.assertEqual(
            [0x5C, 0x5D, 0x5E, 0x60, 0x61, 0x62,
             0x63, 0x7E, 0xAA, 0xBB, 0xEF],
            two_byte["leadBytes"],
        )
        tables = two_byte["tables"]
        self.assertEqual([0xC1, 0x41, 0x5D],
                         tables["5C"]["entries"][0]["codes"])
        self.assertEqual([0x4C, 0x81],
                         tables["5D"]["entries"][0]["codes"])
        self.assertEqual([0x59, 0x81],
                         tables["5E10"]["entries"][0]["codes"])
        self.assertEqual([0x53, 0x74, 0x72, 0x31],
                         tables["AA"]["entries"][0]["codes"])

    def test_two_byte_table_boundaries_are_explicit(self):
        tables = self.load("token-strings.json")["twoByte"]["tables"]

        self.assertEqual(0x13, len(tables["7E"]["entries"]))
        self.assertEqual(0xF7, len(tables["BB"]["entries"]))
        self.assertEqual(0x41, len(tables["EF"]["entries"]))
        self.assertEqual(
            tables["BB"]["entries"][0xF6],
            tables["EF"]["entries"][0],
        )

    def test_key_to_string_tables_cover_the_complete_main_entry_domain(self):
        strings = self.load("token-strings.json")["keyToString"]

        self.assertEqual((0x01, "01:6D10–6DBC", 0x6E05),
                         (strings["page"], strings["routine"],
                          strings["pointerTableAddress"]))
        self.assertEqual(0x65, len(strings["pointerWords"]))
        self.assertEqual(0x65, len(strings["semanticEntries"]))
        self.assertEqual(strings["pointerWords"], [
            entry["pointer"] for entry in strings["semanticEntries"]
        ])
        self.assertEqual((0x6DDE, 0x0D),
                         (strings["highByteSpecialTableAddress"],
                          len(strings["highByteSpecials"])))
        self.assertEqual(
            [0x5B, 0x6D, 0x75, 0x76, 0x79, 0x78, 0x77,
             0x7B, 0x7A, 0x7C, 0x7D, 0x7E, 0x69],
            [entry["value"] for entry in strings["highByteSpecials"]],
        )
        self.assertEqual([0x4E, 0x6F], strings["special1040"]["codes"])

    def test_mathprint_inline_string_conditions_are_explicit(self):
        inline = self.load("token-strings.json")["mathPrintInlineStrings"]

        self.assertEqual((0x39, "39:6B62–6BA8", 6),
                         (inline["page"], inline["routine"],
                          len(inline["entries"])))
        self.assertEqual([0xFB, 0xC8], inline["entries"][0]["cell"])
        self.assertTrue(inline["entries"][0]["requiresHBit0"])
        self.assertTrue(all(
            not entry["requiresHBit0"] for entry in inline["entries"][1:]
        ))

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

    def test_display_byte_tables_cover_the_complete_main_entry_domain(self):
        tables = self.load("layout.json")["displayByteMap"]

        self.assertEqual((0x07, "07:44DE–4538"),
                         (tables["page"], tables["routine"]))
        self.assertEqual((0x4000, 0x100, 0x84),
                         (tables["ordinary"]["address"],
                          len(tables["ordinary"]["values"]),
                          tables["ordinary"]["values"][0]))
        self.assertEqual((0x4099, 0x69, 0xA8),
                         (tables["feLow"]["address"],
                          len(tables["feLow"]["values"]),
                          tables["feLow"]["values"][0]))
        self.assertEqual((0x4102, 0x97, [0x7E, 0x00]),
                         (tables["feHigh"]["address"],
                          len(tables["feHigh"]["entries"]),
                          tables["feHigh"]["entries"][0]))
        self.assertEqual((0x422C, 0x100, [0x61, 0x00]),
                         (tables["fc"]["address"],
                          len(tables["fc"]["entries"]),
                          tables["fc"]["entries"][0]))
        self.assertEqual((0x4426, 0x8C, [0x5E, 0x82]),
                         (tables["fb"]["address"],
                          len(tables["fb"]["entries"]),
                          tables["fb"]["entries"][0]))


if __name__ == "__main__":
    unittest.main()
