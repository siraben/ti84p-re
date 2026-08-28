#!/usr/bin/env python3
"""Build the generic exact-probe runner from pinned Wabbitemu sources."""

from ti84re.emulators.probe_build import wabbitemu_main


if __name__ == "__main__":
    wabbitemu_main(
        description=__doc__, plain_name="built exact-probe runner",
        adapter_name="wabbitemu_exact_probe.cpp",
    )
