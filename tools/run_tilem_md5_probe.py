#!/usr/bin/env python3
"""Run hash-guarded MD5-assist edge cases through pinned TilEm."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tilem_core import TILEM_COMMIT, TILEM_TREE, TilemCoreError, file_sha256
from tilem_md5 import run_md5_probe, validate_md5_report


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
                "MD5-probe SHA-256 does not match --expected-binary-sha256"
            )
        report = validate_md5_report(run_md5_probe(args.binary))
        result = {
            "emulator": "TilEm",
            "commit": TILEM_COMMIT,
            "git_tree": TILEM_TREE,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "report": report,
            "launch": "direct initialized-core MD5-assist port handlers",
            "evidence_scope": (
                "pinned TilEm MD5 edge behavior under the locked compiler; not "
                "TI-OS execution, a portable C result, or physical ASIC behavior"
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
        "operand shifts: "
        f"{native['one_write_result']:08X}, "
        f"{native['three_write_result']:08X}, "
        f"{native['four_write_result']:08X}, "
        f"{native['five_write_result']:08X}"
    )
    print(
        f"masked controls: {native['masked_control_result']:08X}; "
        f"mixed read: {native['mixed_result']:08X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
