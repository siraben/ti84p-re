#!/usr/bin/env python3
"""Build the MD5-assist probe from the exact pinned TilEm source tree."""

from emulator_probe_build import tilem_main
from tilem_md5 import TilemMd5Error, build_probe


if __name__ == "__main__":
    tilem_main(
        description=__doc__, plain_name="MD5 probe",
        adapter_names=("tilem_probe_support.c", "tilem_md5_probe.c"),
        build=build_probe, error_types=(TilemMd5Error,),
    )
