"""Regression tests for the MAME CPU-visible Flash-gate oracle."""

import tempfile
import unittest
from pathlib import Path

from ti84re.emulators.mame.flash_gate import (
    FLASH_SIZE,
    PROGRAM_TARGET,
    expected_flash_gate_report,
    modeled_flash_gate_image,
    parse_flash_gate_report,
    validate_flash_gate_image,
    validate_flash_gate_report,
)
from ti84re.emulators.mame.runtime import MameRuntimeError

NATIVE_OUTPUT = """\
MAME_FLASH_GATE identity machine=ti84pv3 version=0.287
MAME_FLASH_GATE mapping page=08 initial=FF
MAME_FLASH_GATE case=locked gate_status=C3 cpu=50 physical=50
MAME_FLASH_GATE case=unlock_between gate_status=C7 cpu=D0 physical=D0
MAME_FLASH_GATE case=relock_between gate_status=C3 cpu=20 physical=20
"""


class MameFlashGateTests(unittest.TestCase):
    def test_parser_decodes_mapping_and_cases(self):
        report = parse_flash_gate_report(NATIVE_OUTPUT)

        self.assertEqual(0x08, report.mapped_page)
        self.assertEqual(0xC7, report.cases[1].gate_status)
        self.assertEqual(0x20, report.cases[2].physical_byte)

    def test_report_oracle_accepts_exact_source_model(self):
        result = validate_flash_gate_report(expected_flash_gate_report())

        self.assertFalse(result["source_model"]["gate_checked_by_memory_write"])

    def test_parser_rejects_missing_case(self):
        incomplete = NATIVE_OUTPUT.replace(
            "MAME_FLASH_GATE case=relock_between gate_status=C3 cpu=20 physical=20\n",
            "",
        )
        with self.assertRaisesRegex(MameRuntimeError, "incomplete"):
            parse_flash_gate_report(incomplete)

    def test_image_model_changes_only_target(self):
        source = b"\xFF" * FLASH_SIZE
        expected = modeled_flash_gate_image(source)

        self.assertEqual(0x20, expected[PROGRAM_TARGET])
        self.assertEqual(1, sum(left != right for left, right in zip(source, expected)))

    def test_image_oracle_rejects_outside_mutation(self):
        source = b"\xFF" * FLASH_SIZE
        output = bytearray(modeled_flash_gate_image(source))
        output[0x30000] = 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.bin"
            output_path = root / "output.bin"
            source_path.write_bytes(source)
            output_path.write_bytes(output)
            with self.assertRaisesRegex(MameRuntimeError, "0x30000"):
                validate_flash_gate_image(source_path, output_path)


if __name__ == "__main__":
    unittest.main()
