#!/usr/bin/env python3
"""Tests for ROM provenance generation and enforcement."""

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


from ti84re.rom.provenance import (
    analysis_files,
    artifact_rom_hashes,
    build_manifest,
    combined_digest,
    component_map,
    manifest_rom_hash,
)
from ti84re.rom.signatures import (
    TI84_PLUS_OS_255MP_BOOTFREE_SHA256,
    TI84_PLUS_OS_255MP_SHA256,
)


class RomProvenanceTests(unittest.TestCase):
    def test_script_digest_tracks_nested_tools_and_excludes_runtime_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            maintained = (
                "build.sh", "ti84re/rom/provenance.py", "ghidra/Build.java",
                "symbols/ti83plus.inc", "probes/launch/probe.asm",
                "macros/boot.macro", "js/check.js",
            )
            ignored = (
                "roms/input.txt", "data/result.txt", "oracles/report.json",
                "ti84re/rom/__pycache__/provenance.pyc",
            )
            for name in maintained + ignored:
                path = root / "tools" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("original", encoding="ascii")
            with (
                patch("ti84re.rom.provenance.ROOT", root),
                patch("ti84re.rom.provenance.TOOLS", root / "tools"),
            ):
                files = analysis_files()
                self.assertEqual(
                    {path.relative_to(root / "tools").as_posix() for path in files},
                    set(maintained),
                )
                original = combined_digest(files)
                (root / "tools/ti84re/rom/provenance.py").write_text("changed")
                self.assertNotEqual(original, combined_digest(analysis_files()))

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
            with patch("ti84re.rom.provenance.ROOT", root):
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
            path.write_text(json.dumps({"rom": {"sha256": "12" * 32}}))
            self.assertEqual("12" * 32, manifest_rom_hash(path))
            path.write_text(json.dumps({"rom": {"sha256": "12"}}))
            with self.assertRaisesRegex(ValueError, "64 hexadecimal"):
                manifest_rom_hash(path)
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "missing rom.sha256"):
                manifest_rom_hash(path)

    def test_rejects_missing_hash_among_valid_csv_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mixed.csv"
            path.write_text("rom_sha256,result\n" + "ab" * 32 + ",ok\n,unbound\n")
            with self.assertRaisesRegex(ValueError, "mixed.csv:3"):
                artifact_rom_hashes(path)

    def test_rejects_malformed_nested_hash_among_valid_json_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mixed.json"
            path.write_text(json.dumps({"rom_sha256": "ab" * 32,
                                        "rows": [{"rom_sha256": ""}]}))
            with self.assertRaisesRegex(ValueError, "64 hexadecimal"):
                artifact_rom_hashes(path)

    def test_rejects_empty_rom_objects_but_allows_descriptive_rom_locations(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report.json"
            for invalid in ({}, None, [], True, 17, {"sha256": ""}):
                with self.subTest(invalid=invalid):
                    path.write_text(json.dumps({"rom_sha256": "ab" * 32,
                                                "rows": [{"rom": invalid}]}))
                    with self.assertRaisesRegex(ValueError, "64 hexadecimal"):
                        artifact_rom_hashes(path)
            path.write_text(json.dumps({"rom_sha256": "ab" * 32,
                                        "rows": [{"rom": "38:4180–419D"}]}))
            self.assertEqual({"ab" * 32}, artifact_rom_hashes(path))

    def test_manifest_separates_hardware_and_emulator_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "rom.bin"
            rom.write_bytes(bytes(0x4000))
            with (
                patch("ti84re.rom.provenance.ROOT", Path.cwd()),
                patch("ti84re.rom.provenance.TOOLS", Path("tools")),
                patch("ti84re.rom.provenance.analysis_files", return_value=[]),
                patch("ti84re.rom.provenance.git_state", return_value=("revision", False)),
                patch("ti84re.rom.provenance.classify_boot_page", return_value="unknown"),
            ):
                manifest = build_manifest(
                    rom,
                    model="TI-84 Plus",
                    environment="emulator",
                    asic="unknown",
                    emulator_profile="TilEm x4",
                    os_version="2.55MP",
                    ghidra_version="12.1.2",
                )
        self.assertEqual(manifest["target"]["environment"], "emulator")
        self.assertEqual(manifest["target"]["asic_revision"], "unknown")
        self.assertEqual(manifest["target"]["emulator_profile"], "TilEm x4")
        self.assertIn("--environment emulator", manifest["source_command"])
        self.assertIn("--emulator-profile 'TilEm x4'", manifest["source_command"])


if __name__ == "__main__":
    unittest.main()
