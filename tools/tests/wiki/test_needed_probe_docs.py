#!/usr/bin/env python3
"""Require the physical-measurement index to name every built probe artifact."""

import unittest

from ti84re.hardware.build_probes import PROBES
from ti84re.paths import ROOT


INDEX = ROOT / "docs" / "needed-probes" / "calculator-readable.md"
RECORDING = ROOT / "docs" / "needed-probes" / "recording-results.md"


class NeededProbeDocumentationTests(unittest.TestCase):
    def test_every_probe_definition_is_documented(self):
        text = INDEX.read_text()

        for name, probe in PROBES.items():
            with self.subTest(probe=name):
                self.assertIn(f"`{probe.source_name}`", text)
                self.assertIn(f"`{probe.program}`", text)
                self.assertIn(f"`{probe.appvar}`", text)

    def test_every_probe_source_has_one_index_row(self):
        text = INDEX.read_text()
        source_names = {probe.source_name for probe in PROBES.values()}

        for source_name in source_names:
            with self.subTest(source=source_name):
                self.assertEqual(1, text.count(f"`{source_name}`"))

    def test_recording_contract_preserves_raw_state_and_context(self):
        text = RECORDING.read_text()

        self.assertIn("ti84re.hardware.physical_probe_evidence", text)
        self.assertIn("frame_hex", text)
        self.assertIn("appvar_file_sha256", text)
        self.assertIn("ti84p-re.physical-probe-metadata.v1", text)
        self.assertIn("all calculator-observable state", text)
        self.assertIn("compact_state_code", text)
        self.assertIn("HWPZ1-", text)
        self.assertIn("ti84re.hardware.compact_probe_code", text)


if __name__ == "__main__":
    unittest.main()
