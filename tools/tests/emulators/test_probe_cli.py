"""Regression tests for shared emulator-probe CLI plumbing."""

import hashlib
import json
import tempfile
import unittest
from argparse import ArgumentTypeError
from pathlib import Path
from unittest.mock import Mock, patch

from ti84re.emulators.probe_cli import (
    build_mame_result,
    build_tilem_result,
    build_wabbitemu_result,
    positive_int,
    require_exact_hash,
    validate_wabbitemu_probe_inputs,
    write_manifest,
)


class ProbeCliTests(unittest.TestCase):
    def test_parses_positive_prefixed_integer(self):
        self.assertEqual(16, positive_int("0x10"))
        with self.assertRaises(ArgumentTypeError):
            positive_int("0")

    def test_requires_exact_file_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input"
            path.write_bytes(b"probe")
            digest = hashlib.sha256(b"probe").hexdigest()

            self.assertEqual(digest, require_exact_hash(path, digest.upper(), "input"))
            with self.assertRaisesRegex(ValueError, "expected"):
                require_exact_hash(path, "00" * 32, "input")

    def test_writes_canonical_manifest_once(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "run"
            result = {"answer": 42}
            manifest = write_manifest(output_dir, result)

            self.assertEqual(result, json.loads(manifest.read_text()))
            with self.assertRaisesRegex(ValueError, "refusing to reuse"):
                write_manifest(output_dir, result)

    def test_builds_wabbitemu_result_from_composable_callbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            source_rom = Path(directory) / "rom.bin"
            binary = Path(directory) / "adapter"
            source_rom.write_bytes(b"rom")
            binary.write_bytes(b"adapter")
            rom_hash = hashlib.sha256(b"rom").hexdigest()
            binary_hash = hashlib.sha256(b"adapter").hexdigest()

            with patch("ti84re.emulators.probe_cli.TI84_PLUS_OS_255MP_SHA256", rom_hash):
                result = build_wabbitemu_result(
                    binary=binary,
                    source_rom=source_rom,
                    runner=lambda observed_binary, observed_rom: (
                        observed_binary.name,
                        observed_rom.name,
                    ),
                    validator=lambda report: {"native": list(report)},
                    launch="direct core",
                    evidence_scope="emulator only",
                    expected_binary_sha256=binary_hash,
                )

            self.assertEqual(binary_hash, result["binary_sha256"])
            self.assertEqual(
                {"native": ["adapter", "rom.bin"]},
                result["report"],
            )

    def test_builds_tilem_result_from_composable_callbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "probe"
            binary.write_bytes(b"tilem")
            digest = hashlib.sha256(b"tilem").hexdigest()

            result = build_tilem_result(
                binary=binary,
                expected_binary_sha256=digest,
                runner=lambda observed: observed.name,
                validator=lambda report: {"native": report},
                launch="direct core",
                evidence_scope="emulator only",
            )

            self.assertEqual("TilEm", result["emulator"])
            self.assertEqual({"native": "probe"}, result["report"])

    def test_builds_mame_result_from_composable_callbacks(self):
        guarded_run = Mock()
        guarded_run.combined_output = "native report"
        guarded_run.manifest_fields.return_value = {"emulator": "MAME"}

        with (
            patch("ti84re.emulators.probe_cli.run_guarded_probe", return_value=guarded_run),
            patch("ti84re.emulators.probe_cli.validate_rom_warning") as validate_warning,
        ):
            result = build_mame_result(
                executable="mame",
                expected_executable_sha256="12" * 32,
                source_rom=Path("rom.bin"),
                output_dir=Path("run"),
                lua_script=Path("probe.lua"),
                seconds=2,
                load_report=lambda output: {"native": output},
                augment=lambda _run, _rom, _report: {"artifact": "flash"},
                launch="Lua",
                evidence_scope="emulator only",
            )

        validate_warning.assert_called_once_with("native report")
        self.assertEqual({"native": "native report"}, result["report"])
        self.assertEqual("flash", result["artifact"])

    def test_validates_exact_wabbitemu_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            source_rom = Path(directory) / "rom.bin"
            binary = Path(directory) / "adapter"
            source_rom.write_bytes(b"rom")
            binary.write_bytes(b"adapter")
            rom_hash = hashlib.sha256(b"rom").hexdigest()
            binary_hash = hashlib.sha256(b"adapter").hexdigest()

            with patch("ti84re.emulators.probe_cli.TI84_PLUS_OS_255MP_SHA256", rom_hash):
                observed = validate_wabbitemu_probe_inputs(
                    source_rom,
                    binary,
                    binary_hash,
                )

            self.assertEqual((rom_hash, binary_hash), observed)


if __name__ == "__main__":
    unittest.main()
