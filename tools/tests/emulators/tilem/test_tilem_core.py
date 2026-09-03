#!/usr/bin/env python3
"""Regression tests for shared pinned-TilEm native-probe helpers."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ti84re.emulators.tilem.core import TilemCoreError, build_command


class TilemCoreTests(unittest.TestCase):
    @patch("ti84re.emulators.tilem.core.validate_tilem_source")
    def test_build_command_accepts_multiple_adapters(self, validate_source):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "emu" / "x4").mkdir(parents=True)
            (source / "emu" / "calcs.c").touch()
            (source / "emu" / "x4" / "x4_init.c").touch()
            command = build_command(
                source,
                [Path("tools/probes/tilem/tilem_probe_support.c"), Path("tools/probe.c")],
                Path("/tmp/tilem-probe"),
            )

        validate_source.assert_called_once_with(source)
        self.assertLess(
            command.index("tools/probes/tilem/tilem_probe_support.c"),
            command.index("tools/probe.c"),
        )
        self.assertIn("-Wl,--gc-sections", command)
        self.assertEqual(["-lm", "-o", "/tmp/tilem-probe"], command[-3:])

    @patch("ti84re.emulators.tilem.core.validate_tilem_source")
    def test_build_command_requires_an_adapter(self, _validate_source):
        with self.assertRaisesRegex(TilemCoreError, "at least one adapter"):
            build_command(Path("/tmp/tilem"), [], Path("/tmp/tilem-probe"))


if __name__ == "__main__":
    unittest.main()
