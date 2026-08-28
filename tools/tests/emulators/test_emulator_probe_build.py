#!/usr/bin/env python3
"""Regression tests for the shared emulator-probe build CLI."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


from ti84re.emulators import probe_build


class EmulatorProbeBuildTests(unittest.TestCase):
    def run_cli(self, function, output: Path, **kwargs):
        argv = ["build", "--source", "/source", "--output", str(output), "--json"]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(probe_build, "file_sha256", return_value="a" * 64),
            mock.patch("builtins.print") as printed,
        ):
            function(**kwargs)
        return json.loads(printed.call_args.args[0])

    def test_tilem_list_adapter_build(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runner"
            build = mock.Mock(return_value=["cc", "-o", str(output)])
            report = self.run_cli(
                probe_build.tilem_main,
                output,
                description="test",
                plain_name="test",
                adapter_names=("tilem_probe_support.c", "tilem_exact_probe.c"),
                build=build,
                error_types=(),
                adapters_as_list=True,
            )

        adapters = build.call_args.args[1]
        self.assertEqual(2, len(adapters))
        self.assertEqual("debrouxl/tilem", report["repository"])
        self.assertEqual(
            [str(path) for path in adapters],
            [row["path"] for row in report["adapters"]],
        )

    def test_wabbitemu_build(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runner"
            with mock.patch.object(
                probe_build, "build_headless", return_value=["g++", "-o", str(output)]
            ) as build:
                report = self.run_cli(
                    probe_build.wabbitemu_main,
                    output,
                    description="test",
                    plain_name="test",
                    adapter_name="wabbitemu_exact_probe.cpp",
                )

        self.assertEqual("sputt/wabbitemu", report["repository"])
        self.assertEqual("wabbitemu_exact_probe.cpp", Path(report["adapter"]).name)
        self.assertEqual(Path("/source"), build.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
