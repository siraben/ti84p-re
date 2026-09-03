#!/usr/bin/env python3
"""Generate a headless TilEm macro that receives a .8xp fixture by link.

Usage: python3 -m ti84re.trace.make_load_macro FIXTURE.8xp OUT.macro [--run]
"""

import argparse
import sys
from pathlib import Path

def parse_8xp(raw):
    if len(raw) < 76 or raw[:11] != b"**TI83F*\x1a\x0a\x00":
        sys.exit(f"{raw[:8]!r}: not a TI-83/84 variable file")
    data_length = int.from_bytes(raw[53:55], "little")
    data_end = 55 + data_length
    if len(raw) != data_end + 2:
        sys.exit("variable-file data length does not match file size")
    if sum(raw[55:data_end]) & 0xFFFF != int.from_bytes(raw[data_end:], "little"):
        sys.exit("variable-file checksum mismatch")
    # var entry: [hdr 13][data len #1][type][name 8][ver][flag]
    #            [data len #2 == body bytes][body]
    header_length = int.from_bytes(raw[55:57], "little")
    entry_length = int.from_bytes(raw[57:59], "little")
    repeated_length = int.from_bytes(raw[70:72], "little")
    if header_length != 0x0D or entry_length != repeated_length:
        sys.exit("unsupported variable-entry header")
    body_len = int.from_bytes(raw[72:74], "little")
    if entry_length != body_len + 2 or data_length != 17 + entry_length:
        sys.exit("expected a single program entry with a size-prefixed body")
    var_type = raw[59]
    name = raw[60:68].rstrip(b"\0").decode("ascii")
    body = raw[74 : 74 + body_len]
    return var_type, name, body


def render_macro(fixture: Path, *, run_program: bool = False) -> str:
    """Return a reset-origin macro for the patched headless TilEm loader."""

    lines = [
        "set key_hold 0.18s",
        "set key_delay 0.3s",
        "wait 4s",
        "key ON",
        "wait 3s",
        "key ENTER",
        "wait 2s",
        "key CLEAR",
        "wait 0.6s",
        "key 2ND",
        "wait 0.6s",
        "key GRAPHVAR",
        "wait 2s",
        "key RIGHT",
        "wait 1.2s",
        "key ENTER",
        "wait 3s",
        f"loadvar {fixture.resolve()}",
        "wait 1s",
    ]
    if run_program:
        lines.extend([
            "key CLEAR",
            "wait 0.8s",
            "key PRGM",
            "wait 1s",
            "key ENTER",
            "wait 0.8s",
            "key ENTER",
            "wait 8s",
        ])
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture")
    ap.add_argument("out")
    ap.add_argument("--run", action="store_true", help="run the first EXEC-list program after loading")
    args = ap.parse_args()

    fixture = Path(args.fixture)
    raw = fixture.read_bytes()
    var_type, name, data = parse_8xp(raw)
    if var_type not in (0x05, 0x06):
        sys.exit(f"type {var_type:#04x} is not a program")

    Path(args.out).write_text(render_macro(fixture, run_program=args.run))
    action = "loads and runs" if args.run else "loads"
    print(f"{args.out}: {action} prgm{name} ({len(data)} token bytes)")


if __name__ == "__main__":
    main()
