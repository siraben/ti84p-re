#!/usr/bin/env python3
"""Build the compact-display runner from pinned TilEm sources."""

from ti84re.emulators.probe_build import tilem_main
from ti84re.emulators.tilem.core import TilemCoreError, build_probe


if __name__ == "__main__":
    tilem_main(
        description=__doc__, plain_name=None,
        adapter_names=("tilem_probe_support.c", "tilem_compact_probe.c"),
        build=build_probe, error_types=(TilemCoreError,), adapters_as_list=True,
        include_source=False,
    )
