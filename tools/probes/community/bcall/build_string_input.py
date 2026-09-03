#!/usr/bin/env python3
"""Package the _GetStringInput2 fixture and TI-BASIC wrapper."""

from __future__ import annotations

import argparse
from pathlib import Path

from ti84re.tifiles.program import asm_call_body, encode_program_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    payload = args.payload.read_bytes()
    (args.output / "STRIN.8xp").write_bytes(
        encode_program_file(
            "STRIN", bytes((0xBB, 0x6D)) + payload,
            comment="GetStringInput2 interaction fixture",
        )
    )
    (args.output / "ASTRIN.8xp").write_bytes(
        encode_program_file(
            "ASTRIN", asm_call_body("STRIN"),
            comment="GetStringInput2 launcher",
        )
    )


if __name__ == "__main__":
    main()
