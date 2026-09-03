"""Regression tests for the MAME sector and chip-erase report oracle."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ti84re.emulators.mame.flash_erase import (
    ERASED_FLASH_SHA256,
    FLASH_SIZE,
    expected_flash_erase_report,
    parse_flash_erase_report,
    validate_erased_flash_image,
    validate_flash_erase_report,
)
from ti84re.emulators.mame.runtime import MameRuntimeError

NATIVE_OUTPUT = """\
MAME_FLASH_ERASE identity machine=ti84pv3 version=0.287
MAME_FLASH_ERASE immediate case=regular64 start=E0000 size=10000 probe_addr=F0000 before=00 selected=4C,08 selected_end=4C probe=00
MAME_FLASH_ERASE complete case=regular64 frame=50 before=00 selected=FF selected_end=FF probe=00
MAME_FLASH_ERASE immediate case=top32 start=F0000 size=08000 probe_addr=F8000 before=00 selected=4C,08 selected_end=4C probe=08
MAME_FLASH_ERASE complete case=top32 frame=75 before=00 selected=FF selected_end=FF probe=00
MAME_FLASH_ERASE immediate case=top8a start=F8000 size=02000 probe_addr=FA000 before=00 selected=4C,08 selected_end=4C probe=08
MAME_FLASH_ERASE complete case=top8a frame=88 before=00 selected=FF selected_end=FF probe=00
MAME_FLASH_ERASE immediate case=top8b start=FA000 size=02000 probe_addr=FC000 before=00 selected=4C,08 selected_end=4C probe=08
MAME_FLASH_ERASE complete case=top8b frame=101 before=00 selected=FF selected_end=FF probe=00
MAME_FLASH_ERASE immediate case=top16 start=FC000 size=04000 probe_addr=FBFFE before=00 selected=4C,08 selected_end=4C probe=00
MAME_FLASH_ERASE complete case=top16 frame=126 before=00 selected=FF selected_end=FF probe=00
MAME_FLASH_ERASE chip_immediate start_seconds=2 array0=FF array1=FF stale_start=4C stale_end=08
MAME_FLASH_ERASE chip_complete complete_seconds=18 array0=FF array1=FF stale_start=FF stale_end=FF
"""


class MameFlashEraseTests(unittest.TestCase):
    def test_parser_decodes_all_sector_and_chip_cases(self):
        report = parse_flash_erase_report(NATIVE_OUTPUT)

        self.assertEqual(5, len(report.sectors))
        self.assertEqual("top8a", report.sectors[2].name)
        self.assertEqual(0x08, report.sectors[2].immediate_probe)
        self.assertEqual(18, report.chip.complete_seconds)

    def test_oracle_accepts_exact_source_model(self):
        expected = expected_flash_erase_report()
        result = validate_flash_erase_report(expected)

        self.assertEqual(0x10000, result["source_model"]["sector_busy_range_size"])

    def test_oracle_rejects_missing_sector_case(self):
        incomplete = "\n".join(
            line for line in NATIVE_OUTPUT.splitlines() if "case=top8b" not in line
        )
        with self.assertRaisesRegex(MameRuntimeError, "incomplete"):
            parse_flash_erase_report(incomplete)

    def test_oracle_rejects_unordered_completion(self):
        report = expected_flash_erase_report()
        sectors = list(report.sectors)
        sectors[1] = replace(
            sectors[1], complete_frame=sectors[0].complete_frame
        )
        with self.assertRaisesRegex(MameRuntimeError, "not ordered"):
            validate_flash_erase_report(
                type(report)(
                    machine=report.machine,
                    version=report.version,
                    sectors=tuple(sectors),
                    chip=report.chip,
                )
            )

    def test_complete_image_must_be_all_ff(self):
        source = bytes(index & 0xFF for index in range(FLASH_SIZE))
        erased = b"\xFF" * FLASH_SIZE
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.bin"
            output_path = root / "output.bin"
            source_path.write_bytes(source)
            output_path.write_bytes(erased)
            result = validate_erased_flash_image(source_path, output_path)

        self.assertEqual(ERASED_FLASH_SHA256, result["output_sha256"])
        self.assertEqual(FLASH_SIZE // 256 * 255, result["changed_byte_count"])

    def test_complete_image_rejects_one_non_ff_byte(self):
        source = b"\xFF" * FLASH_SIZE
        output = bytearray(source)
        output[0xFC000] = 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.bin"
            output_path = root / "output.bin"
            source_path.write_bytes(source)
            output_path.write_bytes(output)
            with self.assertRaisesRegex(MameRuntimeError, "0xFC000"):
                validate_erased_flash_image(source_path, output_path)


if __name__ == "__main__":
    unittest.main()
