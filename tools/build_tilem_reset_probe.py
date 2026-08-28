#!/usr/bin/env python3
"""Build the direct reset probe from the exact pinned TilEm source tree."""

from emulator_probe_build import tilem_main
from tilem_reset import TilemResetError, build_probe


if __name__ == "__main__":
    tilem_main(
        description=__doc__, plain_name="reset probe",
        adapter_names=("tilem_probe_support.c", "tilem_reset_probe.c"),
        build=build_probe, error_types=(TilemResetError,),
    )
