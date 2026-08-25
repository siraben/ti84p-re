#!/usr/bin/env python3
"""Run every non-interactive physical-probe image in one exact backend."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from ti84re.hardware.build_probes import PROBES
from ti84re.emulators.probe_cli import (
    DEFAULT_ROM,
    require_exact_hash,
    require_output_absent,
    write_json,
)
from ti84re.rom.signatures import TI84_PLUS_OS_255MP_SHA256
from ti84re.paths import TOOLS


SINGLE_RUNNER = TOOLS / "run_exact_hardware_probe.py"
INTERACTIVE_PROBES = {
    "keypad-settle": (
        "requires a launch-key release followed by an operator-held key or chord"
    ),
}
Run = Callable[..., subprocess.CompletedProcess[str]]


def short_failure(completed: subprocess.CompletedProcess[str]) -> str:
    """Return one bounded diagnostic from a failed child run."""

    text = completed.stderr.strip() or completed.stdout.strip()
    line = text.splitlines()[-1] if text else "child runner returned no diagnostic"
    return line[:500]


def run_probe_matrix(
    *,
    backend: str,
    rom: Path,
    binary: Path,
    expected_binary_sha256: str,
    output_dir: Path,
    probes: list[str],
    spasm: str,
    include_interactive: bool,
    run: Run = subprocess.run,
) -> dict[str, object]:
    """Run selected probes and retain success, failure, and skip outcomes."""

    require_output_absent(output_dir)
    rom_sha256 = require_exact_hash(
        rom, TI84_PLUS_OS_255MP_SHA256, "OS 2.55MP ROM"
    )
    binary_sha256 = require_exact_hash(
        binary, expected_binary_sha256, "exact runner"
    )
    output_dir.mkdir(parents=True)
    results: list[dict[str, object]] = []

    for probe in probes:
        if probe in INTERACTIVE_PROBES and not include_interactive:
            results.append({
                "probe": probe,
                "status": "interactive-input-required",
                "detail": INTERACTIVE_PROBES[probe],
            })
            continue

        probe_dir = output_dir / probe
        completed = run(
            [
                sys.executable,
                str(SINGLE_RUNNER),
                "--backend",
                backend,
                "--rom",
                str(rom),
                "--binary",
                str(binary),
                "--expected-binary-sha256",
                expected_binary_sha256,
                "--probe",
                probe,
                "--output-dir",
                str(probe_dir),
                "--spasm",
                spasm,
                "--json",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        (output_dir / f"{probe}.stdout").write_text(
            completed.stdout, encoding="utf-8"
        )
        (output_dir / f"{probe}.stderr").write_text(
            completed.stderr, encoding="utf-8"
        )
        if completed.returncode:
            results.append({
                "probe": probe,
                "status": "failed",
                "returncode": completed.returncode,
                "detail": short_failure(completed),
            })
            continue

        try:
            child = json.loads(
                (probe_dir / "manifest.json").read_text(encoding="utf-8")
            )
            decoded = child["decoded_frame"]
            code = decoded["verification_code_decimal"]
            measurements = decoded["measurements"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            results.append({
                "probe": probe,
                "status": "failed",
                "returncode": completed.returncode,
                "detail": f"invalid child manifest: {error}"[:500],
            })
            continue
        results.append({
            "probe": probe,
            "status": "completed",
            "verification_code_decimal": code,
            "measurements": measurements,
            "manifest": f"{probe}/manifest.json",
        })

    counts = {
        status: sum(row["status"] == status for row in results)
        for status in ("completed", "failed", "interactive-input-required")
    }
    report: dict[str, object] = {
        "schema": "ti84p-re.exact-hardware-probe-matrix.v1",
        "backend": backend,
        "binary": str(binary),
        "binary_sha256": binary_sha256,
        "source_rom": str(rom),
        "source_rom_sha256": rom_sha256,
        "counts": counts,
        "results": results,
        "evidence_scope": (
            "exact assembled measurement, cleanup, frame update, and CRC; "
            "not rendered screen pixels or physical calculator behavior"
        ),
    }
    write_json(output_dir / "manifest.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend", choices=("tilem", "wabbitemu"), required=True
    )
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-binary-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--spasm", default="spasm")
    parser.add_argument("--probe", action="append", choices=tuple(PROBES))
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--include-interactive",
        action="store_true",
        help="attempt operator-driven probes even though current adapters inject no keys",
    )
    args = parser.parse_args()
    try:
        report = run_probe_matrix(
            backend=args.backend,
            rom=args.rom,
            binary=args.binary,
            expected_binary_sha256=args.expected_binary_sha256,
            output_dir=args.output_dir,
            probes=args.probe or list(PROBES),
            spasm=args.spasm,
            include_interactive=args.include_interactive,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        counts = report["counts"]
        print(
            f"completed={counts['completed']} failed={counts['failed']} "
            "interactive_input_required="
            f"{counts['interactive-input-required']}"
        )
        print(f"manifest: {args.output_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
