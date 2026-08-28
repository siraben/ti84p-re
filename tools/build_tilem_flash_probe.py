#!/usr/bin/env python3
"""Build the direct Flash-command probe from exact pinned TilEm sources."""

from emulator_probe_build import tilem_main
from tilem_core import TilemCoreError, build_probe


if __name__ == "__main__":
    tilem_main(
        description=__doc__, plain_name="Flash probe",
        adapter_names=("tilem_probe_support.c", "tilem_flash_probe.c"),
        build=build_probe, error_types=(TilemCoreError,), adapters_as_list=True,
    )
