#!/usr/bin/env python3
"""Build a named guarded Flash emulator fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from flash_emulator_fixture import FLASH_FIXTURES, build_fixture


TOOLS = Path(__file__).resolve().parent
SOURCES = TOOLS / "emulator-probes"


def assemble(source: Path, spasm: str) -> bytes:
    """Assemble the fixture source and return raw machine code."""

    with tempfile.TemporaryDirectory(prefix="ti84-writeflash-fixture-") as temp_dir:
        output = Path(temp_dir) / f"{source.stem}.bin"
        completed = subprocess.run(
            [spasm, "-N", str(source), str(output)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"SPASM failed: {detail}")
        return output.read_bytes()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True, help="audited source ROM")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--fixture",
        choices=sorted(FLASH_FIXTURES),
        default="page-3e-cross",
        help="guarded probe to build (default: page-3e-cross)",
    )
    parser.add_argument("--spasm", default="spasm")
    args = parser.parse_args()

    spec = FLASH_FIXTURES[args.fixture]
    source = SOURCES / spec.source_name
    rom_output = args.output_dir / spec.rom_name
    program_output = args.output_dir / f"{spec.program_name}.8xp"
    runner_output = args.output_dir / f"{spec.runner_name}.8xp"
    manifest_output = args.output_dir / "manifest.json"
    existing = [
        path
        for path in (rom_output, program_output, runner_output, manifest_output)
        if path.exists()
    ]
    if existing:
        parser.error(
            "refusing to overwrite existing fixture output: "
            + ", ".join(map(str, existing))
        )

    try:
        machine_code = assemble(source, args.spasm)
        fixture = build_fixture(args.rom.read_bytes(), machine_code, args.fixture)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        rom_output.write_bytes(fixture.rom)
        program_output.write_bytes(fixture.program)
        runner_output.write_bytes(fixture.runner)
        manifest = {
            "fixture": fixture.spec.name,
            "source": fixture.spec.source_name,
            "rom": rom_output.name,
            "program": program_output.name,
            "runner": runner_output.name,
            "machine_code_sha256": fixture.machine_code_sha256,
            "source_rom_sha256": fixture.source_rom_sha256,
            "fixture_rom_sha256": fixture.fixture_rom_sha256,
            "rom_modified": fixture.spec.patch_unlock,
            "warning": fixture.spec.warning,
        }
        if fixture.spec.patch_unlock:
            manifest["patched_rom_sha256"] = fixture.fixture_rom_sha256
        manifest_output.write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
