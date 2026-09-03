#!/usr/bin/env python3
"""Run a headless MAME TI-84 Plus I/O trace."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from ti84re.emulators.mame.trace import (
    MameTraceConfiguration,
    build_command,
    machine_rom_name,
    trace_environment,
)
from ti84re.paths import PROBES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=Path("tools/rom.bin"))
    parser.add_argument("--mame", default="mame", help="MAME executable")
    parser.add_argument("--machine", default="ti84pv3")
    parser.add_argument("--rom-name", help="override the MAME ROM filename")
    parser.add_argument("--seconds", type=int, default=2)
    parser.add_argument("--ports", default="03,04,55,56")
    parser.add_argument("--on-press-frame", type=int)
    parser.add_argument("--on-release-frame", type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    script = PROBES / "mame" / "mame_io_trace.lua"
    if not args.rom.is_file():
        raise SystemExit(f"ROM does not exist: {args.rom}")
    try:
        rom_name = args.rom_name or machine_rom_name(args.machine)
        with tempfile.TemporaryDirectory(prefix="ti84-mame-") as directory:
            rom_root = Path(directory)
            machine_dir = rom_root / args.machine
            machine_dir.mkdir()
            shutil.copyfile(args.rom, machine_dir / rom_name)
            config = MameTraceConfiguration(
                executable=args.mame,
                machine=args.machine,
                rom_root=rom_root,
                seconds=args.seconds,
                lua_script=script,
                ports=args.ports,
                on_press_frame=args.on_press_frame,
                on_release_frame=args.on_release_frame,
            )
            result = subprocess.run(
                build_command(config),
                env=trace_environment(config, os.environ),
                check=False,
            )
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
