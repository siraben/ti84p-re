"""Regression tests for reusable MAME runtime orchestration."""

import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ti84re.emulators.mame.runtime import (
    MameExecutableIdentity,
    MameProcessOutput,
    MameRunConfiguration,
    MameRuntimeError,
    build_command,
    headless_environment,
    machine_rom_name,
    parse_report_fields,
    prepare_runtime,
    run_guarded_probe,
)


class MameRuntimeTests(unittest.TestCase):
    def configuration(self) -> MameRunConfiguration:
        return MameRunConfiguration(
            executable="/nix/store/example/bin/mame",
            machine="ti84pv3",
            rom_root=Path("/tmp/mame-runtime"),
            seconds=2,
            lua_script=Path("/repo/tools/probe.lua"),
        )

    def test_build_command_is_isolated_and_bounded(self):
        command = build_command(self.configuration())

        self.assertEqual("/nix/store/example/bin/mame", command[0])
        self.assertIn("-seconds_to_run", command)
        self.assertIn("-nvram_directory", command)
        self.assertIn("-autoboot_script", command)

    def test_headless_environment_preserves_unrelated_values(self):
        environment = headless_environment({"KEEP": "yes"})

        self.assertEqual("yes", environment["KEEP"])
        self.assertEqual("dummy", environment["SDL_VIDEODRIVER"])
        self.assertEqual("dummy", environment["SDL_AUDIODRIVER"])

    def test_machine_rom_name_is_explicit(self):
        self.assertEqual("ti84pv3v255mp.bin", machine_rom_name("ti84pv3"))
        with self.assertRaises(MameRuntimeError):
            machine_rom_name("unknown")

    def test_nonpositive_duration_is_rejected(self):
        config = self.configuration()
        invalid = MameRunConfiguration(**{**config.__dict__, "seconds": 0})
        with self.assertRaises(MameRuntimeError):
            build_command(invalid)

    def test_report_fields_parse_stable_pairs(self):
        self.assertEqual(
            {"case": "top8a", "selected": "4C,08"},
            parse_report_fields("PREFIX case=top8a selected=4C,08"),
        )

    def test_runtime_layout_is_new_and_isolated(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_rom = root / "source.bin"
            source_rom.write_bytes(b"fixture")
            output = root / "run"
            layout = prepare_runtime(
                output,
                machine="ti84pv3",
                source_rom=source_rom,
            )

            self.assertEqual(b"fixture", layout.runtime_rom.read_bytes())
            self.assertEqual(output / "runtime", layout.rom_root)
            for name in ("cfg", "nvram", "snap"):
                self.assertTrue((layout.rom_root / name).is_dir())
            with self.assertRaises(MameRuntimeError):
                prepare_runtime(
                    output,
                    machine="ti84pv3",
                    source_rom=source_rom,
                )

    def test_guarded_probe_reuses_identity_layout_logs_and_manifest(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_rom = root / "source.bin"
            source_rom.write_bytes(b"fixture ROM")
            script = root / "probe.lua"
            script.write_text("manager.machine:exit()\n", encoding="utf-8")
            executable = root / "mame"
            identity = MameExecutableIdentity(
                path=executable,
                version="0.287",
                sha256="a" * 64,
            )
            process = MameProcessOutput(
                command=(str(executable), "ti84pv3"),
                stdout="native report\n",
                stderr="warning\n",
            )
            with (
                patch("ti84re.emulators.mame.runtime.guarded_executable", return_value=identity),
                patch("ti84re.emulators.mame.runtime.run_mame", return_value=process) as runner,
            ):
                run = run_guarded_probe(
                    executable="mame",
                    expected_executable_sha256="a" * 64,
                    expected_version="0.287",
                    machine="ti84pv3",
                    source_rom=source_rom,
                    expected_rom_sha256=sha256(b"fixture ROM").hexdigest(),
                    rom_description="the fixture ROM",
                    output_dir=root / "run",
                    seconds=2,
                    lua_script=script,
                    environment={"KEEP": "yes"},
                )

            self.assertEqual("native report\n\nwarning\n", run.combined_output)
            self.assertEqual("native report\n", run.layout.stdout.read_text())
            self.assertEqual("warning\n", run.layout.stderr.read_text())
            self.assertEqual(
                sha256(script.read_bytes()).hexdigest(),
                run.manifest_fields()["lua_script_sha256"],
            )
            passed_environment = runner.call_args.args[1]
            self.assertEqual("yes", passed_environment["KEEP"])
            self.assertEqual("dummy", passed_environment["SDL_VIDEODRIVER"])

    def test_guarded_probe_rejects_wrong_rom_before_creating_runtime(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_rom = root / "source.bin"
            source_rom.write_bytes(b"wrong")
            script = root / "probe.lua"
            script.write_text("manager.machine:exit()\n", encoding="utf-8")
            identity = MameExecutableIdentity(
                path=root / "mame",
                version="0.287",
                sha256="a" * 64,
            )
            with (
                patch("ti84re.emulators.mame.runtime.guarded_executable", return_value=identity),
                self.assertRaisesRegex(MameRuntimeError, "fixture ROM"),
            ):
                run_guarded_probe(
                    executable="mame",
                    expected_executable_sha256="a" * 64,
                    expected_version="0.287",
                    machine="ti84pv3",
                    source_rom=source_rom,
                    expected_rom_sha256=sha256(b"expected").hexdigest(),
                    rom_description="the fixture ROM",
                    output_dir=root / "run",
                    seconds=2,
                    lua_script=script,
                    environment={},
                )

            self.assertFalse((root / "run").exists())


if __name__ == "__main__":
    unittest.main()
