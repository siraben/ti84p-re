#!/usr/bin/env python3
"""Package the resident allocation probe and its Asm wrapper."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tibasic_samples import T, letters, ti83p_program_file  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=Path)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()

    payload = args.payload.read_bytes()
    wrapper = [
        T["2byte"], T["asm"], T["prog"], *letters("ALPROBE"),
        T["rparen"], T["enter"],
    ]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "AACALL.8xp").write_bytes(
        ti83p_program_file("AACALL", wrapper)
    )
    (args.out_dir / "ALPROBE.8xp").write_bytes(
        ti83p_program_file("ALPROBE", [0xBB, 0x6D, *payload])
    )
    print(f"payload={len(payload)} internal_size={len(payload) + 2}")


if __name__ == "__main__":
    main()
