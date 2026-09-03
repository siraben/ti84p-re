#!/usr/bin/env python3
"""Run a guarded sector-geometry and chip-erase matrix through MAME 0.287."""

from pathlib import Path

from ti84re.emulators.mame.flash_erase import (
    parse_flash_erase_report,
    validate_erased_flash_image,
    validate_flash_erase_report,
)
from ti84re.emulators.mame.runtime import GuardedMameProbeRun
from ti84re.emulators.probe_cli import MameProbeCli, Report
from ti84re.paths import PROBES

MACHINE = "ti84pv3"


def load_report(output: str) -> Report:
    return validate_flash_erase_report(parse_flash_erase_report(output))


def augment(
    run: GuardedMameProbeRun,
    source_rom: Path,
    _report: Report,
) -> dict[str, object]:
    flash_path = run.layout.rom_root / "nvram" / MACHINE / "flash"
    image = validate_erased_flash_image(source_rom, flash_path)
    return {"flash_image": {"path": str(flash_path), **image}}


def summarize(result: Report) -> list[str]:
    image = result["flash_image"]
    return [
        "sector cases: regular64, top32, top8a, top8b, top16",
        f"chip erase: {image['changed_byte_count']} changed bytes, "
        f"SHA-256 {image['output_sha256']}",
    ]


PROBE = MameProbeCli(
    lua_script=PROBES / "mame/mame_flash_erase_probe.lua",
    seconds=25,
    load_report=load_report,
    augment=augment,
    launch=(
        "Lua sequences five sector erases and one chip erase through "
        "the TI-84 Plus membank0 Flash interface"
    ),
    evidence_scope=(
        "MAME 0.287 generic AMD_29F800T erase geometry, status range, "
        "timers, and TI-84 Plus mapping; not TI-OS or physical hardware"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
