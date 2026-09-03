#!/usr/bin/env python3
"""Build calculator-side fixtures for community VAT and recovery probes."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
from zipfile import ZipFile

from ti84re.flash.archive_fixture import build_fresh_archive_fixture
from ti84re.hardware.probe import (
    TI_SIGNATURE,
    TiVariable,
)
from ti84re.tifiles.program import asm_call_body, encode_program_file
from ti84re.paths import DEFAULT_ROM


ARCHIVES = {
    "PRGMHIDE.8xp": ("programs/prgmhide.zip", "PRGMHIDE.8xp"),
    "HIDE.8xp": ("programs/programtoappvar.zip", "HIDE.8XP"),
    "PRGMAPPV.8xp": ("programs/prgmappv.zip", "PRGMAPPV.8XP"),
    "ARCHUTIL.8xp": ("programs/archive_utility.zip", "ARCHUTIL.8XP"),
}


def encode_raw_name_variable(
    variable_type: int,
    raw_name: bytes,
    data: bytes,
    *,
    archived: bool = False,
) -> bytes:
    """Encode a link variable whose calculator name is tokenized, not ASCII."""

    if not 1 <= len(raw_name) <= 8:
        raise ValueError("raw calculator name must contain one through eight bytes")
    entry = bytearray()
    entry += (13).to_bytes(2, "little")
    entry += len(data).to_bytes(2, "little")
    entry += bytes((variable_type,))
    entry += raw_name.ljust(8, b"\0")
    entry += bytes((0, 0x80 if archived else 0))
    entry += len(data).to_bytes(2, "little")
    entry += data
    header = TI_SIGNATURE + b"Community VAT trace fixture".ljust(42, b" ")
    payload = header + len(entry).to_bytes(2, "little") + entry
    return payload + (sum(entry) & 0xFFFF).to_bytes(2, "little")


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, bytes] = {}
    origins: dict[str, dict[str, str]] = {}
    for output_name, (archive_rel, member) in ARCHIVES.items():
        archive = args.corpus / archive_rel
        with ZipFile(archive) as zipped:
            data = zipped.read(member)
        outputs[output_name] = data
        origins[output_name] = {
            "archive": archive_rel,
            "archive_sha256": digest(archive.read_bytes()),
            "member": member,
            "member_sha256": digest(data),
        }

    # TI-OS launches the packaged binary programs through BASIC Asm( wrappers.
    # Their program bodies remain byte-for-byte identical to the archive members.
    outputs["APHIDE.8xp"] = encode_program_file(
        "APHIDE", asm_call_body("PRGMHIDE"), comment="PRGMHIDE launcher"
    )
    outputs["AAPPV.8xp"] = encode_program_file(
        "AAPPV", asm_call_body("PRGMAPPV"), comment="PRGMAPPV launcher"
    )
    outputs["AHIDE.8xp"] = encode_program_file(
        "AHIDE", asm_call_body("HIDE"), comment="HIDE launcher"
    )
    outputs["AARCHUT.8xp"] = encode_program_file(
        "AARCHUT", asm_call_body("ARCHUTIL"), comment="Archive Utility launcher"
    )
    with tempfile.TemporaryDirectory(prefix="community-numeric-bcalls-") as temp:
        binary = Path(temp) / "numeric-bcalls.bin"
        subprocess.run(
            ["spasm", str(Path(__file__).with_name("numeric-bcalls.asm")), str(binary)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        numeric_machine = binary.read_bytes()
    outputs["NUMBCALL.8xp"] = encode_program_file(
        "NUMBCALL", bytes((0xBB, 0x6D)) + numeric_machine,
        comment="numeric bcall trace fixture",
    )
    outputs["ANUMCALL.8xp"] = encode_program_file(
        "ANUMCALL", asm_call_body("NUMBCALL"), comment="numeric bcall launcher"
    )
    outputs["ZTARGET.8xp"] = encode_program_file(
        "ZTARGET", bytes((0x31, 0x3F)), comment="ordinary target"
    )
    outputs["ZARCH.8xp"] = encode_raw_name_variable(
        0x05,
        b"ZARCH",
        (2).to_bytes(2, "little") + bytes((0x31, 0x3F)),
        archived=True,
    )
    # Str0 has the token name AA 09. HIDE copies its five-byte data payload
    # after the size word into OP1 as the target name.
    outputs["STR0.8xs"] = encode_raw_name_variable(
        0x04,
        bytes((0xAA, 0x09)),
        (7).to_bytes(2, "little") + b"ZTARGET",
    )

    rom = args.rom.read_bytes()
    live = TiVariable(0x05, "LIVE", 0, False, b"\x02\x00\x31\x3F", "live")
    dead = TiVariable(0x06, "DEAD", 0, False, b"\x02\x00\x31\x3F", "dead")
    fixture = build_fresh_archive_fixture(rom, (live, dead), (0x20000,))
    archive_image = bytearray(fixture.image)
    dead_record = fixture.records[1]
    archive_image[dead_record.physical_start] = 0xF0
    outputs["archive-live-dead.rom"] = bytes(archive_image)
    filler = TiVariable(0x05, "FILL", 0, False, b"\x00" * 16337, "filler")
    cross = TiVariable(
        0x05,
        "CROSS",
        0,
        False,
        (32).to_bytes(2, "little") + bytes(range(32)),
        "cross-page",
    )
    cross_fixture = build_fresh_archive_fixture(
        rom, (filler, cross), (0x20000,)
    )
    if cross_fixture.records[1].logical_address != 0x7FE0:
        raise ValueError("cross-page fixture did not place CROSS at 08:7FE0")
    outputs["archive-cross-page.rom"] = cross_fixture.image

    for name, data in outputs.items():
        path = args.out_dir / name
        if path.exists() and not args.force:
            parser.error(f"refusing to overwrite {path}; pass --force")
        path.write_bytes(data)

    report = {
        "source_rom": str(args.rom),
        "source_rom_sha256": digest(rom),
        "corpus": str(args.corpus),
        "origins": origins,
        "outputs": {
            name: {"sha256": digest(data), "size": len(data)}
            for name, data in sorted(outputs.items())
        },
        "archive_records": [
            {
                "name": record.name,
                "type": record.variable_type,
                "status": 0xFC if record.name == "LIVE" else 0xF0,
                "page": record.page,
                "logical_address": record.logical_address,
                "physical_start": record.physical_start,
                "record_size": record.record_size,
            }
            for record in fixture.records
        ],
        "cross_page_record": {
            "name": cross_fixture.records[1].name,
            "page": cross_fixture.records[1].page,
            "logical_address": cross_fixture.records[1].logical_address,
            "physical_start": cross_fixture.records[1].physical_start,
            "record_size": cross_fixture.records[1].record_size,
        },
    }
    (args.out_dir / "manifest.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="ascii"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
