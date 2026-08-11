#!/usr/bin/env python3
"""Run a binary-guarded Flash command/status matrix through MAME 0.287."""

from pathlib import Path

from mame_flash import (
    MAME_FLASH_IMAGE_SHA256,
    parse_flash_report,
    validate_flash_image,
    validate_flash_report,
)
from mame_runtime import GuardedMameProbeRun
from probe_cli import MameProbeCli, Report

TOOLS = Path(__file__).resolve().parent
MACHINE = "ti84pv3"


def load_report(output: str) -> Report:
    return validate_flash_report(parse_flash_report(output))


def augment(
    run: GuardedMameProbeRun,
    source_rom: Path,
    _report: Report,
) -> dict[str, object]:
    flash_path = run.layout.rom_root / "nvram" / MACHINE / "flash"
    image = validate_flash_image(
        source_rom,
        flash_path,
        expected_sha256=MAME_FLASH_IMAGE_SHA256,
    )
    return {"flash_image": {"path": str(flash_path), **image}}


def summarize(result: Report) -> list[str]:
    native = result["report"]["native"]
    image = result["flash_image"]
    return [
        "program: "
        f"FF->50={native['legal_stored']:02X}, "
        f"50->D0={native['illegal_stored']:02X}",
        "top-sector busy reads: "
        f"selected {native['busy_selected']}, "
        f"adjacent {native['busy_adjacent']:02X}, boot {native['busy_boot']:02X}",
        f"final Flash: {image['changed_byte_count']} changed bytes, "
        f"SHA-256 {image['output_sha256']}",
    ]


PROBE = MameProbeCli(
    lua_script=TOOLS / "mame_flash_probe.lua",
    seconds=2,
    load_report=load_report,
    augment=augment,
    launch=(
        "Lua writes and reads the TI-84 Plus membank0 Flash interface; "
        "MAME persists the complete final array to isolated NVRAM"
    ),
    evidence_scope=(
        "MAME 0.287 generic AMD_29F800T and TI-84 Plus mapping behavior; "
        "not TI-OS Flash routines or physical hardware"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
