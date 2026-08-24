#!/usr/bin/env python3
"""Package the custom-error bcall probe and its TI-BASIC Asm wrapper."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tibasic_samples import T, letters, ti83p_program_file  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    payload = args.payload.read_bytes()
    wrapper = [
        T["2byte"], T["asm"], T["prog"], *letters("ERRPROBE"),
        T["rparen"], T["enter"],
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "AERR.8xp").write_bytes(ti83p_program_file("AERR", wrapper))
    (args.output / "ERRPROBE.8xp").write_bytes(
        ti83p_program_file("ERRPROBE", [0xBB, 0x6D, *payload])
    )
    print(f"payload={len(payload)} internal_size={len(payload) + 2}")


if __name__ == "__main__":
    main()
