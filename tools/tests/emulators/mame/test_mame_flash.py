"""Regression tests for the MAME Flash report and full-image oracle."""

import tempfile
import unittest
from pathlib import Path

from ti84re.emulators.mame.flash import (
    FLASH_SIZE,
    MameFlashReport,
    MameRuntimeError,
    expected_report_values,
    modeled_flash_image,
    parse_flash_report,
    validate_flash_image,
    validate_flash_report,
)

NATIVE_OUTPUT = """\
MAME_FLASH identity machine=ti84pv3 version=0.287
MAME_FLASH immediate initial_target=FF autoselect=01,DA,00,00 legal_stored=50 illegal_stored=D0 partial_reset_byte=D0 cfi_byte=D0 fast_program_stored=D0 fast_exit_id=01 fast_exit_array=D0 top_before=00 adjacent_before=FF boot_before=3E outside_before=9F busy_selected=4C,08 busy_adjacent=4C busy_boot=08 busy_outside=9F
MAME_FLASH complete frame=20 selected=FF adjacent=FF boot=3E outside=9F
"""


def flash_report(**changes) -> MameFlashReport:
    values = expected_report_values()
    values.update(changes)
    return MameFlashReport(**values)


class MameFlashTests(unittest.TestCase):
    def test_parser_decodes_all_three_lines(self):
        report = parse_flash_report(NATIVE_OUTPUT)

        self.assertEqual((0x01, 0xDA, 0, 0), report.autoselect)
        self.assertEqual((0x4C, 0x08), report.busy_selected)
        self.assertEqual(20, report.complete_frame)

    def test_parser_rejects_missing_completion(self):
        with self.assertRaisesRegex(MameRuntimeError, "required report line"):
            parse_flash_report(NATIVE_OUTPUT.split("MAME_FLASH complete")[0])

    def test_oracle_rejects_nor_and_semantics(self):
        with self.assertRaisesRegex(MameRuntimeError, "disagrees"):
            validate_flash_report(flash_report(illegal_stored=0x50))

    def test_oracle_pins_busy_range_bug(self):
        result = validate_flash_report(flash_report())

        self.assertEqual(
            [0xF8000, 0x108000], result["source_model"]["busy_read_range"]
        )
        self.assertEqual(0x08, result["native"]["busy_boot"])

    def test_full_image_model_changes_program_byte_and_top_sector(self):
        source = bytearray(b"\xFF" * FLASH_SIZE)
        source[0xF8000] = 0
        source[0xF9FE0] = 0
        source[0xF9FE1] = 0
        expected = modeled_flash_image(bytes(source))

        self.assertEqual(0xD0, expected[0x20100])
        self.assertEqual(b"\xFF" * 0x2000, expected[0xF8000:0xFA000])

        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.bin"
            output_path = Path(directory) / "output.bin"
            source_path.write_bytes(source)
            output_path.write_bytes(expected)
            result = validate_flash_image(source_path, output_path)

        self.assertEqual(4, result["changed_byte_count"])

    def test_full_image_oracle_rejects_outside_mutation(self):
        source = bytes(b"\xFF" * FLASH_SIZE)
        output = bytearray(modeled_flash_image(source))
        output[0x30000] = 0
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.bin"
            output_path = Path(directory) / "output.bin"
            source_path.write_bytes(source)
            output_path.write_bytes(output)
            with self.assertRaisesRegex(MameRuntimeError, "first offsets"):
                validate_flash_image(source_path, output_path)


if __name__ == "__main__":
    unittest.main()
