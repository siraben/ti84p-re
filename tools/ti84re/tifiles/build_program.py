#!/usr/bin/env python3
"""Build a deterministic TI-83+/84+ program link file."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ti84re.tifiles.program import encode_program_file, filled_program_body


def byte_value(value: str) -> int:
    parsed = int(value, 0)
    if not 0 <= parsed <= 0xFF:
        raise argparse.ArgumentTypeError("byte must be between 0 and 255")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--name",
        required=True,
        help="one- through eight-character calculator name",
    )
    parser.add_argument("--body-size", required=True, type=int, metavar="BYTES")
    parser.add_argument(
        "--fill-byte",
        type=byte_value,
        default=0x31,
        help="body fill byte (default: 0x31, the token 1)",
    )
    parser.add_argument(
        "--last-byte",
        type=byte_value,
        default=0x3F,
        help="replace the final body byte (default: 0x3F, newline)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        body = filled_program_body(
            args.body_size,
            fill_byte=args.fill_byte,
            last_byte=args.last_byte,
        )
        blob = encode_program_file(
            args.name,
            body,
            comment="Archive boundary trace fixture",
        )
    except ValueError as error:
        parser.error(str(error))

    args.output.write_bytes(blob)
    report = {
        "output": str(args.output),
        "name": args.name.upper(),
        "body_size": len(body),
        "variable_data_size": len(body) + 2,
        "file_size": len(blob),
        "fill_byte": args.fill_byte,
        "last_byte": args.last_byte if body else None,
        "sha256": hashlib.sha256(blob).hexdigest(),
    }
    if args.json:
        print(json.dumps(report, indent=2))
        return
    print(
        f"wrote {args.output}: prgm{report['name']}, "
        f"body={report['body_size']} bytes, sha256={report['sha256']}"
    )


if __name__ == "__main__":
    main()
