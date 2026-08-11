#!/usr/bin/env python3
"""Run hash-guarded direct reset and violation cases through pinned TilEm."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tilem_core import (
    TILEM_COMMIT,
    TILEM_TREE,
    TilemCoreError,
    file_sha256,
)
from tilem_reset import (
    RESET_GROUPS,
    RETAINED_COMPONENTS,
    run_reset_probe,
    validate_reset_report,
)


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
                "reset-probe SHA-256 does not match --expected-binary-sha256"
            )
        report = validate_reset_report(run_reset_probe(args.binary))
        result = {
            "emulator": "TilEm",
            "commit": TILEM_COMMIT,
            "git_tree": TILEM_TREE,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "report": report,
            "launch": (
                "direct initialized-core tilem_calc_reset and synthetic forbidden "
                "Flash opcode execution"
            ),
            "evidence_scope": (
                "pinned TilEm reset functions and exception ordering; not TI-OS "
                "reset code, physical ASIC reset, or power-loss retention"
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
        f"reset groups {sum(native['reset_groups'])}/{len(RESET_GROUPS)}; "
        f"retained groups {sum(native['retained'])}/{len(RETAINED_COMPONENTS)}"
    )
    print(
        f"violation stop={native['violation_stop']:02X}, "
        f"RAM marker={native['violation_ram_marker']:02X}, "
        f"post-reset PC={native['violation_pc']:04X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
