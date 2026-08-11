"""Reusable USB register, event, and pinned-emulator comparison helpers.

The FDRC names come from Mentor's published register header and remain a
controller-family hypothesis for the TI ASIC.  Emulator profiles reproduce
the named source revisions; they are not physical USB models.
"""

from __future__ import annotations

from dataclasses import dataclass


FDRC_BASE = 0x80
FDRC_REGISTER_NAMES = (
    ("FADDR",),
    ("POWER",),
    ("INTRTX1",),
    ("INTRTX2",),
    ("INTRRX1",),
    ("INTRRX2",),
    ("INTRUSB",),
    ("INTRTX1E",),
    ("INTRTX2E",),
    ("INTRRX1E",),
    ("INTRRX2E",),
    ("INTRUSBE",),
    ("FRAME1",),
    ("FRAME2",),
    ("INDEX",),
    ("DEVCTL",),
    ("TXMAXP",),
    ("CSR0", "TXCSR1"),
    ("CSR02", "TXCSR2"),
    ("RXMAXP",),
    ("RXCSR1",),
    ("RXCSR2",),
    ("COUNT0", "RXCOUNT1"),
    ("RXCOUNT2",),
    ("TXTYPE",),
    ("TXINTERVAL", "NAKLIMIT0"),
    ("RXTYPE",),
    ("RXINTERVAL",),
    ("TXFIFO1",),
    ("TXFIFO2",),
    ("RXFIFO1",),
    ("RXFIFO2", "FIFOSIZE", "CONFIGDATA"),
)

FDRC_POWER_BITS = {
    0: "ENSUSPEND",
    1: "SUSPENDM",
    2: "RESUME",
    3: "RESET",
    4: "VBUSLO",
    5: "VBUSSESS",
    6: "VBUSVAL",
    7: "ISOUP",
}
FDRC_INTERRUPT_BITS = {
    0: "SUSPEND",
    1: "RESUME",
    2: "RESET/BABBLE",
    3: "SOF",
    4: "CONNECT",
    5: "DISCONNECT",
    6: "SESSION_REQUEST",
    7: "VBUS_ERROR",
}
FDRC_DEVCTL_BITS = {
    0: "SESSION",
    1: "HOST_REQUEST",
    2: "HOST_MODE",
    5: "LOW_SPEED_DEVICE",
    6: "FULL_SPEED_DEVICE",
    7: "B_DEVICE",
}

MAIN_USB_EVENT_TARGETS = {
    1: "35:4031 alternate setup",
    4: "35:4B6A line/event settle",
    5: "35:4B9F event clear/re-arm",
    6: "35:40B2 USB setup",
    7: "35:4C14 cleanup/reset",
}
BOOT_USB_EVENT_PRIORITY = (
    (5, "line-state cleanup and wait"),
    (4, "line-state cleanup and wait"),
    (6, "_InitUSB"),
    (7, "common error exit"),
)


def _byte(value: int, name: str) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be a byte")
    return value


@dataclass(frozen=True)
class FdrcRegister:
    """One Mentor FDRC register hypothesis at a TI I/O port."""

    port: int
    offset: int
    names: tuple[str, ...]
    endpoint: int | None
    indexed_role: bool
    evidence: str


def fdrc_register(port: int) -> FdrcRegister | None:
    """Map a TI port to the corresponding Mentor FDRC offset or FIFO."""

    port = _byte(port, "port")
    offset = port - FDRC_BASE
    if 0 <= offset < len(FDRC_REGISTER_NAMES):
        return FdrcRegister(
            port=port,
            offset=offset,
            names=FDRC_REGISTER_NAMES[offset],
            endpoint=None,
            indexed_role=0x10 <= offset <= 0x1F,
            evidence="Mentor FDRC offset match; TI controller identity is a hypothesis",
        )
    if 0x20 <= offset <= 0x2F:
        endpoint = offset - 0x20
        return FdrcRegister(
            port=port,
            offset=offset,
            names=(f"FIFO{endpoint}",),
            endpoint=endpoint,
            indexed_role=False,
            evidence="Mentor non-AHB FIFO offset; ROM confirms TI FIFOs 0-2",
        )
    return None


def decode_fdrc_bits(port: int, value: int) -> tuple[str, ...]:
    """Decode imported Mentor bit names for unambiguous global registers."""

    port = _byte(port, "port")
    value = _byte(value, "value")
    if port == 0x81:
        names = FDRC_POWER_BITS
    elif port in {0x86, 0x8B}:
        names = FDRC_INTERRUPT_BITS
    elif port == 0x8F:
        names = FDRC_DEVCTL_BITS
    else:
        raise ValueError("bit decoding is available for ports 0x81, 0x86, 0x8B, and 0x8F")
    return tuple(name for bit, name in names.items() if value & (1 << bit))


@dataclass(frozen=True)
class UsbLineState:
    """Decoded paired-state byte used by Wabbitemu ports ``0x4D``/``0x56``."""

    value: int
    d_plus: str
    d_minus: str
    id: str
    vbus: str


def _paired_state(value: int, low_bit: int, high_bit: int) -> str:
    low = bool(value & (1 << low_bit))
    high = bool(value & (1 << high_bit))
    if low and high:
        return "both"
    if low:
        return "low"
    if high:
        return "high"
    return "neither"


def decode_usb_line_state(value: int) -> UsbLineState:
    """Decode Wabbitemu's D+/D-/ID/VBUS low/high bit pairs."""

    value = _byte(value, "line state")
    return UsbLineState(
        value=value,
        d_plus=_paired_state(value, 0, 1),
        d_minus=_paired_state(value, 2, 3),
        id=_paired_state(value, 4, 5),
        vbus=_paired_state(value, 7, 6),
    )


def usb_active_low_summary_bits(value: int) -> tuple[int, ...]:
    """Return active low-five-bit USB summary positions from port ``0x55``."""

    value = _byte(value, "USB summary")
    return tuple(bit for bit in range(5) if not value & (1 << bit))


def main_usb_event_targets(value: int) -> tuple[str, ...]:
    """Return every page-35 target selected by set port-``0x56`` bits."""

    value = _byte(value, "USB events")
    return tuple(
        target for bit, target in MAIN_USB_EVENT_TARGETS.items() if value & (1 << bit)
    )


def boot_usb_event_action(value: int) -> str:
    """Apply `_AttemptUSBOSReceive`'s event-bit priority."""

    value = _byte(value, "USB events")
    for bit, action in BOOT_USB_EVENT_PRIORITY:
        if value & (1 << bit):
            return action
    return "inspect port 0x4D and choose setup path"


@dataclass(frozen=True)
class LinkAssistRate:
    """Historical link-assist rate-field decode for ports ``0x09``–``0x0C``."""

    value: int
    divisor_field: int
    divisor: int | None
    halted: bool
    inter_bit_wait: int


def decode_link_assist_rate(value: int) -> LinkAssistRate:
    """Decode the public divisor/wait interpretation without asserting timing."""

    value = _byte(value, "assist rate")
    field = value >> 5
    halted = field == 7
    return LinkAssistRate(
        value=value,
        divisor_field=field,
        divisor=None if halted else 1 << field,
        halted=halted,
        inter_bit_wait=value & 0x1F,
    )


@dataclass(frozen=True)
class UsbEmulatorProfile:
    """Pinned USB coverage and reset/disconnected values."""

    name: str
    revision: str
    mapped_ports: tuple[int, ...]
    initial_reads: tuple[tuple[int, int], ...]
    controller_model: str
    known_limit: str
    driver_status: str


USB_EMULATOR_PROFILES = (
    UsbEmulatorProfile(
        name="TilEm",
        revision="f56ad637d0524ee841dd381be6ecbaf5b8975600",
        mapped_ports=(0x4C, 0x4D, 0x55, 0x56, 0x57),
        initial_reads=((0x4C, 0x22), (0x4D, 0xA5), (0x55, 0x1F), (0x56, 0), (0x57, 0x50)),
        controller_model="fixed disconnected reads",
        known_limit="no controller/endpoint write cases",
        driver_status="TI-84 Plus model used for disconnected traces",
    ),
    UsbEmulatorProfile(
        name="Wabbitemu",
        revision="48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422",
        mapped_ports=(0x4A, 0x4C, 0x4D, 0x55, 0x56, 0x57, 0x5B, 0x80),
        initial_reads=((0x4A, 0x04), (0x4C, 0x22), (0x4D, 0xA5), (0x55, 0x1F), (0x56, 0x50), (0x57, 0), (0x5B, 0), (0x80, 0)),
        controller_model="paired line/event state plus device-address latch",
        known_limit="port 0x54 is unreachable after duplicate port-0x55 registration",
        driver_status="source labels this block Fake USB",
    ),
    UsbEmulatorProfile(
        name="MAME",
        revision="mame0287",
        mapped_ports=(0x55, 0x56),
        initial_reads=((0x55, 0x1F), (0x56, 0)),
        controller_model="fixed disconnected interrupt reads",
        known_limit="ports 0x4A-0x5B except 0x55/0x56 and 0x80-0xA2 are unmapped",
        driver_status="TI-84 Plus driver is MACHINE_NOT_WORKING",
    ),
)


def usb_emulator_profile(name: str) -> UsbEmulatorProfile:
    """Return a pinned profile by case-insensitive emulator name."""

    normalized = name.casefold()
    for profile in USB_EMULATOR_PROFILES:
        if profile.name.casefold() == normalized:
            return profile
    choices = ", ".join(profile.name for profile in USB_EMULATOR_PROFILES)
    raise ValueError(f"unknown USB emulator {name!r}; choose {choices}")


def emulator_initial_usb_read(emulator: str, port: int) -> int | None:
    """Return a pinned reset/disconnected read, or ``None`` if not modeled."""

    profile = usb_emulator_profile(emulator)
    port = _byte(port, "port")
    return dict(profile.initial_reads).get(port)


@dataclass(frozen=True)
class WabbitemuPort4AResult:
    """Exact state effects of Wabbitemu's port-``0x4A`` write handler."""

    written: int
    stored_port4a: int
    line_state_before: int
    line_state_after: int
    events_before: int
    events_after: int
    line_interrupt: bool


def wabbitemu_port4a_write(
    value: int, *, line_state: int = 0xA5, events: int = 0x50
) -> WabbitemuPort4AResult:
    """Reproduce the pinned Fake USB port-``0x4A`` write side effects."""

    value = _byte(value, "port 0x4A value")
    line_state = _byte(line_state, "line state")
    events = _byte(events, "events")
    new_state = line_state
    new_events = events
    interrupt = False
    if value & 0x08:
        if not line_state & 0x08:
            new_events = (events | 0x08) & ~0x04
            interrupt = True
        new_state |= 0x40
    return WabbitemuPort4AResult(
        written=value,
        stored_port4a=value & 0x38,
        line_state_before=line_state,
        line_state_after=new_state,
        events_before=events,
        events_after=new_events,
        line_interrupt=interrupt,
    )
