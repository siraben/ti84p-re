#!/usr/bin/env python3
"""Decode RTSNAP records and the post-return heap fields from logical RAM."""

from __future__ import annotations

import argparse
from pathlib import Path


MAGIC = b"RTSNAP01"
FIELDS = (
    "fpBase", "FPS", "OPBase", "OPS", "pTemp", "progPtr", "symTable",
    "SP", "MemChk",
)


def word(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ram", type=Path, help="TilEm ram-logical dump")
    args = parser.parse_args()
    data = args.ram.read_bytes()

    candidates = []
    start = 0
    while True:
        offset = data.find(MAGIC, start)
        if offset < 0:
            break
        if data[offset + 8 : offset + 11] == bytes((19, 4, 1)):
            candidates.append(offset)
        start = offset + 1
    if not candidates:
        raise SystemExit("RTSNAP01 result header not found")
    offset = candidates[0]
    record_size = data[offset + 8]
    record_count = data[offset + 9]
    if record_size != 19:
        raise SystemExit(f"unexpected record size: {record_size}")

    print(f"result_logical=0x{offset + 0x8000:04X}")
    cursor = offset + 10
    for _ in range(record_count):
        stage = data[cursor]
        values = [word(data, cursor + 1 + i * 2) for i in range(len(FIELDS))]
        rendered = " ".join(
            f"{name}=0x{value:04X}" for name, value in zip(FIELDS, values)
        )
        print(f"stage={stage} {rendered}")
        cursor += record_size

    base = 0x9820 - 0x8000
    post = {
        "fpBase": word(data, base + 2),
        "FPS": word(data, base + 4),
        "OPBase": word(data, base + 6),
        "OPS": word(data, base + 8),
        "pTemp": word(data, base + 14),
        "progPtr": word(data, base + 16),
    }
    post["MemChk"] = max(0, post["OPS"] - post["FPS"] + 1)
    print("post_return " + " ".join(f"{k}=0x{v:04X}" for k, v in post.items()))


if __name__ == "__main__":
    main()
