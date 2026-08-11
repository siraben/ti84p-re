#!/usr/bin/env python3
"""Assemble and package physical TI-84 Plus hardware probes."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from hardware_probe import APPVAR_TYPE, PROBE_FORMAT_VERSION, PROBE_MAGIC
from tibasic_samples import T, hex_literal, ti83p_program_file


TOOLS = Path(__file__).resolve().parent
PROBE_DIR = TOOLS / "hardware-probes"
USER_MEM = 0x9D95
PROGRAM_LIMIT = 0xC000
PROBE_START = 0x9DB5
CREATE_APPVAR_COPY = b"\xEF\x6A\x4E\xE1\xC1\x13\x13\xED\xB0"


@dataclass(frozen=True)
class ProbeDefinition:
    """Build and result schema for one calculator-side probe."""

    source_name: str
    program: str
    appvar: str
    probe_id: int
    payload_size: int

    @property
    def source(self) -> Path:
        return PROBE_DIR / self.source_name


PROBES = {
    "md5-edge": ProbeDefinition(
        "md5-edge.asm", "HWPMD5", "HWPMD511", 1, 20
    ),
    "ram-alias": ProbeDefinition(
        "ram-alias.asm", "HWPRAM", "HWPRAM21", 2, 18
    ),
    "asic-snapshot": ProbeDefinition(
        "asic-snapshot.asm", "HWASIC", "HWPASIC1", 3, 11
    ),
}


def probe_definition(probe_name: str) -> ProbeDefinition:
    """Return one validated probe definition."""

    try:
        probe = PROBES[probe_name]
    except KeyError:
        choices = ", ".join(PROBES)
        raise ValueError(f"unknown probe {probe_name!r}; choose {choices}") from None
    if not 1 <= len(probe.program) <= 8:
        raise ValueError(f"program name for {probe_name} must be one through eight bytes")
    if len(probe.appvar) != 8:
        raise ValueError(f"result AppVar name for {probe_name} must be eight bytes")
    return probe


def asmprgm_body(machine_code: bytes) -> list[int]:
    """Return a tokenized ``AsmPrgm`` body containing *machine_code*."""

    if not machine_code:
        raise ValueError("probe machine code is empty")
    return [
        T["2byte"],
        T["asmprgm"],
        T["enter"],
        *hex_literal(machine_code.hex()),
        T["enter"],
    ]


def validate_machine_code(probe_name: str, machine_code: bytes) -> None:
    """Check stable entry, result-frame, and AppVar-copy invariants."""

    probe = probe_definition(probe_name)
    if len(machine_code) < 3:
        raise ValueError(f"{probe_name} machine code is too short")
    if machine_code[0] != 0xC3:
        raise ValueError(f"{probe_name} must begin with JP start")
    entry = int.from_bytes(machine_code[1:3], "little")
    if entry != PROBE_START:
        raise ValueError(
            f"{probe_name} entry jump targets 0x{entry:04X}, expected 0x{PROBE_START:04X}"
        )
    if USER_MEM + len(machine_code) > PROGRAM_LIMIT:
        raise ValueError(f"{probe_name} extends beyond the 0xBFFF user-RAM bank")
    if CREATE_APPVAR_COPY not in machine_code:
        raise ValueError(
            f"{probe_name} does not skip the AppVar size word before copying"
        )
    appvar_marker = bytes((APPVAR_TYPE,)) + probe.appvar.encode("ascii")
    if machine_code.count(appvar_marker) != 1:
        raise ValueError(f"{probe_name} must contain its result AppVar name once")
    frame = (
        PROBE_MAGIC
        + bytes((PROBE_FORMAT_VERSION, probe.probe_id))
        + probe.payload_size.to_bytes(2, "little")
        + bytes(2 + probe.payload_size)
    )
    if not machine_code.endswith(frame):
        raise ValueError(
            f"{probe_name} does not end with its {probe.payload_size}-byte result frame"
        )


def package_probe(
    probe_name: str, machine_code: bytes
) -> tuple[bytes, dict[str, object]]:
    """Package assembled bytes as an ``AsmPrgm`` link file."""

    probe = probe_definition(probe_name)
    validate_machine_code(probe_name, machine_code)
    program = ti83p_program_file(probe.program, asmprgm_body(machine_code))
    metadata: dict[str, object] = {
        "probe": probe_name,
        "probe_id": probe.probe_id,
        "source": f"tools/hardware-probes/{probe.source_name}",
        "program": probe.program,
        "result_appvar": probe.appvar,
        "payload_size": probe.payload_size,
        "machine_code_size": len(machine_code),
        "machine_code_sha256": hashlib.sha256(machine_code).hexdigest(),
        "program_file_size": len(program),
        "program_file_sha256": hashlib.sha256(program).hexdigest(),
    }
    return program, metadata


def assemble_probe(
    probe_name: str,
    *,
    spasm: str = "spasm",
) -> tuple[bytes, dict[str, object]]:
    """Assemble one named probe and return its ``.8xp`` plus metadata."""

    probe = probe_definition(probe_name)
    with tempfile.TemporaryDirectory(prefix="ti84-hwprobe-") as temp_dir:
        raw_path = Path(temp_dir) / f"{probe_name}.bin"
        completed = subprocess.run(
            [
                spasm,
                "-N",
                "-I",
                str(PROBE_DIR),
                str(probe.source),
                str(raw_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"SPASM failed for {probe_name}: {detail}")
        machine_code = raw_path.read_bytes()
    return package_probe(probe_name, machine_code)


def build_probes(
    probe_names: list[str], output_dir: Path, *, spasm: str = "spasm"
) -> dict[str, object]:
    """Build probes into *output_dir* and return their stable manifest."""

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for probe_name in probe_names:
        program, row = assemble_probe(probe_name, spasm=spasm)
        output_name = f"{row['program']}.8xp"
        (output_dir / output_name).write_bytes(program)
        row["output"] = output_name
        rows.append(row)
    manifest: dict[str, object] = {"format": 1, "probes": rows}
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "probe",
        nargs="*",
        choices=PROBES,
        help="probe to build (default: all)",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--spasm", default="spasm")
    args = parser.parse_args()
    try:
        manifest = build_probes(
            list(args.probe or PROBES), args.output_dir, spasm=args.spasm
        )
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
