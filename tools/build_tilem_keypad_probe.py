#!/usr/bin/env python3
"""Build the keypad probe from the exact pinned TilEm source tree."""

from emulator_probe_build import tilem_main
from tilem_keypad import TilemKeypadError, build_probe


if __name__ == "__main__":
    tilem_main(
        description=__doc__, plain_name="keypad probe",
        adapter_names=("tilem_probe_support.c", "tilem_keypad_probe.c"),
        build=build_probe, error_types=(TilemKeypadError,),
    )
