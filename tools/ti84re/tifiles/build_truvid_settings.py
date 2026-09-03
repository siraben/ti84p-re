#!/usr/bin/env python3
"""Build the two-byte TruVid settings AppVar used by runtime traces."""

import argparse
from pathlib import Path

from ti84re.hardware.probe import encode_ti_variable_file


def build_settings(contrast: int, delay: int, *, archived: bool) -> bytes:
    """Return the two-byte settings payload in an AppVar link file."""

    if not 0 <= contrast <= 0xFF or not 0 <= delay <= 0xFF:
        raise ValueError("contrast and delay must fit in one byte")
    data = bytes((2, 0, contrast, delay))
    return encode_ti_variable_file(
        0x15,
        "TruVid",
        data,
        archived=archived,
        comment="TruVid runtime trace settings",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archived", action="store_true")
    parser.add_argument("--contrast", type=lambda value: int(value, 0), default=7)
    parser.add_argument("--delay", type=lambda value: int(value, 0), default=178)
    args = parser.parse_args()
    try:
        output = build_settings(args.contrast, args.delay, archived=args.archived)
    except ValueError as error:
        parser.error(str(error))
    args.output.write_bytes(output)


if __name__ == "__main__":
    main()
