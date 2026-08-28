#!/usr/bin/env python3
"""Build the interrupt probe from the exact pinned TilEm source tree."""

from emulator_probe_build import tilem_main
from tilem_interrupt import TilemInterruptError, build_probe


if __name__ == "__main__":
    tilem_main(
        description=__doc__, plain_name="interrupt probe",
        adapter_names=("tilem_probe_support.c", "tilem_interrupt_probe.c"),
        build=build_probe, error_types=(TilemInterruptError,),
    )
