"""Reusable decoders for the TI-84 Plus legacy interrupt controller.

Ports ``0x03`` and ``0x04`` share interrupt-mask, acknowledgement, status,
timer-rate, memory-map, battery-selector, and low-power controls.  This module
models the public bit contract and the dispatch order visible in OS 2.55MP.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


LEGACY_SOURCE_BITS = {
    0: "on",
    1: "standard_timer_1",
    2: "standard_timer_2",
    4: "link_activity",
}

PROGRAMMABLE_SOURCE_BITS = {
    5: "programmable_timer_1",
    6: "programmable_timer_2",
    7: "programmable_timer_3",
}

ROM_STATUS_TEST_BITS = (7, 5, 6, 2, 4, 0, 1)
LEGACY_SOURCE_MASK = sum(1 << bit for bit in LEGACY_SOURCE_BITS)
WABBITEMU_STANDARD_TIMER_RATES = (512, 227, 158, 108)


def _byte(value: int, name: str) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be a byte")
    return value


@dataclass(frozen=True)
class Port03Mask:
    """Decoded interrupt mask and low-power control written to port ``0x03``."""

    raw: int
    on_enabled: bool
    standard_timer_1_enabled: bool
    standard_timer_2_enabled: bool
    keep_power_during_halt: bool
    link_activity_enabled: bool
    unused_bits: int

    @property
    def low_power_on_halt(self) -> bool:
        return not self.keep_power_during_halt

    @property
    def enabled_sources(self) -> tuple[str, ...]:
        return tuple(
            name
            for bit, name in LEGACY_SOURCE_BITS.items()
            if self.raw & (1 << bit)
        )

    @property
    def tilem_programmable_timers_can_wake_halt(self) -> bool:
        """Expose TilEm's dependency on either standard timer being enabled."""

        return self.standard_timer_1_enabled or self.standard_timer_2_enabled


def decode_port03(value: int) -> Port03Mask:
    """Decode a port-``0x03`` mask/control value."""

    value = _byte(value, "port 0x03 value")
    return Port03Mask(
        raw=value,
        on_enabled=bool(value & 0x01),
        standard_timer_1_enabled=bool(value & 0x02),
        standard_timer_2_enabled=bool(value & 0x04),
        keep_power_during_halt=bool(value & 0x08),
        link_activity_enabled=bool(value & 0x10),
        unused_bits=value & 0xE0,
    )


@dataclass(frozen=True)
class Port04Status:
    """Decoded interrupt-source and ON-level status read from port ``0x04``."""

    raw: int
    on_pending: bool
    standard_timer_1_pending: bool
    standard_timer_2_pending: bool
    on_released: bool
    link_activity_pending: bool
    programmable_timer_1_finished: bool
    programmable_timer_2_finished: bool
    programmable_timer_3_finished: bool

    @property
    def legacy_pending_sources(self) -> tuple[str, ...]:
        return tuple(
            name
            for bit, name in LEGACY_SOURCE_BITS.items()
            if self.raw & (1 << bit)
        )

    @property
    def finished_programmable_timers(self) -> tuple[str, ...]:
        return tuple(
            name
            for bit, name in PROGRAMMABLE_SOURCE_BITS.items()
            if self.raw & (1 << bit)
        )


def decode_port04_status(value: int) -> Port04Status:
    """Decode a port-``0x04`` read without treating bit 3 as an interrupt."""

    value = _byte(value, "port 0x04 status")
    return Port04Status(
        raw=value,
        on_pending=bool(value & 0x01),
        standard_timer_1_pending=bool(value & 0x02),
        standard_timer_2_pending=bool(value & 0x04),
        on_released=bool(value & 0x08),
        link_activity_pending=bool(value & 0x10),
        programmable_timer_1_finished=bool(value & 0x20),
        programmable_timer_2_finished=bool(value & 0x40),
        programmable_timer_3_finished=bool(value & 0x80),
    )


@dataclass(frozen=True)
class Port04Configuration:
    """Decode the unrelated controls selected by a port-``0x04`` write."""

    raw: int
    paired_mapping: bool
    standard_timer_index: int
    battery_selector: int
    other_bits: int


def decode_port04_configuration(value: int) -> Port04Configuration:
    """Decode mapping mode, timer-rate index, and battery selector."""

    value = _byte(value, "port 0x04 configuration")
    return Port04Configuration(
        raw=value,
        paired_mapping=bool(value & 0x01),
        standard_timer_index=(value >> 1) & 0x03,
        battery_selector=(value >> 6) & 0x03,
        other_bits=value & 0x38,
    )


def standard_timer_period(value: int, timer: int = 1) -> Fraction:
    """Return the documented timer period as an exact fraction of a second."""

    config = decode_port04_configuration(value)
    if timer not in (1, 2):
        raise ValueError("standard timer must be 1 or 2")
    numerator = 64 + 80 * config.standard_timer_index
    denominator = 32768 * (2 if timer == 2 else 1)
    return Fraction(numerator, denominator)


def wabbitemu_standard_timer_period(value: int, timer: int = 1) -> Fraction:
    """Return the period selected by Wabbitemu's rounded rate table."""

    config = decode_port04_configuration(value)
    if timer not in (1, 2):
        raise ValueError("standard timer must be 1 or 2")
    rate = WABBITEMU_STANDARD_TIMER_RATES[config.standard_timer_index]
    return Fraction(1, rate * (2 if timer == 2 else 1))


def acknowledge_legacy_sources(pending: int, mask_write: int) -> int:
    """Apply the documented clear-on-zero acknowledgement from a port-3 write.

    Bits 5-7 are programmable-timer completion flags and are not acknowledged
    through port ``0x03``.  Bit 3 is an ON-key level, not a pending source.
    """

    pending = _byte(pending, "pending status")
    mask_write = _byte(mask_write, "port 0x03 write")
    return pending & ((mask_write & LEGACY_SOURCE_MASK) | ~LEGACY_SOURCE_MASK) & 0xFF


def rom_status_test_order(status: int) -> tuple[str, ...]:
    """Return set fields in the order tested by the OS IM1 handler."""

    status = _byte(status, "port 0x04 status")
    names = {**LEGACY_SOURCE_BITS, **PROGRAMMABLE_SOURCE_BITS}
    return tuple(
        names[bit] for bit in ROM_STATUS_TEST_BITS if status & (1 << bit)
    )


def usb_active_low_sources(value: int) -> int:
    """Return the active low-five-bit USB summary mask from port ``0x55``."""

    return (~_byte(value, "port 0x55 status")) & 0x1F
