#!/usr/bin/env python3
"""Tests for ROM provenance generation and enforcement."""

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rom_provenance import (  # noqa: E402
    artifact_rom_hashes,
    combined_digest,
    component_map,
    manifest_rom_hash,
)
from rom_signatures import (  # noqa: E402
    TI84_PLUS_OS_255MP_BOOTFREE_SHA256,
    TI84_PLUS_OS_255MP_SHA256,
)


class RomProvenanceTests(unittest.TestCase):
    def test_classifies_retail_and_bootfree_components(self):
        retail = component_map(TI84_PLUS_OS_255MP_SHA256)
        bootfree = component_map(TI84_PLUS_OS_255MP_BOOTFREE_SHA256)
        self.assertEqual("D84PBE2.8Xv", retail[1]["name"])
        self.assertEqual("BootFree 11.259 page", bootfree[1]["name"])

    def test_combined_digest_binds_name_and_contents(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            first = root / "a.py"
            second = root / "b.py"
            first.write_text("one", encoding="ascii")
            second.write_text("two", encoding="ascii")
            with patch("rom_provenance.ROOT", root):
                before = combined_digest([first, second])
                second.write_text("changed", encoding="ascii")
                after = combined_digest([first, second])
            self.assertNotEqual(before, after)

    def test_reads_csv_and_nested_json_hashes(self):
        value = "ab" * 32
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            table = root / "result.csv"
            with table.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["rom_sha256"])
                writer.writeheader()
                writer.writerow({"rom_sha256": value})
            report = root / "result.json"
            report.write_text(
                json.dumps({"rows": [{"rom": {"sha256": value}}]}),
                encoding="utf-8",
            )
            self.assertEqual({value}, artifact_rom_hashes(table))
            self.assertEqual({value}, artifact_rom_hashes(report))

    def test_manifest_requires_rom_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            path.write_text(json.dumps({"rom": {"sha256": "12"}}))
            self.assertEqual("12", manifest_rom_hash(path))
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "missing rom.sha256"):
                manifest_rom_hash(path)


if __name__ == "__main__":
    unittest.main()
