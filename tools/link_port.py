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


@dataclass(frozen=True)
class HandshakePhase:
    """One externally visible phase of a raw link-bit transfer."""

    name: str
    sender_drive: int
    receiver_drive: int
    high_lines: int

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
