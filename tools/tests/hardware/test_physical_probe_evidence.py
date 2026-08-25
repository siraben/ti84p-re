#!/usr/bin/env python3
"""Regression tests for self-contained physical-probe evidence bundles."""

from __future__ import annotations

import hashlib
import json
import unittest


from ti84re.hardware.probe import (
    ProbeFrame,
    encode_probe_appvar,
    encode_ti_variable_file,
    probe_verification_code,
)
from ti84re.hardware.physical_probe_evidence import (
    METADATA_SCHEMA,
    SCHEMA,
    build_evidence,
    validate_evidence,
)


def json_blob(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def program_file(name, body=b"program fixture"):
    return encode_ti_variable_file(0x05, name, body)


def artifact_row(
    *,
    probe="asic-snapshot",
    probe_id=3,
    appvar="HWPASIC1",
    payload=11,
    program_blob=b"program fixture",
):
    return {
        "probe": probe,
        "probe_id": probe_id,
        "source": f"tools/probes/hardware/{probe}.asm",
        "program": "HWASIC" if probe_id == 3 else "HWBATT",
        "result_appvar": appvar,
        "payload_size": payload,
        "defines": {},
        "machine_code_size": 123,
        "machine_code_sha256": "1" * 64,
        "program_file_size": len(program_blob),
        "program_file_sha256": hashlib.sha256(program_blob).hexdigest(),
        "output": "probe.8xp",
    }


def metadata(row, frame):
    return {
        "schema": METADATA_SCHEMA,
        "probe": row["probe"],
        "program": row["program"],
        "result_appvar": row["result_appvar"],
        "calculator": {
            "unit_id": "lab-ta3-01",
            "model": "TI-84 Plus",
            "pcb_revision": "TA3 rev A",
            "asic_marking": "TI-REF-84PL",
            "port_0x15": frame.asic_id,
            "boot_version": "1.03",
            "os_version": "2.55MP",
        },
        "run": {
            "utc_time": "2026-08-25T19:30:00-04:00",
            "power_source": "fresh AAA cells",
            "launch_context": "unmodified OS 2.55MP direct Asm(",
            "cpu_speed_setting": "OS default 15 MHz",
            "interrupts_enabled_on_entry": True,
            "preexisting_hooks_or_shells": [],
            "connected_equipment": [],
            "operator_actions": ["direct Asm(prgmHWASIC)"],
            "displayed_verification_code": probe_verification_code(frame),
            "visible_reset": False,
            "notes": "No visible anomaly.",
        },
    }


class PhysicalProbeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.frame = ProbeFrame(
            probe_id=3,
            asic_id=0x45,
            status=0xE3,
            payload=bytes.fromhex("06013317272F3B454BF0A5"),
        )
        self.appvar = encode_probe_appvar("HWPASIC1", self.frame)
        self.program = program_file("HWASIC")
        self.row = artifact_row(program_blob=self.program)
        self.manifest = {"format": 1, "probes": [self.row]}
        self.metadata = metadata(self.row, self.frame)

    def build(self, **kwargs):
        return build_evidence(
            self.appvar,
            self.program,
            json_blob(self.manifest),
            json_blob(self.metadata),
            appvar_name="HWPASIC1.8xv",
            program_name="HWASIC.8xp",
            manifest_name="manifest.json",
            metadata_name="metadata.json",
            **kwargs,
        )

    def test_bundle_retains_every_input_bit_and_decoded_state(self):
        evidence = self.build(
            attachments=(("unit_photo", "unit.png", b"\x89PNG fixture"),)
        )

        self.assertEqual(SCHEMA, evidence["schema"])
        self.assertTrue(evidence["state_coverage"]["complete"])
        self.assertEqual(self.frame.encode().hex().upper(), evidence["probe_report"]["frame_hex"])
        self.assertEqual(
            hashlib.sha256(self.appvar).hexdigest(),
            evidence["probe_report"]["appvar_file_sha256"],
        )
        self.assertEqual("0x06", evidence["probe_report"]["measurements"]["registers"]["0x04"])
        validate_evidence(evidence)

    def test_embedded_appvar_tamper_is_rejected(self):
        evidence = self.build()
        evidence["input_files"]["appvar"]["content"] = "AAAA"

        with self.assertRaisesRegex(ValueError, "size does not match"):
            validate_evidence(evidence)

    def test_report_tamper_is_rejected_even_when_input_is_intact(self):
        evidence = self.build()
        evidence["probe_report"]["payload_hex"] = "00"

        with self.assertRaisesRegex(ValueError, "does not match embedded inputs"):
            validate_evidence(evidence)

    def test_displayed_code_must_match_complete_frame(self):
        self.metadata["run"]["displayed_verification_code"] ^= 1

        with self.assertRaisesRegex(ValueError, "displayed verification code"):
            self.build()

    def test_asic_identity_must_match_physical_metadata(self):
        self.metadata["calculator"]["port_0x15"] = 0x55

        with self.assertRaisesRegex(ValueError, "port 0x15"):
            self.build()

    def test_unknown_identity_does_not_satisfy_complete_contract(self):
        self.metadata["calculator"]["pcb_revision"] = "unknown"

        with self.assertRaisesRegex(ValueError, "calculator.pcb_revision"):
            self.build()

    def test_manifest_payload_must_match_frame(self):
        self.row["payload_size"] = 12

        with self.assertRaisesRegex(ValueError, "payload size"):
            self.build()

    def test_exact_program_file_must_match_manifest(self):
        self.program = program_file("HWASIC", b"different program")

        with self.assertRaisesRegex(ValueError, "program file (size|SHA-256)"):
            self.build()

    def test_battery_probe_requires_physical_readings(self):
        frame = ProbeFrame(probe_id=6, asic_id=0x45, status=0xE3, payload=bytes(30))
        row = artifact_row(
            probe="battery-level",
            probe_id=6,
            appvar="HWBATT01",
            payload=30,
            program_blob=program_file("HWBATT", b"battery program"),
        )
        appvar = encode_probe_appvar("HWBATT01", frame)
        meta = metadata(row, frame)

        with self.assertRaisesRegex(ValueError, "run.load_amps"):
            build_evidence(
                appvar,
                program_file("HWBATT", b"battery program"),
                json_blob({"format": 1, "probes": [row]}),
                json_blob(meta),
                appvar_name="HWBATT01.8xv",
                program_name="HWBATT.8xp",
                manifest_name="manifest.json",
                metadata_name="metadata.json",
            )

    def test_reset_record_can_omit_display_code(self):
        self.metadata["run"]["visible_reset"] = True
        self.metadata["run"]["displayed_verification_code"] = None

        evidence = self.build()

        self.assertTrue(evidence["state_coverage"]["complete"])

    def test_recovery_gated_laboratory_manifest_is_preserved(self):
        frame = ProbeFrame(probe_id=17, asic_id=0x45, status=0xE3, payload=bytes(2335))
        appvar = encode_probe_appvar("HWPLAB01", frame)
        manifest = {
            "format": 1,
            "laboratory_only": True,
            "program": "HWPLAB",
            "result_appvar": "HWPLAB01",
            "probe_id": 17,
            "payload_size": 2335,
            "source": "tools/probes/hardware/lcd-hidden-lab.asm",
            "machine_code_size": 800,
            "machine_code_sha256": "3" * 64,
            "program_file_size": len(program_file("HWPLAB", b"hidden lab program")),
            "program_file_sha256": hashlib.sha256(
                program_file("HWPLAB", b"hidden lab program")
            ).hexdigest(),
            "recovery": {"backup": {"sha256": "5" * 64}},
        }
        meta = metadata(
            {
                "probe": "lcd-hidden-lab",
                "program": "HWPLAB",
                "result_appvar": "HWPLAB01",
            },
            frame,
        )
        meta["calculator"].update(
            {
                "backup_verified": True,
                "lcd_controller_or_revision": "identified test controller",
            }
        )
        meta["run"].update(
            {
                "visible_reset": True,
                "displayed_verification_code": None,
                "panel_observation": "No visible corruption after recovery.",
                "recovery_notes": "Backup restored and full screen checked.",
            }
        )

        evidence = build_evidence(
            appvar,
            program_file("HWPLAB", b"hidden lab program"),
            json_blob(manifest),
            json_blob(meta),
            appvar_name="HWPLAB01.8xv",
            program_name="HWPLAB.8xp",
            manifest_name="manifest.json",
            metadata_name="metadata.json",
        )

        self.assertTrue(evidence["artifact"]["laboratory_only"])
        self.assertEqual("5" * 64, evidence["artifact"]["recovery"]["backup"]["sha256"])
        validate_evidence(evidence)


if __name__ == "__main__":
    unittest.main()
