#!/usr/bin/env python3
"""Validate the checked symbol, type-region, and offset-reference registries."""

from __future__ import annotations

import re
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
LOCATION = re.compile(r"(?:ram|io|page_[0-9A-Fa-f]{2}):[0-9A-Fa-f]{1,4}\Z")
RAM_LOCATION = re.compile(r"[0-9A-Fa-f]{1,4}\Z")
SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
TYPE_SIZES = {
    "byte": 1,
    "word": 2,
    "TIVarType": 1,
    "TIFloat": 9,
    "TIOpRegister": 11,
    "Context": 14,
    "TIBasicParserState": 16,
    "LinkPacketHeader": 4,
    "ArchiveWorkspacePrefix": 15,
    "CompactHashResult": 17,
    "MonoFramebuffer": 768,
    "TableValueCache": 189,
    "GraphWindowValues": 207,
    "RamWorkerDescriptor": 2,
    "MathPrintArenaState": 21,
    "EqDispViewportState": 12,
    "EqDispSourceTypeRow": 3,
    "EqDispChildScanRow": 5,
    "EqDispAllocationGeometryRow": 3,
    "TIStatResultsPrefix": 279,
    "SystemFlags": 74,
}


def rows(name: str) -> list[tuple[int, list[str]]]:
    result = []
    for line_number, raw in enumerate((TOOLS / name).read_text().splitlines(), 1):
        line = raw.strip()
        if line and not line.startswith("#"):
            result.append((line_number, line.split()))
    return result


def tab_rows(name: str) -> list[tuple[int, list[str]]]:
    result = []
    for line_number, raw in enumerate((TOOLS / name).read_text().splitlines(), 1):
        line = raw.strip()
        if line and not line.startswith("#"):
            result.append((line_number, [field.strip() for field in line.split("\t")]))
    return result


def canonical_location(text: str) -> str:
    if ":" in text:
        space, address = text.split(":", 1)
    else:
        space, address = "ram", text
    return f"{space.lower()}:{int(address, 16):04x}"


class SymbolTableTests(unittest.TestCase):
    def parse_symbols(self, name: str, ram_only: bool = False):
        parsed = []
        for line_number, fields in rows(name):
            self.assertGreaterEqual(len(fields), 2, f"{name}:{line_number}")
            location, symbol = fields[:2]
            pattern = RAM_LOCATION if ram_only else LOCATION
            self.assertRegex(location, pattern, f"{name}:{line_number}")
            self.assertRegex(symbol, SYMBOL, f"{name}:{line_number}")
            parsed.append((canonical_location(location), symbol, line_number))
        return parsed

    def test_symbol_registries_are_unique_and_disjoint(self):
        tables = {
            "names.txt": self.parse_symbols("names.txt"),
            "labels.txt": self.parse_symbols("labels.txt"),
            "ram.txt": self.parse_symbols("ram.txt", ram_only=True),
        }
        for name, entries in tables.items():
            locations = [entry[0] for entry in entries]
            symbols = [entry[1] for entry in entries]
            self.assertEqual(len(locations), len(set(locations)), f"duplicate location in {name}")
            self.assertEqual(len(symbols), len(set(symbols)), f"duplicate symbol in {name}")

        all_symbols = [entry[1] for entries in tables.values() for entry in entries]
        self.assertEqual(
            len(all_symbols), len(set(all_symbols)),
            "symbol names must be unique across functions, labels, and RAM",
        )

        function_locations = {entry[0] for entry in tables["names.txt"]}
        label_locations = {entry[0] for entry in tables["labels.txt"]}
        self.assertFalse(
            function_locations & label_locations,
            "a location cannot be both a function and a non-function label",
        )

    def test_label_modes(self):
        for line_number, fields in rows("labels.txt"):
            self.assertLessEqual(len(fields), 3, f"labels.txt:{line_number}")
            if len(fields) == 3:
                self.assertIn(fields[2], {"primary", "alias"}, f"labels.txt:{line_number}")

    def test_type_regions_reference_registered_bases(self):
        registered = defaultdict(set)
        for location, symbol, _ in (
            self.parse_symbols("labels.txt") + self.parse_symbols("ram.txt", True)
        ):
            registered[location].add(symbol)
        regions = []
        for line_number, fields in tab_rows("ty_regions.txt"):
            self.assertGreaterEqual(len(fields), 2, f"ty_regions.txt:{line_number}")
            location_text, type_name = fields[:2]
            self.assertTrue(LOCATION.fullmatch(location_text) or RAM_LOCATION.fullmatch(location_text),
                            f"ty_regions.txt:{line_number}")
            self.assertIn(type_name, TYPE_SIZES, f"unknown type at ty_regions.txt:{line_number}")
            count = 1
            if len(fields) >= 3 and fields[2]:
                self.assertTrue(fields[2].isdigit(), f"ty_regions.txt:{line_number}")
                count = int(fields[2])
                self.assertGreater(count, 0, f"ty_regions.txt:{line_number}")
            location = canonical_location(location_text)
            if len(fields) >= 4 and fields[3]:
                self.assertIn(location, registered,
                              f"unregistered typed base at ty_regions.txt:{line_number}")
                self.assertIn(fields[3], registered[location],
                              f"wrong base symbol at ty_regions.txt:{line_number}")

            space, address_text = location.split(":", 1)
            start = int(address_text, 16)
            end = start + TYPE_SIZES[type_name] * count - 1
            if space.startswith("page_"):
                self.assertGreaterEqual(start, 0x4000, f"ty_regions.txt:{line_number}")
                self.assertLessEqual(end, 0x7FFF, f"ty_regions.txt:{line_number}")
            else:
                self.assertLessEqual(end, 0xFFFF, f"ty_regions.txt:{line_number}")
            regions.append((space, start, end, line_number))

        for index, left in enumerate(regions):
            for right in regions[index + 1:]:
                if left[0] != right[0]:
                    continue
                self.assertTrue(
                    left[2] < right[1] or right[2] < left[1],
                    f"overlapping typed regions at ty_regions.txt:{left[3]} and :{right[3]}",
                )

    def test_offset_references_use_registered_bases(self):
        registered = {
            location
            for name, ram_only in (("labels.txt", False), ("ram.txt", True))
            for location, _, _ in self.parse_symbols(name, ram_only)
        }
        for line_number, fields in rows("poffsets.txt"):
            self.assertEqual(len(fields), 4, f"poffsets.txt:{line_number}")
            source, operand, base, offset = fields
            self.assertRegex(source, LOCATION, f"poffsets.txt:{line_number}")
            self.assertRegex(base, LOCATION, f"poffsets.txt:{line_number}")
            self.assertGreaterEqual(int(operand), 0, f"poffsets.txt:{line_number}")
            int(offset, 16)
            self.assertIn(canonical_location(base), registered,
                          f"unregistered poffset base at poffsets.txt:{line_number}")


if __name__ == "__main__":
    unittest.main()
