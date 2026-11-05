#!/usr/bin/env python3
"""Require the physical-measurement index to name every built probe artifact."""

import unittest

from ti84re.hardware.build_probes import PROBES
from ti84re.paths import ROOT


INDEX = ROOT / "docs" / "needed-probes" / "calculator-readable.md"


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


if __name__ == "__main__":
    unittest.main()
