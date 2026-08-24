#!/usr/bin/env python3
"""Package the resident-runtime snapshot payload as TI link files."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tibasic_samples import T, letters, ti83p_program_file  # noqa: E402


def build_wrapper() -> list[int]:
    return [
        T["2byte"], T["asm"], T["prog"], *letters("RTSNAP"),
        T["rparen"], T["enter"],
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=Path, help="assembled payload binary")
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()

    payload = args.payload.read_bytes()
    compiled_body = [0xBB, 0x6D, *payload]
    wrapper_body = build_wrapper()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "AACALL.8xp").write_bytes(
        ti83p_program_file("AACALL", wrapper_body)
    )
    (args.out_dir / "RTSNAP.8xp").write_bytes(
        ti83p_program_file("RTSNAP", compiled_body)
    )
    print(f"payload={len(payload)} internal_size={len(compiled_body)}")


if __name__ == "__main__":
    main()
