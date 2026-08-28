#!/usr/bin/env python3
"""Build the compact-display runner from pinned Wabbitemu sources."""

from ti84re.emulators.probe_build import wabbitemu_main


if __name__ == "__main__":
    wabbitemu_main(
        description=__doc__, plain_name=None,
        adapter_name="wabbitemu_compact_probe.cpp",
    )
