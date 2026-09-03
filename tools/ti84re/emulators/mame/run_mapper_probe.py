#!/usr/bin/env python3
"""Run guarded TI-84 Plus memory-mapper cases through MAME 0.287."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from ti84re.emulators.mame.mapper import (
    PROBE_CASES,
    parse_mame_mapper_report,
    validate_mame_mapper_report,
)
from ti84re.emulators.mame.runtime import (
    MAME_VERSION,
    GuardedMameProbeRun,
    run_guarded_probe,
    validate_rom_warning,
)
from ti84re.emulators.probe_cli import DEFAULT_ROM, emit_result, require_output_absent, write_json
from ti84re.rom.signatures import TI84_PLUS_OS_255MP_SHA256
from ti84re.paths import PROBES

MACHINE = "ti84pv3"


def _run_case(
    case: str,
    *,
    executable: str,
    expected_executable_sha256: str,
    source_rom: Path,
    output_dir: Path,
    script: Path,
) -> GuardedMameProbeRun:
    environment = dict(os.environ)
    environment["TI84_MAME_MAPPER_CASE"] = case
    return run_guarded_probe(
        executable=executable,
        expected_executable_sha256=expected_executable_sha256,
        expected_version=MAME_VERSION,
        machine=MACHINE,
        source_rom=source_rom,
        expected_rom_sha256=TI84_PLUS_OS_255MP_SHA256,
        rom_description="the exact local OS 2.55MP ROM",
        output_dir=output_dir / case,
        seconds=2,
        lua_script=script,
        environment=environment,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--mame", default="mame")
    parser.add_argument("--expected-mame-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    script = PROBES / "mame/mame_mapper_probe.lua"
    try:
        require_output_absent(args.output_dir)
        runs = {
            case: _run_case(
                case,
                executable=args.mame,
                expected_executable_sha256=args.expected_mame_sha256,
                source_rom=args.rom,
                output_dir=args.output_dir,
                script=script,
            )
            for case in PROBE_CASES
        }
        for run in runs.values():
            validate_rom_warning(run.combined_output)
        combined_output = "\n".join(runs[case].combined_output for case in PROBE_CASES)
        report = validate_mame_mapper_report(parse_mame_mapper_report(combined_output))
        first = runs[PROBE_CASES[0]]
        result = {
            "emulator": "MAME",
            "version": first.identity.version,
            "binary": str(first.identity.path),
            "binary_sha256": first.identity.sha256,
            "machine": MACHINE,
            "source_rom": str(args.rom),
            "source_rom_sha256": first.source_rom_sha256,
            "lua_script": str(script),
            "lua_script_sha256": first.lua_script_sha256,
            "runs": {
                case: {
                    "runtime_rom": str(run.layout.runtime_rom),
                    "command": run.process.command,
                    "stdout": str(run.layout.stdout),
                    "stderr": str(run.layout.stderr),
                }
                for case, run in runs.items()
            },
            "report": report,
            "launch": (
                "five fresh MAME processes separate reset observation, actual-Z80 "
                "A/independent-B/paired-B reads, and direct mapper edge cases"
            ),
            "evidence_scope": (
                "MAME 0.287 TI-84 Plus reset latch, bank arithmetic, mapped ports, "
                "safe RAM backing, and absent forced overlays; not TI-OS behavior, "
                "physical mapper behavior, or RAM-page-87 execution"
            ),
        }
        manifest = args.output_dir / "manifest.json"
        write_json(manifest, result)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    native = report["native"]
    emit_result(
        result,
        manifest,
        as_json=args.json,
        summary=[
            "handoff: "
            f"independent B={''.join(f'{value:02X}' for value in native['independent_b']['fixed_after'])}, "
            f"A={''.join(f'{value:02X}' for value in native['window_a']['fixed_after'])}, "
            f"paired B={''.join(f'{value:02X}' for value in native['paired_b']['fixed_after'])}",
            "paired A/B/C: "
            f"{''.join(f'{value:02X}' for value in native['paired_a'])}/"
            f"{''.join(f'{value:02X}' for value in native['paired_b_bytes'])}/"
            f"{native['paired_c']:02X}; fetch marker={native['fetch_marker']:02X}",
        ],
    )


if __name__ == "__main__":
    main()
