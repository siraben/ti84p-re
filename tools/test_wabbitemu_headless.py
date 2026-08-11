#!/usr/bin/env python3
"""Regression tests for the pinned Wabbitemu headless adapter."""

from pathlib import Path
import unittest

from wabbitemu_headless import (
    COMPILE_SOURCES,
    WabbitemuHeadlessError,
    build_command,
    parse_run_report,
)


class WabbitemuHeadlessTests(unittest.TestCase):
    def test_build_command_keeps_portability_shims_and_pinned_units_explicit(self):
        source = Path("/source/wabbitemu")
        command = build_command(
            source,
            Path("tools/wabbitemu_headless.cpp"),
            Path("/tmp/wabbitemu-headless"),
            cxx="c++",
        )

        self.assertEqual("c++", command[0])
        self.assertIn("-D_LINUX", command)
        self.assertIn("-D__pragma(x)=", command)
        self.assertEqual(
            [str(source / relative) for relative in COMPILE_SOURCES],
            [item for item in command if item.startswith(str(source)) and item.endswith(".c")],
        )
        self.assertEqual(["-lm", "-o", "/tmp/wabbitemu-headless"], command[-3:])

    def test_parses_native_status_without_treating_pc_as_decimal(self):
        report = parse_run_report(
            "steps=20000000 tstates=239914310 pc=0x03A5 halted=1 "
            "changed_bytes=74 input_fnv1a64=be3f4298bf704659 "
            "output_fnv1a64=3a55a4a28ab5f67b wake=pressed-released "
            "settled=yes visits=3C:7BC7,3C:7C1F,3C:7C43,3C:7D30\n"
        )

        self.assertEqual(0x03A5, report.pc)
        self.assertEqual(74, report.changed_bytes)
        self.assertTrue(report.halted)
        self.assertTrue(report.settled)
        self.assertEqual(("3C:7BC7", "3C:7C1F", "3C:7C43", "3C:7D30"), report.visits)

    def test_rejects_incomplete_native_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_run_report("steps=1 settled=no")


if __name__ == "__main__":
    unittest.main()
