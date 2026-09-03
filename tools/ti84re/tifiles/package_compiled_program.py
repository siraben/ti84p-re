#!/usr/bin/env python3
"""Package a compiled-assembly program body as a TI link file."""

import argparse
from pathlib import Path

from ti84re.tifiles.program import encode_program_file


def package_program(program_name: str, body: bytes) -> bytes:
    """Return a link file for one body carrying the compiled marker."""

    if not body.startswith(bytes((0xBB, 0x6D))):
        raise ValueError("compiled body must begin with BB 6D")
    return encode_program_file(program_name, body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program_name")
    parser.add_argument("body", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    body = args.body.read_bytes()
    try:
        output = package_program(args.program_name, body)
    except ValueError as error:
        parser.error(str(error))
    args.output.write_bytes(output)


if __name__ == "__main__":
    main()
