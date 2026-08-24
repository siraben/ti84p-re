#!/usr/bin/env python3
"""Build a TI-BASIC ``Asm(prgmNAME)`` wrapper for trace fixtures."""

import argparse
from pathlib import Path

from ti_program import asm_call_body, encode_program_file


def build_wrapper(program_name: str, wrapper_name: str = "AARUN") -> bytes:
    """Return one link file containing the requested assembly call."""

    return encode_program_file(wrapper_name, asm_call_body(program_name))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program_name")
    parser.add_argument("output", type=Path)
    parser.add_argument("--wrapper-name", default="AARUN")
    args = parser.parse_args()
    args.output.write_bytes(build_wrapper(args.program_name, args.wrapper_name))


if __name__ == "__main__":
    main()
