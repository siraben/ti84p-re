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
PORT_LOCATION = re.compile(r"[0-9A-Fa-f]{1,2}\Z")
HEX_WORD = re.compile(r"[0-9A-Fa-f]{4}\Z")
HEX_OFFSET = re.compile(r"[0-9A-Fa-f]{4}\Z")
HEX_PAGE = re.compile(r"[0-9A-Fa-f]{2}\Z")
DECIMAL = re.compile(r"[0-9]+\Z")
SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
TYPE_SIZES = {
    "byte": 1,
    "word": 2,
    "TIVarType": 1,
    "TIKeyCode": 1,
    "TIError": 1,
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


def canonical_location(text: str, default_space: str = "ram") -> str:
    if ":" in text:
        space, address = text.split(":", 1)
    else:
        space, address = default_space, text
    return f"{space.lower()}:{int(address, 16):04x}"


def range_is_mapped(space: str, start: int, end: int) -> bool:
    if space == "ram":
        return 0 <= start <= end <= 0x3FFF or 0x8000 <= start <= end <= 0xFFFF
    if space == "io":
        return 0 <= start <= end <= 0xFF
    if space.startswith("page_"):
        page = int(space.removeprefix("page_"), 16)
        return 1 <= page <= 0x3F and 0x4000 <= start <= end <= 0x7FFF
    return False


def location_is_mapped(location: str) -> bool:
    space, address_text = location.split(":", 1)
    address = int(address_text, 16)
    return range_is_mapped(space, address, address)


class SymbolTableTests(unittest.TestCase):
    def test_address_and_numeric_syntax_boundaries(self):
        self.assertTrue(location_is_mapped("page_01:4000"))
        self.assertTrue(location_is_mapped("page_3f:7fff"))
        self.assertFalse(location_is_mapped("page_00:4000"))
        self.assertFalse(location_is_mapped("page_40:4000"))
        self.assertFalse(location_is_mapped("ram:4000"))
        self.assertFalse(range_is_mapped("ram", 0x3FFF, 0x4000))

        self.assertIsNotNone(HEX_OFFSET.fullmatch("000d"))
        for invalid in ("d", "0000d", "0xd", "+000d", "000djunk"):
            self.assertIsNone(HEX_OFFSET.fullmatch(invalid))

    def parse_symbols(
        self,
        name: str,
        raw_space: str | None = None,
        field_counts: tuple[int, ...] = (2,),
    ):
        parsed = []
        for line_number, fields in rows(name):
            self.assertIn(len(fields), field_counts, f"{name}:{line_number}")
            location, symbol = fields[:2]
            if raw_space == "ram":
                pattern = RAM_LOCATION
            elif raw_space == "io":
                pattern = PORT_LOCATION
            else:
                pattern = LOCATION
            self.assertIsNotNone(pattern.fullmatch(location), f"{name}:{line_number}")
            self.assertIsNotNone(SYMBOL.fullmatch(symbol), f"{name}:{line_number}")
            canonical = canonical_location(location, raw_space or "ram")
            self.assertTrue(location_is_mapped(canonical), f"{name}:{line_number}")
            parsed.append((canonical, symbol, line_number))
        return parsed

    def parse_bcall_target_locations(self, name: str):
        locations = set()
        for line_number, fields in rows(name):
            self.assertEqual(len(fields), 4, f"{name}:{line_number}")
            symbol, bcall_id, address, page = fields
            self.assertIsNotNone(SYMBOL.fullmatch(symbol), f"{name}:{line_number}")
            self.assertIsNotNone(HEX_WORD.fullmatch(bcall_id), f"{name}:{line_number}")
            self.assertIsNotNone(HEX_WORD.fullmatch(address), f"{name}:{line_number}")
            self.assertIsNotNone(HEX_PAGE.fullmatch(page), f"{name}:{line_number}")
            space = "ram" if int(page, 16) == 0 else f"page_{int(page, 16):02x}"
            location = canonical_location(f"{space}:{address}")
            self.assertTrue(location_is_mapped(location), f"{name}:{line_number}")
            locations.add(location)
        return locations

    def test_symbol_registries_are_unique_and_disjoint(self):
        tables = {
            "names.txt": self.parse_symbols("names.txt"),
            "labels.txt": self.parse_symbols("labels.txt", field_counts=(2, 3)),
            "ram.txt": self.parse_symbols("ram.txt", raw_space="ram"),
            "ports.txt": self.parse_symbols("ports.txt", raw_space="io"),
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
        function_locations |= self.parse_bcall_target_locations("bcall_targets.txt")
        function_locations |= self.parse_bcall_target_locations("bcalls8x_targets.txt")
        label_locations = {entry[0] for entry in tables["labels.txt"]}
        ram_locations = {entry[0] for entry in tables["ram.txt"]}
        port_locations = {entry[0] for entry in tables["ports.txt"]}
        self.assertFalse(
            function_locations & label_locations,
            "a location cannot be both a function and a non-function label",
        )
        self.assertFalse(
            function_locations & (ram_locations | port_locations),
            "a location cannot be both a function and a RAM or port symbol",
        )

        label_modes = {
            canonical_location(fields[0]): fields[2] if len(fields) == 3 else "primary"
            for _, fields in rows("labels.txt")
        }
        for location in label_locations & (ram_locations | port_locations):
            self.assertEqual(
                label_modes[location], "alias",
                f"a label overlapping a RAM or port symbol must be an alias: {location}",
            )

    def test_label_modes(self):
        for line_number, fields in rows("labels.txt"):
            self.assertLessEqual(len(fields), 3, f"labels.txt:{line_number}")
            if len(fields) == 3:
                self.assertIn(
                    fields[2], {"primary", "alias", "entry"},
                    f"labels.txt:{line_number}",
                )

    def test_type_regions_reference_registered_bases(self):
        registered = defaultdict(set)
        for location, symbol, _ in (
            self.parse_symbols("labels.txt", field_counts=(2, 3))
            + self.parse_symbols("ram.txt", raw_space="ram")
        ):
            registered[location].add(symbol)
        regions = []
        for line_number, fields in tab_rows("ty_regions.txt"):
            self.assertGreaterEqual(len(fields), 2, f"ty_regions.txt:{line_number}")
            self.assertLessEqual(len(fields), 4, f"ty_regions.txt:{line_number}")
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
            self.assertTrue(location_is_mapped(location), f"ty_regions.txt:{line_number}")
            if len(fields) >= 4 and fields[3]:
                self.assertIn(location, registered,
                              f"unregistered typed base at ty_regions.txt:{line_number}")
                self.assertIn(fields[3], registered[location],
                              f"wrong base symbol at ty_regions.txt:{line_number}")

            space, address_text = location.split(":", 1)
            start = int(address_text, 16)
            end = start + TYPE_SIZES[type_name] * count - 1
            self.assertTrue(
                range_is_mapped(space, start, end), f"ty_regions.txt:{line_number}"
            )
            regions.append((space, start, end, line_number))

        function_locations = {
            location for location, _, _ in self.parse_symbols("names.txt")
        }
        function_locations |= self.parse_bcall_target_locations("bcall_targets.txt")
        function_locations |= self.parse_bcall_target_locations("bcalls8x_targets.txt")
        for location in function_locations:
            space, address_text = location.split(":", 1)
            address = int(address_text, 16)
            for region_space, start, end, line_number in regions:
                if space == region_space and start <= address <= end:
                    self.fail(
                        f"function {location} overlaps typed region at "
                        f"ty_regions.txt:{line_number}"
                    )

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
            for name, raw_space, field_counts in (
                ("labels.txt", None, (2, 3)),
                ("ram.txt", "ram", (2,)),
            )
            for location, _, _ in self.parse_symbols(name, raw_space, field_counts)
        }
        typed_regions = {}
        for _, fields in tab_rows("ty_regions.txt"):
            location, type_name = fields[:2]
            count = int(fields[2]) if len(fields) >= 3 and fields[2] else 1
            typed_regions[canonical_location(location)] = TYPE_SIZES[type_name] * count

        sources = set()
        for line_number, fields in rows("poffsets.txt"):
            self.assertEqual(len(fields), 4, f"poffsets.txt:{line_number}")
            source, operand, base, offset = fields
            self.assertIsNotNone(LOCATION.fullmatch(source), f"poffsets.txt:{line_number}")
            self.assertIsNotNone(LOCATION.fullmatch(base), f"poffsets.txt:{line_number}")
            self.assertIsNotNone(DECIMAL.fullmatch(operand), f"poffsets.txt:{line_number}")
            self.assertIsNotNone(HEX_OFFSET.fullmatch(offset), f"poffsets.txt:{line_number}")
            self.assertGreaterEqual(int(operand), 0, f"poffsets.txt:{line_number}")
            canonical_source = canonical_location(source)
            canonical_base = canonical_location(base)
            self.assertTrue(location_is_mapped(canonical_source), f"poffsets.txt:{line_number}")
            self.assertTrue(location_is_mapped(canonical_base), f"poffsets.txt:{line_number}")
            source_operand = (canonical_source, int(operand))
            self.assertNotIn(source_operand, sources, f"duplicate poffset source at line {line_number}")
            sources.add(source_operand)

            offset_value = int(offset, 16)
            self.assertGreaterEqual(offset_value, 0, f"negative poffset at line {line_number}")
            self.assertIn(canonical_base, registered,
                          f"unregistered poffset base at poffsets.txt:{line_number}")
            self.assertIn(canonical_base, typed_regions,
                          f"untyped poffset base at poffsets.txt:{line_number}")
            self.assertLess(offset_value, typed_regions[canonical_base],
                            f"out-of-bounds poffset at poffsets.txt:{line_number}")


if __name__ == "__main__":
    unittest.main()
