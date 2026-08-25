#!/usr/bin/env python3
"""Package the safe bcall-semantics fixture and its TI-BASIC wrapper."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ti_program import asm_call_body, encode_program_file  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    payload = args.payload.read_bytes()
    (args.output / "SEMBCALL.8xp").write_bytes(
        encode_program_file(
            "SEMBCALL",
            bytes((0xBB, 0x6D)) + payload,
            comment="safe bcall semantics fixture",
        )
    )
    (args.output / "ASEM.8xp").write_bytes(
        encode_program_file(
            "ASEM", asm_call_body("SEMBCALL"), comment="bcall semantics launcher"
        )
    )


if __name__ == "__main__":
    main()
