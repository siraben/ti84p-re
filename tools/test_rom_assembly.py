#!/usr/bin/env python3
"""Regression tests for validated local complete-ROM assembly."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from assemble_local_rom import install_file, install_link
from rom_assembly import (
    RETAIL_PAGE_SPECS,
    RomAssemblyError,
    assemble_complete_rom,
    decode_retail_page,
)


TOOLS = Path(__file__).resolve().parent
ROMS = TOOLS / "roms"


class RomAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = (ROMS / "ti84plus_patched.rom").read_bytes()
        cls.appvars = {
            spec.filename: (ROMS / spec.filename).read_bytes()
            for spec in RETAIL_PAGE_SPECS
        }

    def test_reproduces_complete_rom_and_accounts_for_redundant_boot_page(self):
        assembly = assemble_complete_rom(self.base, self.appvars)

        self.assertEqual(
            "7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d",
            assembly.output_sha256,
        )
        self.assertEqual((0x2F, 0x3F), tuple(item.page for item in assembly.patches))
        self.assertEqual(
            (8615, 0),
            tuple(item.changed_bytes for item in assembly.patches),
        )
        self.assertEqual(assembly.image[:0x4000], assembly.page0)

    def test_rejects_corrupt_appvar_checksum_before_identity(self):
        spec = RETAIL_PAGE_SPECS[0]
        corrupt = bytearray(self.appvars[spec.filename])
        corrupt[-1] ^= 1

        with self.assertRaisesRegex(RomAssemblyError, "checksum mismatch"):
            decode_retail_page(bytes(corrupt), spec)

    def test_rejects_swapped_page_artifact(self):
        with self.assertRaisesRegex(RomAssemblyError, "variable name"):
            decode_retail_page(
                self.appvars[RETAIL_PAGE_SPECS[1].filename],
                RETAIL_PAGE_SPECS[0],
            )

    def test_rejects_unpinned_base(self):
        changed = bytearray(self.base)
        changed[0] ^= 1

        with self.assertRaisesRegex(RomAssemblyError, "base ROM SHA-256"):
            assemble_complete_rom(bytes(changed), self.appvars)

    def test_output_install_is_idempotent_and_refuses_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "output.rom"

            self.assertEqual("written", install_file(path, b"one", force=False))
            self.assertEqual("unchanged", install_file(path, b"one", force=False))
            with self.assertRaisesRegex(RomAssemblyError, "use --force"):
                install_file(path, b"two", force=False)
            self.assertEqual("written", install_file(path, b"two", force=True))

    def test_link_install_is_idempotent_and_refuses_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first.rom"
            second = root / "second.rom"
            link = root / "rom.bin"

            self.assertEqual("written", install_link(link, first, force=False))
            self.assertEqual("unchanged", install_link(link, first, force=False))
            with self.assertRaisesRegex(RomAssemblyError, "use --force"):
                install_link(link, second, force=False)


if __name__ == "__main__":
    unittest.main()
