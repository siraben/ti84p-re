#!/usr/bin/env python3
"""Build a valid .8xg group fixture from two or more TI variable files."""

import struct
import sys


def entries(path):
    with open(path, "rb") as source:
        raw = source.read()
    if len(raw) < 57 or raw[:11] != b"**TI83F*\x1a\x0a\x00":
        raise ValueError(f"{path}: not a TI-83/84 variable file")
    data_length = raw[53] | (raw[54] << 8)
    out, off, end = [], 55, 55 + data_length
    if len(raw) != end + 2:
        raise ValueError(f"{path}: data length does not match file size")
    expected_checksum = raw[end] | (raw[end + 1] << 8)
    if sum(raw[55:end]) & 0xFFFF != expected_checksum:
        raise ValueError(f"{path}: checksum mismatch")
    while off < end:
        if off + 17 > end:
            raise ValueError(f"{path}: truncated entry header at {off:#x}")
        if raw[off] | (raw[off + 1] << 8) != 0x0D:
            raise ValueError(f"{path}: invalid entry header at {off:#x}")
        size = raw[off + 2] | (raw[off + 3] << 8)
        rec = raw[off : off + 17 + size]
        if len(rec) != 17 + size or off + len(rec) > end:
            raise ValueError(f"{path}: truncated entry at {off:#x}")
        out.append(rec)
        off += len(rec)
    return out


def build_group(paths):
    all_entries = []
    for path in paths:
        all_entries += entries(path)

    body = b"".join(all_entries)
    checksum = struct.pack("<H", sum(body) & 0xFFFF)

    out = bytearray(b"**TI83F*\x1a\x0a\x00")
    comment = b"group fixture A8"
    out += comment + b"\x00" * (42 - len(comment))
    out += struct.pack("<H", len(body))
    out += body + checksum
    return bytes(out), len(all_entries)


def main():
    if len(sys.argv) < 4:
        raise SystemExit(f"usage: {sys.argv[0]} INPUT INPUT [INPUT ...] OUTPUT.8xg")

    out, entry_count = build_group(sys.argv[1:-1])
    with open(sys.argv[-1], "wb") as destination:
        destination.write(out)
    print("wrote", sys.argv[-1], len(out), "bytes,", entry_count, "entries")


if __name__ == "__main__":
    main()
