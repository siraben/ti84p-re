#!/usr/bin/env python3
"""Regression tests for reusable MAME trace orchestration."""

from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mame_trace import (
    MameTraceConfiguration,
    build_command,
    machine_rom_name,
    trace_environment,
)


class MameTraceTests(unittest.TestCase):
    def configuration(self) -> MameTraceConfiguration:
        return MameTraceConfiguration(
            executable="mame",
            machine="ti84pv3",
            rom_root=Path("/tmp/roms"),
            seconds=2,
            lua_script=Path("/repo/tools/mame_io_trace.lua"),
            ports="03-04,55-56",
            on_press_frame=30,
            on_release_frame=34,
        )

    def test_known_rom_names(self):
        self.assertEqual("ti84pv3v255mp.bin", machine_rom_name("ti84pv3"))
        with self.assertRaises(ValueError):
            machine_rom_name("unknown")

    def test_command_is_headless_and_bounded(self):
        command = build_command(self.configuration())
        self.assertEqual("mame", command[0])
        self.assertIn("-seconds_to_run", command)
        self.assertIn("-autoboot_script", command)
        self.assertIn("-nothrottle", command)
        self.assertIn("-cfg_directory", command)
        self.assertIn("-nvram_directory", command)
        self.assertIn("-snapshot_directory", command)

    def test_trace_environment(self):
        environment = trace_environment(self.configuration(), {"KEEP": "yes"})
        self.assertEqual("yes", environment["KEEP"])
        self.assertEqual("dummy", environment["SDL_VIDEODRIVER"])
        self.assertEqual("03-04,55-56", environment["MAME_TRACE_PORTS"])
        self.assertEqual("30", environment["MAME_ON_PRESS_FRAME"])
        self.assertEqual("34", environment["MAME_ON_RELEASE_FRAME"])

    def test_trace_environment_removes_stale_key_events(self):
        config = replace(
            self.configuration(), on_press_frame=None, on_release_frame=None
        )
        environment = trace_environment(
            config,
            {"MAME_ON_PRESS_FRAME": "1", "MAME_ON_RELEASE_FRAME": "2"},
        )
        self.assertNotIn("MAME_ON_PRESS_FRAME", environment)
        self.assertNotIn("MAME_ON_RELEASE_FRAME", environment)

    def test_release_must_follow_press(self):
        config = replace(self.configuration(), on_release_frame=30)
        with self.assertRaises(ValueError):
            trace_environment(config, {})

    def test_nonpositive_duration_is_rejected(self):
        config = self.configuration()
        invalid = replace(config, seconds=0)
        with self.assertRaises(ValueError):
            build_command(invalid)


if __name__ == "__main__":
    unittest.main()
