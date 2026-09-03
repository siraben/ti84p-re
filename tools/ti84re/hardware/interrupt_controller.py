"""Reusable decoders for the TI-84 Plus legacy interrupt controller.

Ports ``0x03`` and ``0x04`` share interrupt-mask, acknowledgement, status,
timer-rate, memory-map, battery-selector, and low-power controls.  This module
models the public bit contract and the dispatch order visible in OS 2.55MP.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
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
MAME_STANDARD_TIMER_RATES = (256, 512)


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
            name for bit, name in LEGACY_SOURCE_BITS.items() if self.raw & (1 << bit)
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
            name for bit, name in LEGACY_SOURCE_BITS.items() if self.raw & (1 << bit)
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
    return tuple(names[bit] for bit in ROM_STATUS_TEST_BITS if status & (1 << bit))


def usb_active_low_sources(value: int) -> int:
    """Return the active low-five-bit USB summary mask from port ``0x55``."""

    return (~_byte(value, "port 0x55 status")) & 0x1F


@dataclass(frozen=True)
class MameLegacyInterruptState:
    """Model MAME 0.287's TI-84 Plus legacy interrupt fields.

    This is an emulator-source model, not the public ASIC contract.  MAME
    stores the ON mask separately from timer-mask bits 1-2, exposes status from
    both ports ``0x03`` and ``0x04``, and treats a port-``0x02`` write as a
    direct overwrite of the three pending fields.
    """

    on_mask: bool = False
    timer_mask: int = 0
    on_pending: bool = False
    timer_pending: int = 0
    programmable_pending: int = 0
    on_pressed: bool = False

    def __post_init__(self) -> None:
        _byte(self.timer_mask, "MAME timer mask")
        _byte(self.timer_pending, "MAME timer pending")
        _byte(self.programmable_pending, "MAME programmable pending")
        if self.timer_mask & ~0x06:
            raise ValueError("MAME timer mask may contain only bits 1-2")
        if self.timer_pending & ~0x06:
            raise ValueError("MAME timer pending may contain only bits 1-2")
        if self.programmable_pending & ~0xE0:
            raise ValueError("MAME programmable pending may contain only bits 5-7")

    @property
    def status(self) -> int:
        """Return MAME's shared port-``0x03``/``0x04`` status byte."""

        return (
            int(self.on_pending)
            | self.timer_pending
            | (0 if self.on_pressed else 0x08)
            | self.programmable_pending
        )

    def write_port02(self, value: int) -> MameLegacyInterruptState:
        """Apply MAME's direct pending-field write at port ``0x02``."""

        value = _byte(value, "port 0x02 write")
        return replace(
            self,
            on_pending=bool(value & 0x01),
            timer_pending=value & 0x06,
        )

    def write_port03(self, value: int) -> MameLegacyInterruptState:
        """Apply MAME's three-bit mask and clear-on-zero behavior."""

        value = _byte(value, "port 0x03 write")
        on_mask = bool(value & 0x01)
        timer_mask = value & 0x06
        return replace(
            self,
            on_mask=on_mask,
            timer_mask=timer_mask,
            on_pending=self.on_pending and on_mask,
            timer_pending=self.timer_pending & timer_mask,
        )

    def sample_on(self, pressed: bool) -> MameLegacyInterruptState:
        """Apply the press-only edge logic in MAME's timer-1 callback."""

        edge = pressed and not self.on_pressed
        return replace(
            self,
            on_pending=self.on_pending or (edge and self.on_mask),
            on_pressed=pressed,
        )

    def standard_timer_tick(self, timer: int) -> MameLegacyInterruptState:
        """Apply one enabled fixed-rate standard-timer callback."""

        if timer not in (1, 2):
            raise ValueError("MAME standard timer must be 1 or 2")
        bit = 1 << timer
        pending = self.timer_pending | (bit if self.timer_mask & bit else 0)
        return replace(self, timer_pending=pending)

    def soft_reset(self) -> MameLegacyInterruptState:
        """Return MAME's retained fields across the TI-83 Plus reset hook."""

        return self


@dataclass(frozen=True)
class TilemLegacyInterruptState:
    """Model pinned TilEm's TI-84 Plus legacy interrupt policy.

    This state uses the port-``0x04`` bit layout for pending sources.  TilEm's
    internal link interrupt uses another bit, but the distinction is not
    observable through the legacy status port.  Reset intentionally exposes
    TilEm's port-``0x03`` readback/internal-enable mismatch.
    """

    port03: int = 0x0B
    on_enabled: bool = False
    keep_power_during_halt: bool = True
    link_activity_enabled: bool = False
    legacy_pending: int = 0
    programmable_finished: int = 0
    on_pressed: bool = False
    user_timer_no_halt_interrupt: bool = False

    def __post_init__(self) -> None:
        _byte(self.port03, "TilEm port 0x03")
        _byte(self.legacy_pending, "TilEm legacy pending status")
        _byte(self.programmable_finished, "TilEm programmable status")
        if self.legacy_pending & ~LEGACY_SOURCE_MASK:
            raise ValueError("TilEm legacy pending status has unknown bits")
        if self.programmable_finished & ~0xE0:
            raise ValueError("TilEm programmable status may contain only bits 5-7")

    @property
    def status(self) -> int:
        """Return TilEm's port-``0x04`` status byte."""

        return (
            self.legacy_pending
            | (0 if self.on_pressed else 0x08)
            | self.programmable_finished
        )

    def write_port02(self, value: int) -> TilemLegacyInterruptState:
        """Apply TilEm's clear-on-zero legacy acknowledgement."""

        value = _byte(value, "port 0x02 write")
        return replace(
            self,
            legacy_pending=self.legacy_pending & value & LEGACY_SOURCE_MASK,
        )

    def write_port03(self, value: int) -> TilemLegacyInterruptState:
        """Apply TilEm's mask, acknowledgement, link, power, and HALT policy."""

        value = _byte(value, "port 0x03 write")
        return replace(
            self,
            port03=value,
            on_enabled=bool(value & 0x01),
            keep_power_during_halt=bool(value & 0x08),
            link_activity_enabled=bool(value & 0x10),
            legacy_pending=self.legacy_pending & value & LEGACY_SOURCE_MASK,
            user_timer_no_halt_interrupt=not bool(value & 0x06),
        )

    def sample_on(self, pressed: bool) -> TilemLegacyInterruptState:
        """Latch either ON transition when TilEm's internal enable is set."""

        changed = pressed != self.on_pressed
        pending = self.legacy_pending
        if changed and self.on_enabled:
            pending |= 0x01
        return replace(self, legacy_pending=pending, on_pressed=pressed)

    def standard_timer_tick(self, timer: int) -> TilemLegacyInterruptState:
        """Apply one of TilEm's three standard-timer callbacks."""

        if timer not in (1, 2):
            raise ValueError("TilEm standard timer must be 1 or 2")
        bit = 1 << timer
        pending = self.legacy_pending | (bit if self.port03 & bit else 0)
        return replace(self, legacy_pending=pending)

    def link_transition(self, *, visible: bool = True) -> TilemLegacyInterruptState:
        """Apply one external-line transition visible past driven outputs."""

        pending = self.legacy_pending
        if visible and self.link_activity_enabled:
            pending |= 0x10
        return replace(self, legacy_pending=pending)

    def soft_reset(self) -> TilemLegacyInterruptState:
        """Apply TilEm's reset ordering while retaining the power policy."""

        return TilemLegacyInterruptState(
            keep_power_during_halt=self.keep_power_during_halt,
        )
