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
        for name in ("font.json", "layout.json"):
            self.assertEqual(TI84_PLUS_OS_255MP_SHA256,
                             self.load(name)["romSha256"])

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
