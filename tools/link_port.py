"""Reusable model of the TI two-wire link port and byte handshake.

Drive-mask bits describe outputs: a set bit means that endpoint pulls the
corresponding line low.  Read-mask bits describe physical levels: a set bit
means that line is high.  The deliberately neutral names ``line 0`` and
``line 1`` avoid assuming a connector-contact mapping in analysis code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import reduce
from operator import or_
from typing import Iterable


LINE_MASK = 0x03
NOMINAL_LOW_SPEED_HZ = 6_000_000


@dataclass(frozen=True)
class LinkPortImplementationProfile:
    """One public contract or pinned emulator's raw-link coverage."""

    key: str
    name: str
    revision: str
    write_model: str
    reset_state: int
    mapped_assist_ports: tuple[int, ...]
    advertises_assist: bool
    assist_operational: bool
    raw_activity_interrupt: bool
    driver_status: str
    known_limit: str


DOCUMENTED_LINK_PROFILE = LinkPortImplementationProfile(
    key="documented",
    name="Public digital contract",
    revision="TI Link Protocol Guide and historical WikiTI description",
    write_model="low-two-bit open-collector",
    reset_state=0,
    mapped_assist_ports=(),
    advertises_assist=False,
    assist_operational=False,
    raw_activity_interrupt=True,
    driver_status="reference contract; not an implementation",
    known_limit="does not establish analog levels, timing, or ASIC reset behavior",
)

TILEM_LINK_PROFILE = LinkPortImplementationProfile(
    key="tilem",
    name="TilEm",
    revision="f56ad637d0524ee841dd381be6ecbaf5b8975600",
    write_model="low-two-bit open-collector",
    reset_state=0,
    mapped_assist_ports=(0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D),
    advertises_assist=True,
    assist_operational=True,
    raw_activity_interrupt=True,
    driver_status="usable raw and link-assist model",
    known_limit="digital model only; assist timing includes implementation policy",
)

WABBITEMU_LINK_PROFILE = LinkPortImplementationProfile(
    key="wabbitemu",
    name="Wabbitemu",
    revision="48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422",
    write_model="low-two-bit open-collector",
    reset_state=0,
    mapped_assist_ports=(0x08, 0x09, 0x0A, 0x0D),
    advertises_assist=True,
    assist_operational=True,
    raw_activity_interrupt=False,
    driver_status="usable raw and link-assist model with source-level quirks",
    known_limit=(
        "disconnected peer aliases the local latch; link_disconnect leaves a null "
        "client pointer"
    ),
)

MAME_LINK_PROFILE = LinkPortImplementationProfile(
    key="mame",
    name="MAME",
    revision="mame0287",
    write_model="TI-Plus PCR latch with mismatched connector control bits",
    reset_state=0,
    mapped_assist_ports=(0x09,),
    advertises_assist=True,
    assist_operational=False,
    raw_activity_interrupt=False,
    driver_status="MACHINE_NOT_WORKING driver",
    known_limit=(
        "normal writes update readback but release the connector; assist is "
        "advertised while its control/data ports are absent"
    ),
)

LINK_PORT_PROFILES = {
    profile.key: profile
    for profile in (
        DOCUMENTED_LINK_PROFILE,
        TILEM_LINK_PROFILE,
        WABBITEMU_LINK_PROFILE,
        MAME_LINK_PROFILE,
    )
}
LINK_EMULATOR_PROFILE_KEYS = ("tilem", "wabbitemu", "mame")


def link_port_profile(
    profile: str | LinkPortImplementationProfile,
) -> LinkPortImplementationProfile:
    """Resolve a profile key or return an already-resolved profile."""

    if isinstance(profile, LinkPortImplementationProfile):
        return profile
    try:
        return LINK_PORT_PROFILES[profile.lower()]
    except KeyError:
        choices = ", ".join(LINK_PORT_PROFILES)
        raise ValueError(f"unknown link profile {profile!r}; choose {choices}") from None


@dataclass(frozen=True)
class HandshakePhase:
    """One externally visible phase of a raw link-bit transfer."""

    name: str
    sender_drive: int
    receiver_drive: int
    high_lines: int

    def as_dict(self) -> dict[str, int | str]:
        return asdict(self)


@dataclass(frozen=True)
class LinkPortWriteResult:
    """State and externally visible result of one emulator port-0 write."""

    profile: str
    write_value: int
    state_before: int
    state_after: int
    local_latch: int
    connector_drive: int
    peer_drive: int
    port_read: int

    def as_dict(self) -> dict[str, int | str]:
        return asdict(self)


def _line_mask(value: int, *, name: str) -> int:
    if not 0 <= value <= LINE_MASK:
        raise ValueError(f"{name} must be between 0 and 3")
    return value


def byte(value: int, *, name: str = "value") -> int:
    """Validate and return an unsigned byte."""

    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be between 0 and 255")
    return value


def drive_mask(write_value: int) -> int:
    """Return the two output bits latched by a port-0 write."""

    return byte(write_value, name="write value") & LINE_MASK


def physical_high_mask(*endpoint_drives: int) -> int:
    """Resolve open-collector endpoint drives into the physical line levels."""

    drives = (
        _line_mask(value, name=f"endpoint drive {index}")
        for index, value in enumerate(endpoint_drives)
    )
    pulled_low = reduce(or_, drives, 0)
    return (~pulled_low) & LINE_MASK


def port_read_value(local_drive: int, peer_drive: int) -> int:
    """Model a port-0 read, including the local output latch in bits 4-5."""

    local = _line_mask(local_drive, name="local drive")
    peer = _line_mask(peer_drive, name="peer drive")
    return physical_high_mask(local, peer) | (local << 4)


def mame_plus_state_after_write(write_value: int, prior_state: int = 0) -> int:
    """Apply MAME 0.287's ``ti8x_plus_serial_w`` PCR assignment."""

    value = byte(write_value, name="write value")
    prior = byte(prior_state, name="prior PCR state")
    return (prior & 0xC8) | (value & 0x04) | ((value << 4) & 0x30)


def mame_plus_connector_drive(write_value: int) -> int:
    """Return lines MAME drives low through its connector callbacks."""

    value = byte(write_value, name="write value")
    tip_low = bool(value & 0x04) and bool(value & 0x10)
    ring_low = bool(value & 0x08) and bool(value & 0x20)
    return int(tip_low) | (int(ring_low) << 1)


def mame_plus_port_read(pcr_state: int, peer_drive: int = 0) -> int:
    """Apply MAME 0.287's TI-Plus raw serial read expression."""

    pcr = byte(pcr_state, name="PCR state")
    peer = _line_mask(peer_drive, name="peer drive")
    tip_in = 0x02 if peer & 1 else 0x03
    ring_in = 0x01 if peer & 2 else 0x03
    inputs = (~(pcr >> 4) & 0xFF) & tip_in & ring_in
    return inputs | (pcr & 0xFC)


def emulator_port_write(
    profile: str | LinkPortImplementationProfile,
    write_value: int,
    *,
    prior_state: int | None = None,
    peer_drive: int = 0,
) -> LinkPortWriteResult:
    """Apply one raw port write and calculate readback and connector output."""

    selected = link_port_profile(profile)
    value = byte(write_value, name="write value")
    peer = _line_mask(peer_drive, name="peer drive")
    before = selected.reset_state if prior_state is None else byte(
        prior_state, name="prior state"
    )
    if selected.key == "mame":
        after = mame_plus_state_after_write(value, before)
        latch = (after >> 4) & LINE_MASK
        connector = mame_plus_connector_drive(value)
        read = mame_plus_port_read(after, peer)
    else:
        after = drive_mask(value)
        latch = after
        connector = after
        read = port_read_value(after, peer)
    return LinkPortWriteResult(
        profile=selected.key,
        write_value=value,
        state_before=before,
        state_after=after,
        local_latch=latch,
        connector_drive=connector,
        peer_drive=peer,
        port_read=read,
    )


def emulator_write_sequence(
    profile: str | LinkPortImplementationProfile,
    write_values: Iterable[int],
    *,
    peer_drive: int = 0,
) -> tuple[LinkPortWriteResult, ...]:
    """Apply a sequence of writes while preserving implementation state."""

    selected = link_port_profile(profile)
    state = selected.reset_state
    results = []
    for value in write_values:
        result = emulator_port_write(
            selected, value, prior_state=state, peer_drive=peer_drive
        )
        results.append(result)
        state = result.state_after
    return tuple(results)


def sender_drive(bit: int) -> int:
    """Return the port-0 drive mask used to transmit one bit."""

    if bit not in (0, 1):
        raise ValueError("bit must be 0 or 1")
    return 1 << bit


def observed_state_to_bit(high_lines: int) -> int:
    """Decode the sender's initial single-low state into a received bit."""

    high = _line_mask(high_lines, name="observed high-line mask")
    if high == 0x02:
        return 0
    if high == 0x01:
        return 1
    raise ValueError("a received bit must begin with exactly one line low")


def receiver_ack_drive(high_lines: int) -> int:
    """Return the receiver drive that pulls the other physical line low."""

    observed_state_to_bit(high_lines)
    return high_lines


def byte_drive_sequence(value: int) -> tuple[int, ...]:
    """Return the eight LSB-first sender drive masks for a byte."""

    value = byte(value)
    return tuple(sender_drive((value >> index) & 1) for index in range(8))


def observed_sequence(value: int) -> tuple[int, ...]:
    """Return the receiver's eight initial high-line masks for a byte."""

    return tuple(physical_high_mask(drive) for drive in byte_drive_sequence(value))


def assemble_observed_byte(high_line_states: Iterable[int]) -> int:
    """Assemble eight LSB-first initial line states into a byte."""

    states = tuple(high_line_states)
    if len(states) != 8:
        raise ValueError("exactly eight line states are required")
    result = 0
    for index, state in enumerate(states):
        result |= observed_state_to_bit(state) << index
    return result


def handshake_phases(bit: int) -> tuple[HandshakePhase, ...]:
    """Return the four transitions used to transfer and acknowledge one bit."""

    send = sender_drive(bit)
    first_high = physical_high_mask(send)
    acknowledge = receiver_ack_drive(first_high)
    values = (
        ("sender-assert", send, 0),
        ("receiver-acknowledge", send, acknowledge),
        ("sender-release", 0, acknowledge),
        ("receiver-release", 0, 0),
    )
    return tuple(
        HandshakePhase(
            name=name,
            sender_drive=sender,
            receiver_drive=receiver,
            high_lines=physical_high_mask(sender, receiver),
        )
        for name, sender, receiver in values
    )


def byte_report(value: int) -> dict[str, object]:
    """Return a JSON-ready description of all eight raw bit handshakes."""

    value = byte(value)
    bits = []
    for index, drive in enumerate(byte_drive_sequence(value)):
        bit_value = (value >> index) & 1
        bits.append(
            {
                "index": index,
                "bit": bit_value,
                "sender_drive": drive,
                "initial_high_lines": physical_high_mask(drive),
                "phases": [phase.as_dict() for phase in handshake_phases(bit_value)],
            }
        )
    return {"value": value, "bit_order": "least-significant first", "bits": bits}


def abort_pulse_delay_tstates(
    *,
    outer_iterations: int = 0xFFFF,
    inner_iterations: int = 4,
    padding_nops: int = 4,
) -> int:
    """Count the delay loop at ``3C:619D`` through ``3C:61AE``.

    The count starts with ``LD HL,0xFFFF`` and ends after the final untaken
    outer ``JR NZ``. It excludes the surrounding calls that change CPU speed,
    assert the link lines, and restore the previous state.
    """

    if outer_iterations <= 0:
        raise ValueError("outer iteration count must be positive")
    if not 1 <= inner_iterations <= 0xFF:
        raise ValueError("inner iteration count must be between 1 and 255")
    if padding_nops < 0:
        raise ValueError("padding NOP count must be nonnegative")

    inner_loop = (
        inner_iterations * 4
        + (inner_iterations - 1) * 12
        + 7
    )
    fixed_outer = 7 + padding_nops * 4 + inner_loop + 6 + 4 + 4
    outer_branches = (outer_iterations - 1) * 12 + 7
    return 10 + outer_iterations * fixed_outer + outer_branches


def abort_pulse_instruction_count(
    *,
    outer_iterations: int = 0xFFFF,
    inner_iterations: int = 4,
    padding_nops: int = 4,
) -> int:
    """Count opcode fetches in the abort delay loop."""

    abort_pulse_delay_tstates(
        outer_iterations=outer_iterations,
        inner_iterations=inner_iterations,
        padding_nops=padding_nops,
    )
    instructions_per_outer = 5 + padding_nops + 2 * inner_iterations
    return 1 + outer_iterations * instructions_per_outer


def abort_pulse_report(
    cpu_hz: int = NOMINAL_LOW_SPEED_HZ,
    *,
    opcode_wait_tstates: int = 1,
) -> dict[str, object]:
    """Return the ROM loop count and nominal wall time for the raw abort pulse."""

    if cpu_hz <= 0:
        raise ValueError("CPU frequency must be positive")
    if opcode_wait_tstates < 0:
        raise ValueError("opcode wait must be nonnegative")
    base_tstates = abort_pulse_delay_tstates()
    opcode_fetches = abort_pulse_instruction_count()
    tstates = base_tstates + opcode_fetches * opcode_wait_tstates
    return {
        "routine": "3C:619D-61AE",
        "outer_iterations": 0xFFFF,
        "inner_iterations": 4,
        "padding_nops": 4,
        "base_tstates": base_tstates,
        "opcode_fetches": opcode_fetches,
        "opcode_wait_tstates_per_fetch": opcode_wait_tstates,
        "delay_tstates": tstates,
        "cpu_hz": cpu_hz,
        "nominal_seconds": tstates / cpu_hz,
        "scope": (
            "delay loop only; surrounding calls and I/O are excluded; the "
            "default one-T-state opcode wait matches the OS mode-0 Flash setup"
        ),
    }
