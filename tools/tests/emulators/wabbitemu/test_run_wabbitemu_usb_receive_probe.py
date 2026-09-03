"""Regression tests for the guarded retail USB receive CLI."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ti84re.emulators.wabbitemu.run_usb_receive_probe import validate_probe_inputs


class WabbitemuUsbReceiveCliTests(unittest.TestCase):
    def test_accepts_exact_rom_and_adapter_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            rom = Path(directory) / "rom.bin"
            binary = Path(directory) / "adapter"
            rom.write_bytes(b"retail-rom")
            binary.write_bytes(b"adapter")
            rom_hash = hashlib.sha256(rom.read_bytes()).hexdigest()
            binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()

            with patch(
                "ti84re.emulators.probe_cli.TI84_PLUS_OS_255MP_SHA256",
                rom_hash,
            ):
                observed = validate_probe_inputs(rom, binary, binary_hash.upper())

            self.assertEqual((rom_hash, binary_hash), observed)

    def test_rejects_wrong_rom_or_adapter_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            rom = Path(directory) / "rom.bin"
            binary = Path(directory) / "adapter"
            rom.write_bytes(b"retail-rom")
            binary.write_bytes(b"adapter")
            rom_hash = hashlib.sha256(rom.read_bytes()).hexdigest()
            binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()

            with self.assertRaisesRegex(ValueError, "exact local"):
                validate_probe_inputs(rom, binary, binary_hash)
            with (
                patch(
                    "ti84re.emulators.probe_cli.TI84_PLUS_OS_255MP_SHA256",
                    rom_hash,
                ),
                self.assertRaisesRegex(ValueError, "binary SHA-256"),
            ):
                validate_probe_inputs(rom, binary, "00" * 32)


if __name__ == "__main__":
    unittest.main()
