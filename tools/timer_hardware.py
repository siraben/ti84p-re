"""Reusable programmable-timer, ROM timer, and RTC comparison models.

The documented profile encodes the public port contract.  Emulator profiles
encode pinned upstream source and are debugging oracles for those revisions,
not physical-ASIC claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


CRYSTAL_HZ = 32_768
DOCUMENTED_CRYSTAL_DIVISORS = (3, 33, 328, 3277, 1, 16, 256, 4096)
WABBIT_MAME_CRYSTAL_DIVISORS = (3, 32, 327, 3276, 1, 16, 256, 4096)


def _byte(value: int, name: str) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be a byte")
    return value


def _word(value: int, name: str) -> int:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"{name} must be a word")
    return value


def _positive(value: int, name: str) -> int:
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class TimerImplementationProfile:
    """Pinned timer and RTC characteristics for one source model."""

    name: str
    revision: str
    source_model: str
    mode3_model: str
    scheduler_model: str
    expiry_model: str
    halt_model: str
    rtc_ports: bool
    rtc_source: str
    rtc_disabled_read: str
    driver_status: str


TIMER_IMPLEMENTATION_PROFILES = (
    TimerImplementationProfile(
        name="Documented",
        revision="public port contract",
        source_model="32.768 kHz crystal or divided CPU clock",
        mode3_model="CPU source with speed-selected port-0x2F prescaler",
        scheduler_model="counter zero represents 256 recurring ticks",
        expiry_model="bit 1 enables interrupts; completion is independent",
        halt_model="published tests report unreliable HALT wake",
        rtc_ports=True,
        rtc_source="ASIC seconds counter from the RTC clock domain",
        rtc_disabled_read="zero, according to the public port report",
        driver_status="physical edge behavior still needs TA2/TA3 tests",
    ),
    TimerImplementationProfile(
        name="TilEm",
        revision="f56ad637d0524ee841dd381be6ecbaf5b8975600",
        source_model="documented crystal divisors and divided CPU clock",
        mode3_model="same decode as ordinary CPU mode; port 0x2F ignored",
        scheduler_model="exact CPU cycles or rounded crystal microseconds",
        expiry_model="separate internal completion and visible overflow flags",
        halt_model="suppresses HALT interrupt unless a standard timer is enabled",
        rtc_ports=True,
        rtc_source="host time_t plus a stored offset",
        rtc_disabled_read="frozen stored count",
        driver_status="TI-84 Plus model used for dynamic traces",
    ),
    TimerImplementationProfile(
        name="Wabbitemu",
        revision="48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422",
        source_model="crystal divisors 3/32/327/3276/... or divided CPU clock",
        mode3_model="same decode as ordinary CPU mode; port 0x2F ignored",
        scheduler_model="crystal path catches up once per handler; CPU path loops",
        expiry_model="bit 2 reports first underflow; bit 1 enables interrupts",
        halt_model="retains generation but suppresses the CPU interrupt in HALT",
        rtc_ports=True,
        rtc_source="emulated elapsed seconds plus a stored base",
        rtc_disabled_read="frozen stored base",
        driver_status="source model; no physical timing claim",
    ),
    TimerImplementationProfile(
        name="MAME",
        revision="mame0287",
        source_model="all nonzero values use 32.768 kHz and low-three-bit divisor",
        mode3_model="ports 0x2D and 0x2F are unmapped",
        scheduler_model="first decrement is scheduled at zero delay",
        expiry_model="bit 1 suppresses interrupts and loop bit 0 is discarded",
        halt_model="no programmable-timer-specific HALT suppression",
        rtc_ports=False,
        rtc_source="unimplemented; ports 0x40-0x48 are unmapped",
        rtc_disabled_read="not applicable",
        driver_status="TI-84 Plus driver is MACHINE_NOT_WORKING",
    ),
)


def timer_implementation_profile(name: str) -> TimerImplementationProfile:
    """Return a source profile by case-insensitive name."""

    normalized = name.casefold()
    aliases = {"hardware": "documented", "public": "documented"}
    normalized = aliases.get(normalized, normalized)
    for profile in TIMER_IMPLEMENTATION_PROFILES:
        if profile.name.casefold() == normalized:
            return profile
    choices = ", ".join(profile.name for profile in TIMER_IMPLEMENTATION_PROFILES)
    raise ValueError(f"unknown timer profile {name!r}; choose {choices}")


def _cpu_divisor(value: int) -> int:
    """Decode the highest selected divisor bit used by TilEm and Wabbitemu."""

    for bit, divisor in (
        (0x20, 64),
        (0x10, 32),
        (0x08, 16),
        (0x04, 8),
        (0x02, 4),
        (0x01, 2),
    ):
        if value & bit:
            return divisor
    return 1


@dataclass(frozen=True)
class TimerSource:
    """Decoded source register and exact nominal tick rate."""

    profile: str
    value: int
    family: str
    source_hz: int
    divisor: int
    tick_hz: Fraction
    tick_period_seconds: Fraction
    port2f_prescaler_applied: bool
    note: str


def decode_timer_source(
    profile: str,
    value: int,
    *,
    cpu_hz: int = 15_000_000,
    mode3_prescaler: int = 1,
) -> TimerSource | None:
    """Decode one source byte under the public or a pinned emulator model.

    ``mode3_prescaler`` is the speed-selected port-``0x2F`` field plus one.
    Only the documented profile applies it; all three emulators ignore that
    register for programmable timers.
    """

    implementation = timer_implementation_profile(profile)
    value = _byte(value, "source")
    cpu_hz = _positive(cpu_hz, "CPU frequency")
    if not 1 <= mode3_prescaler <= 8:
        raise ValueError("mode-3 prescaler must be between 1 and 8")

    normalized = implementation.name.casefold()
    family_bits = value & 0xC0
    if normalized == "mame":
        if value == 0:
            return None
        divisor = WABBIT_MAME_CRYSTAL_DIVISORS[value & 0x07]
        family = "mame_fixed_crystal"
        source_hz = CRYSTAL_HZ
        note = "MAME ignores the clock-family bits for every nonzero value"
        applied = False
    elif family_bits == 0:
        return None
    elif family_bits == 0x40:
        table = (
            WABBIT_MAME_CRYSTAL_DIVISORS
            if normalized == "wabbitemu"
            else DOCUMENTED_CRYSTAL_DIVISORS
        )
        divisor = table[value & 0x07]
        family = "crystal"
        source_hz = CRYSTAL_HZ
        note = "32.768 kHz crystal family"
        applied = False
    else:
        divisor = _cpu_divisor(value)
        family = "cpu_prescaled" if family_bits == 0xC0 else "cpu"
        source_hz = cpu_hz
        applied = normalized == "documented" and family_bits == 0xC0
        if applied:
            divisor *= mode3_prescaler
            note = "CPU divisor multiplied by the selected port-0x2F prescaler"
        elif family_bits == 0xC0:
            note = "emulator treats mode 3 like ordinary divided-CPU mode"
        else:
            note = "divided CPU-clock family"

    tick_hz = Fraction(source_hz, divisor)
    return TimerSource(
        profile=implementation.name,
        value=value,
        family=family,
        source_hz=source_hz,
        divisor=divisor,
        tick_hz=tick_hz,
        tick_period_seconds=1 / tick_hz,
        port2f_prescaler_applied=applied,
        note=note,
    )


@dataclass(frozen=True)
class TimerDuration:
    """Nominal first-expiry timing for one counter write."""

    profile: str
    source: int
    counter: int
    effective_counter_ticks: int
    scheduled_periods_to_expiry: int | None
    expires: bool
    duration_seconds: Fraction | None
    note: str


def timer_duration(
    profile: str,
    source: int,
    counter: int,
    *,
    cpu_hz: int = 15_000_000,
    mode3_prescaler: int = 1,
) -> TimerDuration:
    """Return exact nominal timing, including each source scheduler's edges."""

    implementation = timer_implementation_profile(profile)
    counter = _byte(counter, "counter")
    decoded = decode_timer_source(
        profile,
        source,
        cpu_hz=cpu_hz,
        mode3_prescaler=mode3_prescaler,
    )
    if decoded is None:
        return TimerDuration(
            implementation.name,
            source,
            counter,
            256 if counter == 0 else counter,
            None,
            False,
            None,
            "source is off",
        )

    effective_ticks = 256 if counter == 0 else counter
    if implementation.name == "MAME":
        if counter == 0:
            return TimerDuration(
                implementation.name,
                source,
                counter,
                effective_ticks,
                None,
                False,
                None,
                "MAME's callback does not decrement a zero counter",
            )
        periods = counter - 1
        note = "MAME schedules the first decrement at zero delay"
        duration = decoded.tick_period_seconds * periods
    elif implementation.name == "TilEm" and decoded.family == "crystal":
        periods = effective_ticks
        microseconds = (
            decoded.divisor * 1_000_000 * effective_ticks + CRYSTAL_HZ // 2
        ) // CRYSTAL_HZ
        duration = Fraction(microseconds, 1_000_000)
        note = "TilEm rounds the complete crystal duration to microseconds"
    else:
        periods = effective_ticks
        duration = decoded.tick_period_seconds * periods
        note = (
            "nominal periods; Wabbitemu crystal delivery also depends on handler calls"
            if implementation.name == "Wabbitemu" and decoded.family == "crystal"
            else "nominal source periods"
        )
    return TimerDuration(
        implementation.name,
        source,
        counter,
        effective_ticks,
        periods,
        True,
        duration,
        note,
    )


@dataclass(frozen=True)
class TimerExpiry:
    """One modeled expiry under a public or emulator callback contract."""

    profile: str
    mode_written: int
    counter: int
    event_occurs: bool
    completion_visible: bool
    status_bit2: bool
    interrupt_generated: bool | None
    running_after_expiry: bool
    counter_reloaded: bool
    mode_read_after_expiry: int
    note: str


def timer_expiry(
    profile: str,
    mode: int,
    *,
    counter: int = 1,
    already_completed: bool = False,
    halted: bool = False,
    standard_timer_enabled: bool = True,
) -> TimerExpiry:
    """Model one expiry without claiming that emulator policy is hardware."""

    implementation = timer_implementation_profile(profile)
    mode = _byte(mode, "mode") & 0x03
    counter = _byte(counter, "counter")
    loop = bool(mode & 0x01)
    interrupt_enable = bool(mode & 0x02)
    name = implementation.name

    if name == "MAME" and counter == 0:
        return TimerExpiry(
            name, mode, counter, False, False, False, False, True, False, mode,
            "MAME leaves a zero counter idle while its periodic callback runs",
        )
    if name in {"Documented", "TilEm"} and counter == 0:
        return TimerExpiry(
            name, mode, counter, True, False, False, False, True, True, mode,
            "counter zero recurs as 256 ticks without completion",
        )

    if name == "MAME":
        completion = not interrupt_enable
        generated: bool | None = not interrupt_enable
        resulting_mode = mode & 0x02
        return TimerExpiry(
            name,
            mode,
            counter,
            True,
            completion,
            False,
            generated,
            loop,
            loop,
            resulting_mode,
            "MAME uses inverted interrupt polarity and clears loop bit 0",
        )

    completion = True
    running = loop
    if name == "Wabbitemu":
        status_bit2 = True
        generated = interrupt_enable and not halted
        note = "interrupt generation remains pending while HALT suppresses assertion"
    elif name == "TilEm":
        status_bit2 = already_completed
        generated = interrupt_enable and (
            not halted or standard_timer_enabled
        )
        note = "second unacknowledged expiry sets visible overflow bit 2"
    else:
        status_bit2 = already_completed
        generated = None if halted and interrupt_enable else interrupt_enable
        note = "HALT assertion is left unknown pending physical tests" if (
            halted and interrupt_enable
        ) else "public mode and completion contract"
    resulting_mode = mode | (0x04 if status_bit2 else 0)
    return TimerExpiry(
        name,
        mode,
        counter,
        True,
        completion,
        status_bit2,
        generated,
        running,
        loop,
        resulting_mode,
        note,
    )


def rom_timer_ticks(duration: int) -> int:
    """Decode the OS 2.55MP timer API's radix-255 ``DE`` duration."""

    duration = _word(duration, "duration")
    return 255 * (duration >> 8) + (duration & 0xFF)


def rom_timer_chunks(duration: int) -> tuple[int, ...]:
    """Return the successive hardware counter values programmed by the ROM."""

    duration = _word(duration, "duration")
    full_chunks, final = divmod(duration, 0x100)
    return (255,) * full_chunks + ((final,) if final else ())
