#!/usr/bin/env python3
"""Run a guarded CPU-visible Flash-gate matrix through MAME 0.287."""

from pathlib import Path

from ti84re.emulators.mame.flash_gate import (
    parse_flash_gate_report,
    validate_flash_gate_image,
    validate_flash_gate_report,
)
from ti84re.emulators.mame.runtime import GuardedMameProbeRun
from ti84re.emulators.probe_cli import MameProbeCli, Report
from ti84re.paths import PROBES

MACHINE = "ti84pv3"


def load_report(output: str) -> Report:
    return validate_flash_gate_report(parse_flash_gate_report(output))


def augment(
    run: GuardedMameProbeRun,
    source_rom: Path,
    _report: Report,
) -> dict[str, object]:
    flash_path = run.layout.rom_root / "nvram" / MACHINE / "flash"
    image = validate_flash_gate_image(source_rom, flash_path)
    return {"flash_image": {"path": str(flash_path), **image}}


def summarize(result: Report) -> list[str]:
    native_cases = result["report"]["native"]["cases"]
    image = result["flash_image"]
    return [
        "gate cases: "
        + ", ".join(
            f"{case['name']}={case['physical_byte']:02X}" for case in native_cases
        ),
        f"final Flash: {image['changed_byte_count']} changed byte, "
        f"SHA-256 {image['output_sha256']}",
    ]


PROBE = MameProbeCli(
    lua_script=PROBES / "mame/mame_flash_gate_probe.lua",
    seconds=2,
    load_report=load_report,
    augment=augment,
    launch=(
        "Lua maps Flash page 08 into the CPU program space and changes "
        "port 0x14 between AMD command phases"
    ),
    evidence_scope=(
        "MAME 0.287 TI-84 Plus CPU and I/O mapping plus generic "
        "AMD_29F800T writes; not TI-OS execution or physical hardware"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
