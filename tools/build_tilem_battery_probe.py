#!/usr/bin/env python3
"""Build the battery-comparator probe from the exact pinned TilEm source tree."""

from emulator_probe_build import tilem_main
from tilem_battery import TilemBatteryError, build_probe


if __name__ == "__main__":
    tilem_main(
        description=__doc__, plain_name="battery probe",
        adapter_names=("tilem_probe_support.c", "tilem_battery_probe.c"),
        build=build_probe, error_types=(TilemBatteryError,),
    )
