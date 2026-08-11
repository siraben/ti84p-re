"""Reusable command and environment helpers for headless MAME traces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MameTraceConfiguration:
    executable: str
    machine: str
    rom_root: Path
    seconds: int
    lua_script: Path
    ports: str
    on_press_frame: int | None = None
    on_release_frame: int | None = None


def machine_rom_name(machine: str) -> str:
    """Return the known MAME ROM filename for supported TI-84 Plus drivers."""

    names = {
        "ti84pv3": "ti84pv3v255mp.bin",
    }
    try:
        return names[machine]
    except KeyError as error:
        raise ValueError(f"unknown ROM filename for MAME machine {machine!r}") from error


def build_command(config: MameTraceConfiguration) -> list[str]:
    """Build the noninteractive MAME invocation."""

    if config.seconds <= 0:
        raise ValueError("trace duration must be positive")
    return [
        config.executable,
        config.machine,
        "-rompath",
        str(config.rom_root),
        "-cfg_directory",
        str(config.rom_root / "cfg"),
        "-nvram_directory",
        str(config.rom_root / "nvram"),
        "-snapshot_directory",
        str(config.rom_root / "snap"),
        "-video",
        "soft",
        "-sound",
        "none",
        "-seconds_to_run",
        str(config.seconds),
        "-nothrottle",
        "-skip_gameinfo",
        "-autoboot_script",
        str(config.lua_script),
    ]


def trace_environment(
    config: MameTraceConfiguration, base: dict[str, str]
) -> dict[str, str]:
    """Return an environment for SDL dummy output and Lua trace controls."""

    result = dict(base)
    result["SDL_VIDEODRIVER"] = "dummy"
    result["SDL_AUDIODRIVER"] = "dummy"
    result["MAME_TRACE_PORTS"] = config.ports
    for name, value in (
        ("MAME_ON_PRESS_FRAME", config.on_press_frame),
        ("MAME_ON_RELEASE_FRAME", config.on_release_frame),
    ):
        if value is not None and value < 0:
            raise ValueError("ON event frames must be nonnegative")
        if value is None:
            result.pop(name, None)
        else:
            result[name] = str(value)
    if (
        config.on_press_frame is not None
        and config.on_release_frame is not None
        and config.on_release_frame <= config.on_press_frame
    ):
        raise ValueError("ON release frame must follow press frame")
    return result
