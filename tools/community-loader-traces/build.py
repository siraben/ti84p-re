#!/usr/bin/env python3
"""Build link-only fixtures for community loader traces."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware_probe import encode_ti_variable_file  # noqa: E402
from ti_program import asm_call_body, encode_program_file  # noqa: E402


RELEASES = {
    "RUNCOUNT.8xp": (
        "programs/runcounter16.zip.contents/RUNCOUNT.8xp",
        "41615816759a6cb2df1aee41f906956a6823aa09c19e4ec8e79712868c1d889a",
    ),
    "PLASMA.8xp": (
        "shells/plasma141.zip.contents/Plasma/PLASMA.8XP",
        "a55816b3ea9462c4e7ef16750d3ad6f8955b0a51de6a096c8b7e59f1242f0df1",
    ),
}
TSE_GROUP = (
    "shells/old/tsekrnl.zip.contents/Tse.8xg",
    "4cde52eb0ec37c16a5ac17f2f6eb94c7e3f4ebc4020b577b70d32ac34b29f3cf",
)


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def archive_link_file(blob: bytes) -> bytes:
    """Return a single-entry link file with its archive flag set."""

    archived = bytearray(blob)
    archived[69] = 0x80
    archived[-2:] = (sum(archived[55:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(archived)


def ion_client(name: str, *, archived: bool) -> bytes:
    """Return a protected Ion client that writes 0x42 to ram:9DA6."""

    # RET guards direct Asm(.  Plasma enters at userMem+1 with carry clear, so
    # JR NC skips the NUL-terminated description and reaches the marker store.
    body = bytes.fromhex("C930065452414345003E4232A69DC900")
    data = len(body).to_bytes(2, "little") + body
    return encode_ti_variable_file(
        0x06,
        name,
        data,
        archived=archived,
        comment="Plasma loader trace client",
    )


def split_tse_group(blob: bytes, *, archived_runtime: bool) -> dict[str, bytes]:
    """Split the identified TSE group into single-variable link files."""

    end = 55 + int.from_bytes(blob[53:55], "little")
    position = 55
    outputs = {}
    while position < end:
        size = int.from_bytes(blob[position + 2 : position + 4], "little")
        variable_type = blob[position + 4]
        name = blob[position + 5 : position + 13].split(b"\0", 1)[0].decode("ascii")
        version = blob[position + 13]
        data = blob[position + 17 : position + 17 + size]
        if len(data) != size:
            raise ValueError("truncated TSE group member")
        archived = archived_runtime and name in {"TSEKRNL", "TSELIBS"}
        outputs[name] = encode_ti_variable_file(
            variable_type,
            name,
            data,
            version=version,
            archived=archived,
            comment="TSE loader trace member",
        )
        position += 17 + size
    if position != end or set(outputs) != {"A", "LOADTSE", "TSEKRNL", "TSELIBS"}:
        raise ValueError("unexpected TSE group layout")
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extracted", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, bytes] = {}
    for output_name, (relative, expected) in RELEASES.items():
        data = (args.extracted / relative).read_bytes()
        if digest(data) != expected:
            raise SystemExit(f"unexpected digest for {relative}")
        outputs[output_name] = data
    outputs["ACOUNT.8xp"] = encode_program_file(
        "ACOUNT", asm_call_body("RUNCOUNT"), comment="RUNCOUNT trace launcher"
    )
    outputs["APLASMA.8xp"] = encode_program_file(
        "APLASMA", asm_call_body("PLASMA"), comment="Plasma trace launcher"
    )
    outputs["TRACECL.8xp"] = ion_client("TRACECL", archived=False)
    outputs["TRACARC.8xp"] = ion_client("TRACARC", archived=True)
    outputs["RUNCOUNT-archived.8xp"] = archive_link_file(outputs["RUNCOUNT.8xp"])
    tse_relative, tse_expected = TSE_GROUP
    tse_group = (args.extracted / tse_relative).read_bytes()
    if digest(tse_group) != tse_expected:
        raise SystemExit(f"unexpected digest for {tse_relative}")
    outputs["TSE.8xg"] = tse_group
    for name, data in split_tse_group(tse_group, archived_runtime=False).items():
        outputs[f"tse-ram-{name}.8xp"] = data
    for name, data in split_tse_group(tse_group, archived_runtime=True).items():
        outputs[f"tse-archive-{name}.8xp"] = data

    manifest = {}
    for name, data in outputs.items():
        (args.out_dir / name).write_bytes(data)
        manifest[name] = {"sha256": digest(data), "bytes": len(data)}
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )


if __name__ == "__main__":
    main()
