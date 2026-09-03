#!/usr/bin/env python3
"""Package the link-wait witness and its TI-BASIC Asm wrapper."""

from __future__ import annotations

import argparse
from pathlib import Path

from ti84re.tifiles.program import asm_call_body, encode_program_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    payload = args.payload.read_bytes()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "AALINK.8xp").write_bytes(
        encode_program_file("AALINK", asm_call_body("LINKWAIT"))
    )
    (args.output / "LINKWAIT.8xp").write_bytes(
        encode_program_file("LINKWAIT", bytes((0xBB, 0x6D)) + payload)
    )
    print(f"payload={len(payload)} internal_size={len(payload) + 2}")


if __name__ == "__main__":
    main()
