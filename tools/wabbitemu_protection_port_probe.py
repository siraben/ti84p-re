"""Reusable oracle for Wabbitemu's native protected-boundary port probe."""

from __future__ import annotations

import json

from execution_protection import (
    WABBITEMU_BOUNDARY_PORTS,
    WabbitemuProtectionPortModel,
)
from wabbitemu_headless import (
    WabbitemuHeadlessError,
    WabbitemuProtectionPortReport,
)


def _read_vector(model: WabbitemuProtectionPortModel) -> tuple[int, ...]:
    reads = tuple(model.read_port(port) for port in range(0x22, 0x27))
    if any(value is None for value in reads):
        raise ValueError("Wabbitemu model omitted a protected-boundary read")
    return tuple(int(value) for value in reads)


def expected_protection_port_values() -> dict[str, object]:
    """Return source-model values for every native protected-port case."""

    model = WabbitemuProtectionPortModel()
    initial_reads = _read_vector(model)
    locked_write_accepted = tuple(
        model.write_port(port, 0xA2 + index)
        for index, port in enumerate(range(0x22, 0x27))
    )
    locked_reads = _read_vector(model)

    model.flash_locked = False
    model.flash_lower = 0x01A5
    model.flash_upper = 0x02B6
    low_writes = (0xCC, 0xDD)
    model.write_port(0x22, low_writes[0])
    model.write_port(0x23, low_writes[1])
    low_write_reads = (model.read_port(0x22), model.read_port(0x23))
    low_write_flash_lower = model.flash_lower
    low_write_flash_upper = model.flash_upper

    model.write_port(0x24, 0xFF)
    port24_read = model.read_port(0x24)
    port24_flash_lower = model.flash_lower
    port24_flash_upper = model.flash_upper

    wrap_values = (0x3F, 0x40, 0x41, 0xFF)
    ram_lower_reads = []
    ram_lower_internal = []
    ram_upper_reads = []
    ram_upper_internal = []
    for value in wrap_values:
        model.write_port(0x25, value)
        ram_lower_reads.append(model.read_port(0x25))
        ram_lower_internal.append(model.ram_lower)
        model.write_port(0x26, value)
        ram_upper_reads.append(model.read_port(0x26))
        ram_upper_internal.append(model.ram_upper)

    return {
        "port_active": tuple(port in WABBITEMU_BOUNDARY_PORTS for port in range(0x22, 0x27)),
        "port_protected": (True, True, True, True, True),
        "initial_flash_locked": True,
        "initial_reads": initial_reads,
        "initial_flash_lower": 0x0010,
        "initial_flash_upper": 0x0030,
        "initial_port24": 0x00,
        "initial_ram_lower": 0x0000,
        "initial_ram_upper": 0x03FF,
        "locked_write_accepted": locked_write_accepted,
        "locked_reads": locked_reads,
        "configured_flash_locked": False,
        "seeded_flash_lower": 0x01A5,
        "seeded_flash_upper": 0x02B6,
        "low_writes": low_writes,
        "low_write_reads": tuple(int(value) for value in low_write_reads),
        "low_write_flash_lower": low_write_flash_lower,
        "low_write_flash_upper": low_write_flash_upper,
        "port24_written": 0xFF,
        "port24_read": int(port24_read),
        "port24_flash_lower": port24_flash_lower,
        "port24_flash_upper": port24_flash_upper,
        "wrap_values": wrap_values,
        "ram_lower_reads": tuple(int(value) for value in ram_lower_reads),
        "ram_lower_internal": tuple(ram_lower_internal),
        "ram_upper_reads": tuple(int(value) for value in ram_upper_reads),
        "ram_upper_internal": tuple(ram_upper_internal),
        "tstates": 0,
    }


def validate_protection_port_report(
    report: WabbitemuProtectionPortReport,
) -> dict[str, object]:
    """Check native protected-port observations against the source model."""

    expected = expected_protection_port_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native protection-port report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "mapped_ports": sorted(WABBITEMU_BOUNDARY_PORTS),
            "write_gate": "all five writes require Wabbitemu's Flash lock to be open",
            "read_gate": "reads remain active while the Flash lock is closed",
            "flash_low_bytes": "ports 0x22 and 0x23 preserve seeded high bytes",
            "port24": (
                "stores the raw byte but clears both seeded high-bound fields because "
                "shift binds before bitwise AND"
            ),
            "ram_fields": "ports 0x25 and 0x26 wrap through 16-bit storage",
            "direct_seed_scope": (
                "the probe opens the in-memory lock and seeds high fields directly; "
                "it does not execute the retail protected-byte sequence"
            ),
        },
        "native": observed,
    }
