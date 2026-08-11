"""Reusable command and environment helpers for headless MAME traces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from mame_runtime import (
    MameRunConfiguration,
    build_command,
    headless_environment,
    machine_rom_name,
)

__all__ = [
    "MameTraceConfiguration",
    "build_command",
    "machine_rom_name",
    "trace_environment",
]


@dataclass(frozen=True)
class MameTraceConfiguration(MameRunConfiguration):
    """A MAME run with I/O trace and optional ON-key controls."""

    ports: str
    on_press_frame: int | None = None
    on_release_frame: int | None = None


def trace_environment(
    config: MameTraceConfiguration, base: Mapping[str, str]
) -> dict[str, str]:
    """Return an environment for SDL dummy output and Lua trace controls."""

    result = headless_environment(base)
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
