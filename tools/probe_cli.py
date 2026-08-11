"""Composable manifest and CLI plumbing for emulator probes."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from file_hashes import file_sha256
from mame_runtime import (
    MAME_VERSION,
    GuardedMameProbeRun,
    MameRuntimeError,
    run_guarded_probe,
    validate_rom_warning,
)
from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from tilem_core import TILEM_COMMIT, TILEM_TREE
from wabbitemu_headless import WABBITEMU_COMMIT

JsonObject = dict[str, object]
Report = Mapping[str, Any]
Summary = Callable[[Report], Iterable[str]]
WabbitemuRunner = Callable[[Path, Path], object]
TilemRunner = Callable[[Path], object]
ReportValidator = Callable[[object], Report]
MameReportLoader = Callable[[str], Report]
MameAugment = Callable[
    [GuardedMameProbeRun, Path, Report], Mapping[str, object]
]
ResultSummary = Callable[[Mapping[str, Any]], Iterable[str]]

TOOLS = Path(__file__).resolve().parent
DEFAULT_ROM = TOOLS / "rom.bin"


def positive_int(value: str) -> int:
    """Parse one positive prefixed integer for argparse."""

    try:
        parsed = int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def require_exact_hash(path: Path, expected_sha256: str, description: str) -> str:
    """Return a file hash after checking it against a pinned identity."""

    observed = file_sha256(path)
    expected = expected_sha256.lower()
    if observed != expected:
        raise ValueError(
            f"{description} SHA-256 is {observed}; expected {expected}"
        )
    return observed


def require_output_absent(path: Path) -> None:
    """Reject an output path that already exists."""

    if path.exists():
        raise ValueError(f"refusing to reuse existing output directory {path}")


def require_fresh_output_dir(path: Path) -> None:
    """Reject reused result directories and create a fresh one."""

    require_output_absent(path)
    path.mkdir(parents=True)


def write_json(path: Path, result: Mapping[str, object]) -> Path:
    """Write one canonical indented JSON object."""

    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return path


def write_manifest(output_dir: Path, result: Mapping[str, object]) -> Path:
    """Create an output directory and write its canonical JSON manifest."""

    require_fresh_output_dir(output_dir)
    return write_json(output_dir / "manifest.json", result)


def emit_result(
    result: Mapping[str, object],
    manifest: Path,
    *,
    as_json: bool,
    summary: Iterable[str],
) -> None:
    """Print either canonical JSON or human summary lines plus the manifest."""

    if as_json:
        print(json.dumps(result, indent=2))
        return
    for line in summary:
        print(line)
    print(f"manifest: {manifest}")


def build_wabbitemu_result(
    *,
    binary: Path,
    source_rom: Path,
    runner: WabbitemuRunner,
    validator: ReportValidator,
    launch: str,
    evidence_scope: str,
    expected_binary_sha256: str | None = None,
) -> JsonObject:
    """Run and identify one Wabbitemu probe without CLI side effects."""

    identity = wabbitemu_identity(
        binary,
        source_rom,
        expected_binary_sha256=expected_binary_sha256,
    )
    report = validator(runner(binary, source_rom))
    return {
        **identity,
        "report": report,
        "launch": launch,
        "evidence_scope": evidence_scope,
    }


def wabbitemu_identity(
    binary: Path,
    source_rom: Path,
    *,
    expected_binary_sha256: str | None = None,
) -> JsonObject:
    """Return the common pinned Wabbitemu and retail-ROM identity fields."""

    source_rom_sha256 = require_exact_hash(
        source_rom,
        TI84_PLUS_OS_255MP_SHA256,
        "source ROM",
    )
    binary_sha256 = file_sha256(binary)
    if (
        expected_binary_sha256 is not None
        and binary_sha256 != expected_binary_sha256.lower()
    ):
        raise ValueError(
            f"native runner SHA-256 is {binary_sha256}; "
            f"expected {expected_binary_sha256.lower()}"
        )
    return {
        "emulator": "Wabbitemu",
        "commit": WABBITEMU_COMMIT,
        "binary": str(binary),
        "binary_sha256": binary_sha256,
        "source_rom": str(source_rom),
        "source_rom_sha256": source_rom_sha256,
    }


def validate_wabbitemu_probe_inputs(
    source_rom: Path,
    binary: Path,
    expected_binary_sha256: str,
) -> tuple[str, str]:
    """Require the pinned retail ROM and explicitly selected adapter."""

    source_rom_sha256 = file_sha256(source_rom)
    if source_rom_sha256 != TI84_PLUS_OS_255MP_SHA256:
        raise ValueError("probe requires the exact local OS 2.55MP ROM")
    binary_sha256 = require_exact_hash(
        binary,
        expected_binary_sha256,
        "binary",
    )
    return source_rom_sha256, binary_sha256


def build_tilem_result(
    *,
    binary: Path,
    expected_binary_sha256: str,
    runner: TilemRunner,
    validator: ReportValidator,
    launch: str,
    evidence_scope: str,
) -> JsonObject:
    """Run and identify one TilEm probe without CLI side effects."""

    binary_sha256 = require_exact_hash(
        binary,
        expected_binary_sha256,
        "native probe",
    )
    report = validator(runner(binary))
    return {
        "emulator": "TilEm",
        "commit": TILEM_COMMIT,
        "git_tree": TILEM_TREE,
        "binary": str(binary),
        "binary_sha256": binary_sha256,
        "report": report,
        "launch": launch,
        "evidence_scope": evidence_scope,
    }


def _no_mame_augment(
    _run: GuardedMameProbeRun,
    _source_rom: Path,
    _report: Report,
) -> Mapping[str, object]:
    return {}


def build_mame_result(
    *,
    executable: str,
    expected_executable_sha256: str,
    source_rom: Path,
    output_dir: Path,
    lua_script: Path,
    seconds: int,
    load_report: MameReportLoader,
    launch: str,
    evidence_scope: str,
    augment: MameAugment = _no_mame_augment,
    machine: str = "ti84pv3",
) -> JsonObject:
    """Run one guarded MAME probe and compose its canonical result."""

    run = run_guarded_probe(
        executable=executable,
        expected_executable_sha256=expected_executable_sha256,
        expected_version=MAME_VERSION,
        machine=machine,
        source_rom=source_rom,
        expected_rom_sha256=TI84_PLUS_OS_255MP_SHA256,
        rom_description="the exact local OS 2.55MP ROM",
        output_dir=output_dir,
        seconds=seconds,
        lua_script=lua_script,
        environment=os.environ,
    )
    validate_rom_warning(run.combined_output)
    report = load_report(run.combined_output)
    return {
        **run.manifest_fields(),
        "report": report,
        **augment(run, source_rom, report),
        "launch": launch,
        "evidence_scope": evidence_scope,
    }


@dataclass(frozen=True)
class WabbitemuProbeCli:
    """Declarative CLI wrapper for one ROM-backed Wabbitemu probe."""

    runner: WabbitemuRunner
    validator: ReportValidator
    launch: str
    evidence_scope: str
    summarize: Summary
    exact_binary: bool = False

    def run(self, description: str | None) -> None:
        """Parse common arguments, execute the probe, and retain its manifest."""

        parser = argparse.ArgumentParser(description=description)
        parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
        parser.add_argument("--binary", type=Path, required=True)
        if self.exact_binary:
            parser.add_argument("--expected-binary-sha256", required=True)
        parser.add_argument("--output-dir", type=Path, required=True)
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args()

        try:
            require_output_absent(args.output_dir)
            result = build_wabbitemu_result(
                binary=args.binary,
                source_rom=args.rom,
                runner=self.runner,
                validator=self.validator,
                launch=self.launch,
                evidence_scope=self.evidence_scope,
                expected_binary_sha256=(
                    args.expected_binary_sha256 if self.exact_binary else None
                ),
            )
            manifest = write_manifest(args.output_dir, result)
        except (OSError, RuntimeError, ValueError) as error:
            parser.error(str(error))

        emit_result(
            result,
            manifest,
            as_json=args.json,
            summary=self.summarize(result["report"]),
        )


@dataclass(frozen=True)
class TilemProbeCli:
    """Declarative CLI wrapper for one direct-core TilEm probe."""

    runner: TilemRunner
    validator: ReportValidator
    launch: str
    evidence_scope: str
    summarize: Summary

    def run(self, description: str | None) -> None:
        """Parse common arguments, execute the probe, and retain its manifest."""

        parser = argparse.ArgumentParser(description=description)
        parser.add_argument("--binary", type=Path, required=True)
        parser.add_argument("--expected-binary-sha256", required=True)
        parser.add_argument("--output-dir", type=Path, required=True)
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args()

        try:
            require_output_absent(args.output_dir)
            result = build_tilem_result(
                binary=args.binary,
                expected_binary_sha256=args.expected_binary_sha256,
                runner=self.runner,
                validator=self.validator,
                launch=self.launch,
                evidence_scope=self.evidence_scope,
            )
            manifest = write_manifest(args.output_dir, result)
        except (OSError, RuntimeError, ValueError) as error:
            parser.error(str(error))

        emit_result(
            result,
            manifest,
            as_json=args.json,
            summary=self.summarize(result["report"]),
        )


@dataclass(frozen=True)
class MameProbeCli:
    """Declarative CLI wrapper for one guarded single-process MAME probe."""

    lua_script: Path
    seconds: int
    load_report: MameReportLoader
    launch: str
    evidence_scope: str
    summarize: ResultSummary
    augment: MameAugment = _no_mame_augment
    machine: str = "ti84pv3"

    def run(self, description: str | None) -> None:
        """Parse common arguments, execute the probe, and retain its manifest."""

        parser = argparse.ArgumentParser(description=description)
        parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
        parser.add_argument("--mame", default="mame")
        parser.add_argument("--expected-mame-sha256", required=True)
        parser.add_argument("--output-dir", type=Path, required=True)
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args()

        try:
            result = build_mame_result(
                executable=args.mame,
                expected_executable_sha256=args.expected_mame_sha256,
                source_rom=args.rom,
                output_dir=args.output_dir,
                lua_script=self.lua_script,
                seconds=self.seconds,
                load_report=self.load_report,
                launch=self.launch,
                evidence_scope=self.evidence_scope,
                augment=self.augment,
                machine=self.machine,
            )
            manifest = write_json(args.output_dir / "manifest.json", result)
        except (OSError, MameRuntimeError) as error:
            parser.error(str(error))

        emit_result(
            result,
            manifest,
            as_json=args.json,
            summary=self.summarize(result),
        )
