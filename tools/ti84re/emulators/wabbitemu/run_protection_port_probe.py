#!/usr/bin/env python3
"""Run guarded protected-boundary port edges through pinned Wabbitemu."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, WabbitemuProbeCli
from ti84re.emulators.wabbitemu.headless import run_protection_port_probe
from ti84re.emulators.wabbitemu.protection_port_probe import validate_protection_port_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable protection-port summary."""

    native = report["native"]
    return (
        "locked writes: "
        + "/".join(str(int(value)) for value in native["locked_write_accepted"])
        + f"; port 24 bound fields={native['port24_flash_lower']:04X}/"
        + f"{native['port24_flash_upper']:04X}",
        "RAM lower: "
        + "/".join(f"{value:04X}" for value in native["ram_lower_internal"])
        + "; upper: "
        + "/".join(f"{value:04X}" for value in native["ram_upper_internal"]),
    )


PROBE = WabbitemuProbeCli(
    runner=run_protection_port_probe,
    validator=validate_protection_port_report,
    launch="direct initialized-core protected-boundary port calls",
    evidence_scope=(
        "pinned Wabbitemu port registration, shared protected-write gate, "
        "Flash-bound low-byte and port-0x24 behavior, and 16-bit RAM-bound "
        "storage; not the retail protected-byte sequence, opcode-fetch "
        "outcomes, or physical ASIC behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
