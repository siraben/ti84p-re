"""Decode TI-84 Plus ASIC bus-delay registers."""

from __future__ import annotations

from dataclasses import asdict, dataclass


TIMING_PORTS = frozenset({0x20, 0x29, 0x2A, 0x2B, 0x2C, 0x2E, 0x2F})
DELAY_PORTS = frozenset(TIMING_PORTS - {0x20})


@dataclass(frozen=True)
class TimingImplementationProfile:
    """One public contract or pinned emulator implementation."""

    key: str
    name: str
    revision: str
    mapped_ports: frozenset[int]
    speed_policy: str
    delay_registers: bool
    lcd_ready_policy: str
    timer_prescaler: str
    driver_status: str
    known_limit: str


DOCUMENTED_PROFILE = TimingImplementationProfile(
    key="documented",
    name="Historical public contract",
    revision="WikiTI pages retrieved 2026-08-09",
    mapped_ports=TIMING_PORTS,
    speed_policy="low two bits select modes 0-3",
    delay_registers=True,
    lcd_ready_policy="speed-selected port-0x2F field",
    timer_prescaler="documented f+1 divisor for 0xC0-family timer sources",
    driver_status="reference description; not a hardware implementation",
    known_limit="electrical timing and cross-revision behavior remain unmeasured",
)

TILEM_PROFILE = TimingImplementationProfile(
    key="tilem",
    name="TilEm",
    revision="f56ad637d0524ee841dd381be6ecbaf5b8975600",
    mapped_ports=TIMING_PORTS,
    speed_policy="low two bits select delay mode; nonzero runs at 15 MHz",
    delay_registers=True,
    lcd_ready_policy="restart after every modeled LCD-port read or write",
    timer_prescaler="not modeled",
    driver_status="usable emulator timing implementation",
    known_limit="does not model the documented port-0x2F timer prescaler",
)

WABBITEMU_PROFILE = TimingImplementationProfile(
    key="wabbitemu",
    name="Wabbitemu",
    revision="48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422",
    mapped_ports=TIMING_PORTS,
    speed_policy="modes 2-3 require the external extra-speed option",
    delay_registers=True,
    lcd_ready_policy="measure from the last successful LCD write",
    timer_prescaler="not modeled in the compared timer path",
    driver_status="usable emulator timing implementation",
    known_limit="default TI-84 Plus state clamps speed writes 2-3 to mode 1",
)

MAME_PROFILE = TimingImplementationProfile(
    key="mame",
    name="MAME",
    revision="mame0287",
    mapped_ports=frozenset({0x20}),
    speed_policy="zero runs at 6 MHz; any nonzero byte runs at 15 MHz",
    delay_registers=False,
    lcd_ready_policy="no ASIC programmable-ready interval",
    timer_prescaler="not modeled",
    driver_status="MACHINE_NOT_WORKING TI-84 Plus driver",
    known_limit="ports 0x29-0x2F and all programmable bus waits are absent",
)

TIMING_PROFILES = {
    profile.key: profile
    for profile in (
        DOCUMENTED_PROFILE,
        TILEM_PROFILE,
        WABBITEMU_PROFILE,
        MAME_PROFILE,
    )
}
EMULATOR_PROFILE_KEYS = ("tilem", "wabbitemu", "mame")


def timing_profile(
    profile: str | TimingImplementationProfile,
) -> TimingImplementationProfile:
    """Resolve a profile key while accepting an already-resolved profile."""

    if isinstance(profile, TimingImplementationProfile):
        return profile
    try:
        return TIMING_PROFILES[profile.lower()]
    except KeyError:
        choices = ", ".join(TIMING_PROFILES)
        raise ValueError(f"unknown timing profile {profile!r}; choose {choices}") from None


@dataclass(frozen=True)
class MemoryWaits:
    """One-T-state additions selected for each memory access class."""

    flash_opcode: int
    flash_read: int
    flash_write: int
    ram_opcode: int
    ram_read: int
    ram_write: int


class BusTiming:
    """Track speed-dependent LCD and memory wait-state registers."""

    def __init__(
        self,
        *,
        speed_mode: int = 0,
        port29: int = 0,
        port2a: int = 0,
        port2b: int = 0,
        port2c: int = 0,
        port2e: int = 0,
        port2f: int = 0,
    ) -> None:
        self.speed_mode = self._speed(speed_mode)
        self.delay_ports = [
            self._byte(port29),
            self._byte(port2a),
            self._byte(port2b),
            self._byte(port2c),
        ]
        self.port2e = self._byte(port2e)
        self.port2f = self._byte(port2f)

    @staticmethod
    def _byte(value: int) -> int:
        if not 0 <= value <= 0xFF:
            raise ValueError("register values must be bytes")
        return value

    @staticmethod
    def _speed(value: int) -> int:
        if not 0 <= value <= 3:
            raise ValueError("CPU speed mode must be between 0 and 3")
        return value

    @classmethod
    def ti84p_os(cls, speed_mode: int = 1) -> "BusTiming":
        """Return the register values written by the retail boot page."""

        return cls(
            speed_mode=speed_mode,
            port29=0x17,
            port2a=0x27,
            port2b=0x2F,
            port2c=0x3B,
            port2e=0x45,
            port2f=0x4B,
        )

    def write_port(self, port: int, value: int) -> bool:
        """Apply a timing-register write and return whether it was handled."""

        if port not in TIMING_PORTS:
            return False
        value = self._byte(value)
        if port == 0x20:
            self.speed_mode = value & 3
        elif 0x29 <= port <= 0x2C:
            self.delay_ports[port - 0x29] = value
        elif port == 0x2E:
            self.port2e = value
        else:
            self.port2f = value
        return True

    def active_delay_port(self, speed_mode: int | None = None) -> tuple[int, int]:
        """Return ``(port, value)`` selected by the CPU-speed mode."""

        mode = self.speed_mode if speed_mode is None else self._speed(speed_mode)
        return 0x29 + mode, self.delay_ports[mode]

    def lcd_access_wait(self, speed_mode: int | None = None) -> int:
        """Return the modeled T-states added to each LCD-port instruction."""

        _, value = self.active_delay_port(speed_mode)
        return value >> 2

    def memory_waits(self, speed_mode: int | None = None) -> MemoryWaits:
        """Return enabled one-T-state memory additions for one speed mode."""

        _, enable = self.active_delay_port(speed_mode)
        flash = bool(enable & 0x01)
        ram = bool(enable & 0x02)
        return MemoryWaits(
            flash_opcode=int(flash and bool(self.port2e & 0x01)),
            flash_read=int(flash and bool(self.port2e & 0x02)),
            flash_write=int(flash and bool(self.port2e & 0x04)),
            ram_opcode=int(ram and bool(self.port2e & 0x10)),
            ram_read=int(ram and bool(self.port2e & 0x20)),
            ram_write=int(ram and bool(self.port2e & 0x40)),
        )

    def port2f_field(self, speed_mode: int | None = None) -> int | None:
        """Return the speed-selected port-0x2F field, or ``None`` for mode 0."""

        mode = self.speed_mode if speed_mode is None else self._speed(speed_mode)
        if mode == 0:
            return None
        if mode == 1:
            return self.port2f & 0x03
        if mode == 2:
            return (self.port2f >> 2) & 0x07
        return (self.port2f >> 5) & 0x07

    def lcd_ready_hold(self, speed_mode: int | None = None) -> int:
        """Return modeled port-0x02 not-ready T-states after an LCD access."""

        field = self.port2f_field(speed_mode)
        return 0 if field is None else 48 + 64 * field

    def documented_mode3_divisor(self, speed_mode: int | None = None) -> int:
        """Return the public mode-3 programmable-timer divisor."""

        field = self.port2f_field(speed_mode)
        return 1 if field is None else field + 1

    def row(self, speed_mode: int) -> dict[str, object]:
        """Return one serializable speed-mode summary."""

        port, value = self.active_delay_port(speed_mode)
        return {
            "speed_mode": speed_mode,
            "delay_port": port,
            "delay_value": value,
            "lcd_access_wait": self.lcd_access_wait(speed_mode),
            "memory_waits": asdict(self.memory_waits(speed_mode)),
            "lcd_ready_hold": self.lcd_ready_hold(speed_mode),
            "documented_mode3_divisor": self.documented_mode3_divisor(speed_mode),
        }

    def rows(self) -> list[dict[str, object]]:
        """Return summaries for all four CPU-speed selector values."""

        return [self.row(mode) for mode in range(4)]


class TimingImplementation:
    """Apply one implementation's I/O coverage around :class:`BusTiming`."""

    def __init__(
        self,
        *,
        profile: str | TimingImplementationProfile = "documented",
        extra_speeds: bool = False,
    ) -> None:
        self.profile = timing_profile(profile)
        self.extra_speeds = extra_speeds
        self.decoder = BusTiming()
        self.port20 = 0
        self.writes = 0
        self.ignored_writes: list[tuple[int, int]] = []

    @classmethod
    def ti84p_os(
        cls,
        profile: str | TimingImplementationProfile = "documented",
        *,
        speed_value: int = 1,
        extra_speeds: bool = False,
    ) -> "TimingImplementation":
        """Apply the retail boot values and one later speed selection."""

        implementation = cls(profile=profile, extra_speeds=extra_speeds)
        for port, value in (
            (0x29, 0x17),
            (0x2A, 0x27),
            (0x2B, 0x2F),
            (0x2C, 0x3B),
            (0x2E, 0x45),
            (0x2F, 0x4B),
            (0x20, speed_value),
        ):
            implementation.write_port(port, value)
        return implementation

    @staticmethod
    def _byte(value: int) -> int:
        return BusTiming._byte(value)

    def write_port(self, port: int, value: int) -> bool:
        """Apply a write and report whether this profile maps the port."""

        if port not in TIMING_PORTS:
            return False
        value = self._byte(value)
        if port not in self.profile.mapped_ports:
            self.ignored_writes.append((port, value))
            return False
        if port == 0x20:
            self.port20 = value
            if self.profile.key == "mame":
                mode = int(value != 0)
            else:
                mode = value & 3
                if (
                    self.profile.key == "wabbitemu"
                    and not self.extra_speeds
                    and mode > 1
                ):
                    mode = 1
            self.decoder.speed_mode = mode
        else:
            self.decoder.write_port(port, value)
        self.writes += 1
        return True

    def read_port(self, port: int) -> int | None:
        """Return modeled register readback, or ``None`` when unmapped."""

        if port not in self.profile.mapped_ports:
            return None
        if port == 0x20:
            if self.profile.key == "mame":
                return self.port20
            return self.decoder.speed_mode
        if 0x29 <= port <= 0x2C:
            return self.decoder.delay_ports[port - 0x29]
        if port == 0x2E:
            return self.decoder.port2e
        if port == 0x2F:
            return self.decoder.port2f
        return None

    def clock_mhz(self) -> int:
        """Return the CPU clock selected by this software implementation."""

        mode = self.decoder.speed_mode
        if self.profile.key == "wabbitemu" and self.extra_speeds:
            return (6, 15, 20, 25)[mode]
        return 6 if mode == 0 else 15

    def selectable_speed_modes(self) -> tuple[int, ...]:
        """Return modes reachable through port ``0x20`` in this profile."""

        if self.profile.key == "mame":
            return (0, 1)
        if self.profile.key == "wabbitemu" and not self.extra_speeds:
            return (0, 1)
        return (0, 1, 2, 3)

    def rows(self) -> list[dict[str, object]]:
        """Return delay rows for speed modes reachable by this profile."""

        if not self.profile.delay_registers:
            return []
        rows = []
        for mode in self.selectable_speed_modes():
            row = self.decoder.row(mode)
            if self.profile.key == "wabbitemu" and self.extra_speeds:
                row["clock_mhz"] = (6, 15, 20, 25)[mode]
            else:
                row["clock_mhz"] = 6 if mode == 0 else 15
            rows.append(row)
        return rows
