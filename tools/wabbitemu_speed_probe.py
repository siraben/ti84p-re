"""Reusable oracle for the native Wabbitemu speed and delay-register probe."""

from __future__ import annotations

from dataclasses import asdict
import json

from bus_timing import BusTiming, TimingImplementation, WABBITEMU_PROFILE
from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuSpeedReport


def _mode_vectors(extra_speeds: bool) -> tuple[tuple[int, ...], tuple[int, ...]]:
    implementation = TimingImplementation(
        profile="wabbitemu",
        extra_speeds=extra_speeds,
    )
    reads = []
    frequencies = []
    for value in range(0xFC, 0x100):
        implementation.write_port(0x20, value)
        read = implementation.read_port(0x20)
        if read is None:
            raise ValueError("Wabbitemu model did not map port 0x20")
        reads.append(read)
        frequencies.append(implementation.clock_mhz() * 1_000_000)
    return tuple(reads), tuple(frequencies)


def _wait_mask(timing: BusTiming, mode: int) -> int:
    waits = asdict(timing.memory_waits(mode))
    names = (
        "flash_opcode",
        "flash_read",
        "flash_write",
        "ram_opcode",
        "ram_read",
        "ram_write",
    )
    return sum(int(waits[name]) << bit for bit, name in enumerate(names))


def expected_speed_values() -> dict[str, object]:
    """Return the pinned source-model value for every native speed case."""

    default_reads, default_frequencies = _mode_vectors(False)
    extra_reads, extra_frequencies = _mode_vectors(True)

    latches = TimingImplementation(profile="wabbitemu", extra_speeds=True)
    latch_written = tuple(range(0xA9, 0xB0))
    for port, value in zip(range(0x29, 0x30), latch_written, strict=True):
        if not latches.write_port(port, value):
            raise ValueError(f"Wabbitemu model did not map port 0x{port:02X}")
    latch_reads = tuple(latches.read_port(port) for port in range(0x29, 0x30))
    if any(value is None for value in latch_reads):
        raise ValueError("Wabbitemu model omitted a delay-latch read")

    timing = BusTiming(
        port29=0x00,
        port2a=0x01,
        port2b=0x02,
        port2c=0x03,
        port2e=0x77,
    )
    return {
        "port20_active": 0x20 in WABBITEMU_PROFILE.mapped_ports,
        "delay_ports_active": tuple(
            port in WABBITEMU_PROFILE.mapped_ports for port in range(0x29, 0x30)
        ),
        "reset_speed": 0,
        "reset_frequency": 6_000_000,
        "reset_timer_version": 0,
        "reset_delay_reads": (0, 0, 0, 0, 0, 0, 0),
        "default_speed_reads": default_reads,
        "default_frequencies": default_frequencies,
        "extra_speed_reads": extra_reads,
        "extra_frequencies": extra_frequencies,
        "latch_written": latch_written,
        "latch_reads": tuple(int(value) for value in latch_reads),
        "wait_masks": tuple(_wait_mask(timing, mode) for mode in range(4)),
        "port2d_written": 0x5A,
        "port2d_read": 0x5A,
        "port2d_wait_unchanged": True,
        "port2d_freq_unchanged": True,
        "port2d_timer_version_unchanged": True,
        "port2d_xtal_unchanged": True,
        "port2d_lcd_active_unchanged": True,
        "port2d_halt_unchanged": True,
        "port2d_interrupt_unchanged": True,
        "port2d_tstates_unchanged": True,
        "tstates": 0,
    }


def validate_speed_report(report: WabbitemuSpeedReport) -> dict[str, object]:
    """Check native speed observations against the reusable source model."""

    expected = expected_speed_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native speed report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "reset": "mode 0, 6 MHz, timer_version 0, and seven zero latches",
            "default_speed_policy": "modes 2 and 3 clamp to mode 1",
            "front_end_speed_policy": "timer_version 1 enables 20 and 25 MHz",
            "front_end_seed_scope": (
                "timer_version is direct emulator configuration, not a calculator port"
            ),
            "delay_selection": (
                "the active speed register gates Flash and RAM wait classes"
            ),
            "port2d_policy": (
                "raw fifth delay latch with no modeled low-power or timer transition"
            ),
        },
        "native": observed,
    }
