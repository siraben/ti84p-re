"""Reusable identity, command, environment, and process helpers for MAME."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

MAME_VERSION = "0.287"
MAME_TI84PV3_ROM_WARNING = (
    "EXPECTED: CRC(a9b5d5a6) SHA1(d500540feca974f6e8fa269981cfb25dc951c338)"
)
LOCAL_TI84_ROM_WARNING = (
    "FOUND: CRC(c326162a) SHA1(ffddb460d7d4e79cc8fbd288d6895fd113d7f3bf)"
)


class MameRuntimeError(ValueError):
    """A MAME executable, configuration, or process invariant failed."""


@dataclass(frozen=True)
class MameRunConfiguration:
    """One bounded noninteractive MAME invocation."""

    executable: str
    machine: str
    rom_root: Path
    seconds: int
    lua_script: Path


@dataclass(frozen=True)
class MameProcessOutput:
    """Captured output from one successful MAME invocation."""

    command: tuple[str, ...]
    stdout: str
    stderr: str


@dataclass(frozen=True)
class MameExecutableIdentity:
    """Resolved identity of one guarded MAME executable."""

    path: Path
    version: str
    sha256: str


@dataclass(frozen=True)
class MameRuntimeLayout:
    """Isolated filesystem layout for one MAME invocation."""

    root: Path
    rom_root: Path
    runtime_rom: Path
    stdout: Path
    stderr: Path


@dataclass(frozen=True)
class GuardedMameProbeRun:
    """Inputs, identities, filesystem layout, and output for one guarded probe."""

    machine: str
    source_rom: Path
    lua_script: Path
    identity: MameExecutableIdentity
    layout: MameRuntimeLayout
    process: MameProcessOutput
    source_rom_sha256: str
    lua_script_sha256: str

    @property
    def combined_output(self) -> str:
        """Return standard output and standard error for report parsing."""

        return self.process.stdout + "\n" + self.process.stderr

    def manifest_fields(self) -> dict[str, object]:
        """Return the common identity and retained-artifact manifest fields."""

        return {
            "emulator": "MAME",
            "version": self.identity.version,
            "binary": str(self.identity.path),
            "binary_sha256": self.identity.sha256,
            "machine": self.machine,
            "source_rom": str(self.source_rom),
            "source_rom_sha256": self.source_rom_sha256,
            "runtime_rom": str(self.layout.runtime_rom),
            "lua_script": str(self.lua_script),
            "lua_script_sha256": self.lua_script_sha256,
            "command": self.process.command,
            "stdout": str(self.layout.stdout),
            "stderr": str(self.layout.stderr),
        }


def file_sha256(path: Path) -> str:
    """Hash one file without loading it all into memory."""

    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def machine_rom_name(machine: str) -> str:
    """Return the known MAME ROM filename for supported TI-84 Plus drivers."""

    names = {
        "ti84pv3": "ti84pv3v255mp.bin",
    }
    try:
        return names[machine]
    except KeyError as error:
        raise MameRuntimeError(
            f"unknown ROM filename for MAME machine {machine!r}"
        ) from error


def build_command(config: MameRunConfiguration) -> list[str]:
    """Build a bounded, noninteractive MAME invocation."""

    if config.seconds <= 0:
        raise MameRuntimeError("run duration must be positive")
    return [
        config.executable,
        config.machine,
        "-rompath",
        str(config.rom_root),
        "-cfg_directory",
        str(config.rom_root / "cfg"),
        "-nvram_directory",
        str(config.rom_root / "nvram"),
        "-snapshot_directory",
        str(config.rom_root / "snap"),
        "-video",
        "soft",
        "-sound",
        "none",
        "-seconds_to_run",
        str(config.seconds),
        "-nothrottle",
        "-skip_gameinfo",
        "-autoboot_script",
        str(config.lua_script),
    ]


def headless_environment(base: Mapping[str, str]) -> dict[str, str]:
    """Return an isolated SDL environment for a headless MAME run."""

    result = dict(base)
    result["SDL_VIDEODRIVER"] = "dummy"
    result["SDL_AUDIODRIVER"] = "dummy"
    return result


def resolve_executable(executable: str) -> Path:
    """Resolve one MAME command name or explicit path."""

    if os.sep in executable:
        path = Path(executable).expanduser().resolve()
        if not path.is_file():
            raise MameRuntimeError(f"MAME executable does not exist: {path}")
        return path
    resolved = shutil.which(executable)
    if resolved is None:
        raise MameRuntimeError(f"cannot find MAME executable {executable!r}")
    return Path(resolved).resolve()


def executable_version(executable: Path) -> str:
    """Read the leading semantic version from `mame -version`."""

    try:
        completed = subprocess.run(
            [str(executable), "-version"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise MameRuntimeError(f"cannot execute MAME: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise MameRuntimeError(f"MAME version query failed: {detail}")
    first_line = completed.stdout.splitlines()[0] if completed.stdout else ""
    version = first_line.split(maxsplit=1)[0]
    if not version:
        raise MameRuntimeError("MAME version query returned no version")
    return version


def guarded_executable(
    executable: str,
    *,
    expected_sha256: str,
    expected_version: str,
) -> MameExecutableIdentity:
    """Resolve MAME and require its caller-supplied hash and version."""

    path = resolve_executable(executable)
    actual_sha256 = file_sha256(path)
    if actual_sha256 != expected_sha256.lower():
        raise MameRuntimeError("MAME SHA-256 does not match expectation")
    version = executable_version(path)
    if version != expected_version:
        raise MameRuntimeError(
            f"MAME probe requires version {expected_version}, found {version}"
        )
    return MameExecutableIdentity(
        path=path,
        version=version,
        sha256=actual_sha256,
    )


def prepare_runtime(
    output_dir: Path,
    *,
    machine: str,
    source_rom: Path,
) -> MameRuntimeLayout:
    """Create one new isolated MAME ROM, configuration, and NVRAM tree."""

    if output_dir.exists():
        raise MameRuntimeError(
            f"refusing to reuse existing output directory {output_dir}"
        )
    rom_root = output_dir / "runtime"
    machine_dir = rom_root / machine
    machine_dir.mkdir(parents=True)
    for directory in ("cfg", "nvram", "snap"):
        (rom_root / directory).mkdir()
    runtime_rom = machine_dir / machine_rom_name(machine)
    shutil.copyfile(source_rom, runtime_rom)
    return MameRuntimeLayout(
        root=output_dir,
        rom_root=rom_root,
        runtime_rom=runtime_rom,
        stdout=output_dir / "stdout.log",
        stderr=output_dir / "stderr.log",
    )


def write_process_logs(
    layout: MameRuntimeLayout,
    process: MameProcessOutput,
) -> None:
    """Retain complete standard output and standard error for one run."""

    layout.stdout.write_text(process.stdout, encoding="utf-8")
    layout.stderr.write_text(process.stderr, encoding="utf-8")


REPORT_FIELD_PATTERN = re.compile(
    r"(?P<key>[a-z_][a-z0-9_]*)=(?P<value>\S+)"
)


def parse_report_fields(line: str) -> dict[str, str]:
    """Extract stable `name=value` fields from one native report line."""

    return {
        match["key"]: match["value"]
        for match in REPORT_FIELD_PATTERN.finditer(line)
    }


def validate_rom_warning(output: str) -> None:
    """Require MAME's expected and actual identities for the local TI-84 ROM."""

    for line in (MAME_TI84PV3_ROM_WARNING, LOCAL_TI84_ROM_WARNING):
        if line not in output:
            raise MameRuntimeError(f"MAME output omits checksum line: {line}")


def run_mame(
    config: MameRunConfiguration,
    environment: Mapping[str, str],
) -> MameProcessOutput:
    """Run MAME and capture complete output from a successful invocation."""

    command = build_command(config)
    try:
        completed = subprocess.run(
            command,
            env=dict(environment),
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise MameRuntimeError(f"cannot execute MAME: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise MameRuntimeError(f"MAME probe failed: {detail}")
    return MameProcessOutput(
        command=tuple(command),
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def run_guarded_probe(
    *,
    executable: str,
    expected_executable_sha256: str,
    expected_version: str,
    machine: str,
    source_rom: Path,
    expected_rom_sha256: str,
    rom_description: str,
    output_dir: Path,
    seconds: int,
    lua_script: Path,
    environment: Mapping[str, str],
) -> GuardedMameProbeRun:
    """Validate every executable input, run in isolation, and retain the logs."""

    identity = guarded_executable(
        executable,
        expected_sha256=expected_executable_sha256,
        expected_version=expected_version,
    )
    source_rom_sha256 = file_sha256(source_rom)
    if source_rom_sha256 != expected_rom_sha256.lower():
        raise MameRuntimeError(f"probe requires {rom_description}")
    lua_script_sha256 = file_sha256(lua_script)
    layout = prepare_runtime(
        output_dir,
        machine=machine,
        source_rom=source_rom,
    )
    config = MameRunConfiguration(
        executable=str(identity.path),
        machine=machine,
        rom_root=layout.rom_root,
        seconds=seconds,
        lua_script=lua_script,
    )
    process = run_mame(config, headless_environment(environment))
    write_process_logs(layout, process)
    return GuardedMameProbeRun(
        machine=machine,
        source_rom=source_rom,
        lua_script=lua_script,
        identity=identity,
        layout=layout,
        process=process,
        source_rom_sha256=source_rom_sha256,
        lua_script_sha256=lua_script_sha256,
    )
