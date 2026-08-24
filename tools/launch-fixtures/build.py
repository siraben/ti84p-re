#!/usr/bin/env python3
"""Build compiled-program launch-boundary link files."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
CASES = {
    "1FFF": 0x1FFF,
    "2000": 0x2000,
    "2001": 0x2001,
}


def ti83p_program_file(name: str, body: bytes) -> bytes:
    """Return a TI-83+/84+ .8xp file for a raw ProgObj body."""
    calc_name = name.encode("ascii")[:8]
    prog_data = len(body).to_bytes(2, "little") + body

    entry = bytearray()
    entry += (13).to_bytes(2, "little")
    entry += len(prog_data).to_bytes(2, "little")
    entry += bytes([0x05])
    entry += calc_name.ljust(8, b"\0")
    entry += bytes([0x00, 0x00])
    entry += len(prog_data).to_bytes(2, "little")
    entry += prog_data

    header = (
        b"**TI83F*"
        + bytes([0x1A, 0x0A, 0x00])
        + b"Compiled launch boundary fixture".ljust(42, b" ")
    )
    payload = header + len(entry).to_bytes(2, "little") + entry
    return payload + (sum(entry) & 0xFFFF).to_bytes(2, "little")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=HERE / "generated")
    parser.add_argument("--spasm", help="SPASM executable; defaults to spasm on PATH")
    args = parser.parse_args()

    spasm = args.spasm or shutil.which("spasm")
    if not spasm:
        raise SystemExit("SPASM not found; pass --spasm or enter a shell that provides spasm")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    payload_path = args.out_dir / "payload.bin"
    subprocess.run(
        [str(spasm), str(HERE / "payload.asm"), str(payload_path)],
        check=True,
        cwd=HERE,
    )
    payload = payload_path.read_bytes()
    if payload != b"\xC9":
        raise SystemExit(f"expected one-byte RET payload, got {payload.hex().upper()}")

    manifest: dict[str, object] = {
        "marker": "BB6D",
        "payload": payload.hex().upper(),
        "cases": {},
    }
    for suffix, internal_size in CASES.items():
        payload_name = f"B{suffix}"
        wrapper_name = f"A{suffix}"
        if internal_size < 2 + len(payload):
            raise AssertionError("internal size is too small for marker and payload")
        body = b"\xBB\x6D" + payload
        body += bytes(internal_size - len(body))
        link_file = ti83p_program_file(payload_name, body)
        path = args.out_dir / f"{payload_name}.8xp"
        path.write_bytes(link_file)
        wrapper_body = b"\xBB\x6A\x5F" + payload_name.encode("ascii") + b"\x11\x3F"
        wrapper_path = args.out_dir / f"{wrapper_name}.8xp"
        wrapper_path.write_bytes(ti83p_program_file(wrapper_name, wrapper_body))
        manifest["cases"][suffix] = {
            "file": path.name,
            "wrapper": wrapper_path.name,
            "internal_size": internal_size,
            "internal_size_hex": f"0x{internal_size:04X}",
            "native_payload_bytes": internal_size - 2,
            "sha256": hashlib.sha256(link_file).hexdigest(),
            "wrapper_sha256": hashlib.sha256(wrapper_path.read_bytes()).hexdigest(),
        }

    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="ascii"
    )
    print(f"wrote {len(CASES)} fixtures to {args.out_dir}")


if __name__ == "__main__":
    main()
