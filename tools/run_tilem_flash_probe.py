#!/usr/bin/env python3
"""Run a hash-guarded Flash command/status matrix through pinned TilEm."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tilem_core import TILEM_COMMIT, TILEM_TREE, TilemCoreError, file_sha256
from tilem_flash import run_flash_probe, validate_flash_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-binary-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists():
        parser.error(f"refusing to reuse existing output directory {args.output_dir}")
    try:
        binary_sha256 = file_sha256(args.binary)
        if binary_sha256 != args.expected_binary_sha256.lower():
            raise TilemCoreError(
                "Flash-probe SHA-256 does not match --expected-binary-sha256"
            )
        report = validate_flash_report(run_flash_probe(args.binary))
        result = {
            "emulator": "TilEm",
            "commit": TILEM_COMMIT,
            "git_tree": TILEM_TREE,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "report": report,
            "launch": (
                "direct initialized-core Flash command writes and reads with "
                "synthetic in-memory contents"
            ),
            "evidence_scope": (
                "pinned TilEm command, status, protection-group, and timer model; "
                "not retail-ROM or physical Flash behavior"
            ),
        }
        args.output_dir.mkdir(parents=True)
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, TilemCoreError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    native = report["native"]
    print(
        "program deadlines/status: "
        f"{native['legal_timer']} clocks {native['legal_reads']}; "
        f"illegal {native['illegal_busy_reads']} -> {native['illegal_error_reads']}"
    )
    print(
        "sector erase: "
        f"{native['sector_erased']} bytes, deadlines "
        f"{native['sector_wait_timer']}/{native['sector_erase_timer']} clocks"
    )
    print(
        "chip erase non-FF bytes: "
        f"default {native['chip_default_non_ff']}, "
        f"override {native['chip_override_non_ff']}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
