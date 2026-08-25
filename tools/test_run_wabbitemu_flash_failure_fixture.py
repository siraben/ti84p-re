"""Regression tests for the guarded Wabbitemu Flash-failure CLI."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from run_wabbitemu_flash_failure_fixture import validate_probe_inputs


class WabbitemuFlashFailureCliTests(unittest.TestCase):
    def test_requires_exact_rom_and_adapter_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            rom = Path(directory) / "rom.bin"
            binary = Path(directory) / "adapter"
            rom.write_bytes(b"retail-rom")
            binary.write_bytes(b"guarded-adapter")
            rom_hash = hashlib.sha256(rom.read_bytes()).hexdigest()
            binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()

            with patch("probe_cli.TI84_PLUS_OS_255MP_SHA256", rom_hash):
                identity = validate_probe_inputs(rom, binary, binary_hash.upper())

            self.assertEqual(binary_hash, identity["binary_sha256"])
            self.assertEqual(rom_hash, identity["source_rom_sha256"])

    def test_rejects_arbitrary_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            rom = Path(directory) / "rom.bin"
            binary = Path(directory) / "adapter"
            rom.write_bytes(b"retail-rom")
            binary.write_bytes(b"arbitrary-adapter")
            rom_hash = hashlib.sha256(rom.read_bytes()).hexdigest()

            with (
                patch("probe_cli.TI84_PLUS_OS_255MP_SHA256", rom_hash),
                self.assertRaisesRegex(ValueError, "native runner SHA-256"),
            ):
                validate_probe_inputs(rom, binary, "00" * 32)


if __name__ == "__main__":
    unittest.main()
