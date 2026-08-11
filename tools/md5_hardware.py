"""Decode and independently verify TI-84 Plus MD5-assist transactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from hardware_trace import ResolvedIoEvent


MASK32 = 0xFFFFFFFF
MODE_NAMES = {0: "F", 1: "G", 2: "H", 3: "I"}
MD5_PORTS = frozenset(range(0x18, 0x20))


@dataclass(frozen=True)
class Md5ImplementationProfile:
    """One pinned emulator's MD5-assist I/O coverage."""

    key: str
    name: str
    revision: str
    mapped_ports: frozenset[int]
    sliding_operands: bool
    masked_controls: bool
    recompute_on_read: bool
    undefined_operand_reads: int | None
    driver_status: str
    known_limit: str


MD5_IMPLEMENTATIONS = {
    profile.key: profile
    for profile in (
        Md5ImplementationProfile(
            "tilem",
            "TilEm",
            "f56ad637d0524ee841dd381be6ecbaf5b8975600",
            MD5_PORTS,
            True,
            True,
            True,
            0,
            "usable emulator implementation",
            "result is recalculated independently for every byte read",
        ),
        Md5ImplementationProfile(
            "wabbitemu",
            "Wabbitemu",
            "48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422",
            MD5_PORTS,
            True,
            True,
            True,
            0,
            "usable emulator implementation",
            "result is recalculated independently for every byte read",
        ),
        Md5ImplementationProfile(
            "mame",
            "MAME",
            "mame0287",
            frozenset(),
            False,
            False,
            False,
            None,
            "MACHINE_NOT_WORKING TI-84 Plus driver",
            "ports 0x18-0x1F are absent from the I/O map",
        ),
    )
}


def md5_implementation(profile: str) -> Md5ImplementationProfile:
    """Return one pinned emulator profile by case-insensitive key."""

    try:
        return MD5_IMPLEMENTATIONS[profile.lower()]
    except KeyError:
        choices = ", ".join(MD5_IMPLEMENTATIONS)
        raise ValueError(f"unknown MD5 profile {profile!r}; choose {choices}") from None

MD5_EVENT_SEQUENCE = (
    (("OUT", 0x1F),)
    + tuple(("OUT", port) for port in range(0x18, 0x1E) for _ in range(4))
    + (("OUT", 0x1E),)
    + tuple(("IN", port) for port in range(0x1C, 0x20))
)


class Md5TraceError(ValueError):
    """The port stream does not form complete ROM-style MD5 transactions."""


def _word_lsb(events: list[ResolvedIoEvent]) -> int:
    value = 0
    for shift, event in enumerate(events):
        if event.value is None:
            raise Md5TraceError(
                f"unknown byte at instruction {event.instruction_index}"
            )
        value |= event.value << (8 * shift)
    return value


def md5_assist_value(
    mode: int,
    a: int,
    b: int,
    c: int,
    d: int,
    x: int,
    t: int,
    shift: int,
) -> int:
    """Evaluate one 32-bit MD5 round operation independently of TilEm."""

    if mode == 0:
        function = (b & c) | ((~b) & d)
    elif mode == 1:
        function = (b & d) | (c & (~d))
    elif mode == 2:
        function = b ^ c ^ d
    elif mode == 3:
        function = c ^ (b | (~d))
    else:
        raise ValueError(f"mode must be 0 through 3, got {mode}")
    if not 0 <= shift <= 31:
        raise ValueError(f"shift must be 0 through 31, got {shift}")

    inner = (a + function + x + t) & MASK32
    rotated = ((inner << shift) | (inner >> ((32 - shift) & 31))) & MASK32
    return (b + rotated) & MASK32


class Md5AssistImplementation:
    """Execute the pinned emulator port contract for one MD5 assist block."""

    def __init__(self, profile: str = "tilem") -> None:
        self.profile = md5_implementation(profile)
        self.operands = [0] * 6
        self.shift = 0
        self.mode = 0
        self.ignored_writes: list[tuple[int, int]] = []

    def write_port(self, port: int, value: int) -> bool:
        """Apply one byte write and return whether the profile maps it."""

        if port not in MD5_PORTS:
            return False
        if not 0 <= value <= 0xFF:
            raise ValueError("MD5 port values must be bytes")
        if port not in self.profile.mapped_ports:
            self.ignored_writes.append((port, value))
            return False
        if port <= 0x1D:
            index = port - 0x18
            self.operands[index] = (
                (self.operands[index] >> 8) | (value << 24)
            ) & MASK32
        elif port == 0x1E:
            self.shift = value & 0x1F
        else:
            self.mode = value & 0x03
        return True

    def result(self) -> int | None:
        """Return the current computed word, or ``None`` for an absent block."""

        if not self.profile.mapped_ports:
            return None
        return md5_assist_value(
            self.mode,
            *self.operands,
            self.shift,
        )

    def read_port(self, port: int) -> int | None:
        """Read one result byte or an implementation-defined operand port."""

        if port not in self.profile.mapped_ports:
            return None
        if 0x18 <= port <= 0x1B:
            return self.profile.undefined_operand_reads
        if 0x1C <= port <= 0x1F:
            result = self.result()
            assert result is not None
            return (result >> (8 * (port - 0x1C))) & 0xFF
        return None

    def load_word(self, port: int, value: int) -> None:
        """Write a 32-bit operand in the ROM's least-significant-byte order."""

        if not 0x18 <= port <= 0x1D:
            raise ValueError("operand port must be 0x18 through 0x1D")
        if not 0 <= value <= MASK32:
            raise ValueError("operand must be a 32-bit word")
        for shift in range(0, 32, 8):
            self.write_port(port, (value >> shift) & 0xFF)


@dataclass(frozen=True)
class Md5AssistStep:
    index: int
    mode: int
    a: int
    b: int
    c: int
    d: int
    x: int
    t: int
    shift: int
    result: int
    instruction_index: int
    clock: int
    space: str
    address: int

    @property
    def mode_name(self) -> str:
        return MODE_NAMES.get(self.mode, f"?{self.mode}")

    @property
    def expected_result(self) -> int:
        return md5_assist_value(
            self.mode,
            self.a,
            self.b,
            self.c,
            self.d,
            self.x,
            self.t,
            self.shift,
        )

    @property
    def verified(self) -> bool:
        return self.result == self.expected_result


def _decode_step(index: int, events: list[ResolvedIoEvent]) -> Md5AssistStep:
    mode_event = events[0]
    if mode_event.value is None:
        raise Md5TraceError(
            f"unknown mode at instruction {mode_event.instruction_index}"
        )
    shift_event = events[25]
    if shift_event.value is None:
        raise Md5TraceError(
            f"unknown shift at instruction {shift_event.instruction_index}"
        )
    return Md5AssistStep(
        index=index,
        mode=mode_event.value,
        a=_word_lsb(events[1:5]),
        b=_word_lsb(events[5:9]),
        c=_word_lsb(events[9:13]),
        d=_word_lsb(events[13:17]),
        x=_word_lsb(events[17:21]),
        t=_word_lsb(events[21:25]),
        shift=shift_event.value,
        result=_word_lsb(events[26:30]),
        instruction_index=mode_event.instruction_index,
        clock=mode_event.clock,
        space=mode_event.space,
        address=mode_event.address,
    )


def decode_md5_steps(
    events: Iterable[ResolvedIoEvent],
) -> Iterator[Md5AssistStep]:
    """Decode ROM-order transactions, ignoring unrelated leading I/O."""

    current: list[ResolvedIoEvent] = []
    step_index = 0
    for event in events:
        key = (event.direction, event.port)
        if not current:
            if key == MD5_EVENT_SEQUENCE[0]:
                current.append(event)
            continue

        expected = MD5_EVENT_SEQUENCE[len(current)]
        if key != expected:
            raise Md5TraceError(
                f"step {step_index}, event {len(current)}: expected "
                f"{expected[0]} port 0x{expected[1]:02X}, got "
                f"{key[0]} port 0x{key[1]:02X} at instruction "
                f"{event.instruction_index}"
            )
        current.append(event)
        if len(current) == len(MD5_EVENT_SEQUENCE):
            yield _decode_step(step_index, current)
            step_index += 1
            current = []

    if current:
        raise Md5TraceError(
            f"incomplete step {step_index}: {len(current)} of "
            f"{len(MD5_EVENT_SEQUENCE)} events"
        )
