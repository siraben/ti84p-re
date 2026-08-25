#!/usr/bin/env python3
"""Regression tests for the recovery-gated hidden-column LCD experiment."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_hardware_probes import PROBES
from build_lcd_hidden_lab_probe import (
    ACK_TEXT,
    APPVAR,
    PAYLOAD_SIZE,
    PROGRAM,
    SOURCE,
    LcdHiddenLabBuildError,
    assemble,
    build,
    validate_recovery_inputs,
)
from hardware_probe import (
    ProbeFormatError,
    ProbeFrame,
    decode_probe_measurements,
    decode_ti_variable_file,
)
from run_lcd_hidden_lab_emulator import validate_capture
from tibasic_samples import T


class LcdHiddenLabProbeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="lcd-hidden-lab-test-")
        self.root = Path(self.directory.name)
        self.backup = self.root / "calculator.8xg"
        self.backup.write_bytes(b"test calculator backup\0" * 8)
        self.backup_sha256 = hashlib.sha256(self.backup.read_bytes()).hexdigest()
        self.notes = self.root / "recovery.txt"
        self.notes.write_text(
            "Verify the backup first. If the LCD stalls, reset the calculator, "
            "then restore the backup.\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.directory.cleanup()

    def recovery(self):
        return validate_recovery_inputs(
            acknowledgement=ACK_TEXT,
            expected_asic=0x45,
            controller_id="test-module-01",
            backup_file=self.backup,
            expected_backup_sha256=self.backup_sha256,
            recovery_notes=self.notes,
        )

    def test_recovery_gate_hashes_real_backup_and_notes(self):
        recovery = self.recovery()

        self.assertEqual(self.backup_sha256, recovery["backup"]["sha256"])
        self.assertEqual(0x45, recovery["expected_asic"])
        self.assertEqual("test-module-01", recovery["controller_id"])

    def test_recovery_gate_rejects_missing_or_placeholder_inputs(self):
        cases = (
            {"acknowledgement": "yes"},
            {"expected_asic": 0x100},
            {"controller_id": "unknown"},
            {"expected_backup_sha256": "0" * 64},
            {"expected_backup_sha256": "1" * 64},
        )
        defaults = {
            "acknowledgement": ACK_TEXT,
            "expected_asic": 0x45,
            "controller_id": "test-module-01",
            "backup_file": self.backup,
            "expected_backup_sha256": self.backup_sha256,
            "recovery_notes": self.notes,
        }

        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(LcdHiddenLabBuildError):
                    validate_recovery_inputs(**(defaults | override))

    def test_recovery_gate_requires_specific_notes(self):
        self.notes.write_text("Try again later.\n", encoding="utf-8")

        with self.assertRaisesRegex(LcdHiddenLabBuildError, "backup, reset, and restore"):
            self.recovery()

    def test_lab_probe_is_excluded_from_default_artifacts(self):
        self.assertNotIn("lcd-hidden-lab", PROBES)
        self.assertEqual(25, len(PROBES))

    @unittest.skipUnless(shutil.which("spasm"), "SPASM-ng is not on PATH")
    def test_source_requires_compile_time_gates(self):
        output = self.root / "ungated.bin"

        completed = subprocess.run(
            ["spasm", "-N", "-I", str(SOURCE.parent), str(SOURCE), str(output)],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(0, completed.returncode)

    @unittest.skipUnless(shutil.which("spasm"), "SPASM-ng is not on PATH")
    def test_build_packages_the_exact_validated_machine_image(self):
        output = self.root / "artifact"

        manifest = build(
            output,
            spasm="spasm",
            expected_asic=0x45,
            recovery=self.recovery(),
        )
        variable = decode_ti_variable_file((output / f"{PROGRAM}.8xp").read_bytes())
        body = variable.data[2:]
        recovered = bytes.fromhex(body[3:-1].decode("ascii"))

        self.assertEqual(PROGRAM, variable.name)
        self.assertEqual(bytes((T["2byte"], T["asmprgm"], T["enter"])), body[:3])
        self.assertEqual(assemble(spasm="spasm", expected_asic=0x45), recovered)
        self.assertEqual(PAYLOAD_SIZE, manifest["payload_size"])
        self.assertEqual(APPVAR, manifest["result_appvar"])
        self.assertEqual(self.backup_sha256, manifest["recovery"]["backup"]["sha256"])

    @unittest.skipUnless(shutil.which("spasm"), "SPASM-ng is not on PATH")
    def test_tracked_emulator_record_matches_both_asic_specific_images(self):
        record = json.loads(
            (Path(__file__).parent / "fixtures" / "lcd-hidden-lab-emulators.json")
            .read_text(encoding="utf-8")
        )

        self.assertEqual(PAYLOAD_SIZE, record["payload_size"])
        self.assertEqual(
            hashlib.sha256(SOURCE.read_bytes()).hexdigest(), record["source_sha256"]
        )
        for backend, run in record["runs"].items():
            with self.subTest(backend=backend):
                image = assemble(spasm="spasm", expected_asic=run["expected_asic"])
                self.assertEqual(run["machine_code_size"], len(image))
                self.assertEqual(
                    run["machine_code_sha256"], hashlib.sha256(image).hexdigest()
                )
                self.assertTrue(run["appvar_matches"])
                self.assertEqual(0, run["visible_restore_mismatches"])
                self.assertEqual(0, run["hidden_restore_mismatches"])

    def test_decoder_reports_visible_alias_and_verified_restoration(self):
        payload = bytearray(PAYLOAD_SIZE)
        before = bytearray(768)
        direct = bytearray(before)
        wrap = bytearray(before)
        direct[10] = 0xA5
        wrap[0] = 0xA2
        payload[0:8] = bytes((1, 5, 0x63, 7, 0x20, 0x80, 0, 0))
        payload[8:10] = (1).to_bytes(2, "little")
        payload[10:12] = (1).to_bytes(2, "little")
        payload[15:31] = bytes.fromhex("00000000A55AC33C0000A10000000000")
        payload[31:799] = before
        payload[799:1567] = direct
        payload[1567:2335] = wrap

        report = decode_probe_measurements(
            ProbeFrame(probe_id=17, asic_id=0x44, status=0xE1, payload=bytes(payload))
        )

        self.assertEqual([10], report["direct_hidden_columns"]["visible_difference_indices"])
        self.assertTrue(report["direct_hidden_columns"]["change_count_matches"])
        self.assertEqual([0], report["increment_from_column_14"]["visible_difference_indices"])
        self.assertTrue(report["increment_from_column_14"]["change_count_matches"])
        self.assertTrue(report["restoration"]["matches"])

    def test_decoder_rejects_wrong_payload_size(self):
        frame = ProbeFrame(probe_id=17, asic_id=0x45, status=0xE1, payload=b"x")

        with self.assertRaisesRegex(ProbeFormatError, "2335 bytes"):
            decode_probe_measurements(frame)

    def test_exact_capture_requires_matching_appvar_and_decimal_code(self):
        payload = bytearray(PAYLOAD_SIZE)
        payload[0] = 1
        frame = ProbeFrame(
            probe_id=17, asic_id=0x45, status=0xE1, payload=bytes(payload)
        )
        encoded = frame.encode()
        from hardware_probe import probe_verification_code

        fields = {
            "mode": "tilem-exact-probe",
            "completed": "1",
            "probe_id": "17",
            "payload_size": str(PAYLOAD_SIZE),
            "probe_size": "3450",
            "appvar_matches": "1",
            "display_code": str(probe_verification_code(frame)),
            "frame_hex": encoded.hex(),
            "appvar_frame_hex": encoded.hex(),
        }

        decoded, measurements, code = validate_capture(
            fields, backend="tilem", image_size=3450
        )

        self.assertEqual(frame, decoded)
        self.assertEqual("completed", measurements["outcome"])
        self.assertGreaterEqual(code, 0)

        fields["appvar_matches"] = "0"
        with self.assertRaisesRegex(ValueError, "resident AppVar"):
            validate_capture(fields, backend="tilem", image_size=3450)


if __name__ == "__main__":
    unittest.main()
