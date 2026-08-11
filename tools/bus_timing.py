"""Decode TI-84 Plus ASIC bus-delay registers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction

TIMING_PORTS = frozenset({0x20, 0x29, 0x2A, 0x2B, 0x2C, 0x2E, 0x2F})
DELAY_PORTS = frozenset(TIMING_PORTS - {0x20})
WABBITEMU_TIMING_PORTS = TIMING_PORTS | {0x2D}
IMPLEMENTATION_PORTS = WABBITEMU_TIMING_PORTS
BUS_TIMING_PROBE_TIMER_SOURCE = 0x45
BUS_TIMING_PROBE_TIMER_TICK_HZ = 2_048
BUS_TIMING_PROBE_MEASUREMENT_SIZE = 3
PREFIX_M1_PROBE_ITERATIONS = 12_288


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
    mapped_ports=WABBITEMU_TIMING_PORTS,
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


@dataclass(frozen=True)
class BusTimingProbeCase:
    """One paired baseline/enabled physical wait-state measurement."""

    key: str
    wait_mask: int
    iterations: int
    wait_sensitive_accesses: int
    operation: str


BUS_TIMING_PROBE_CASES = (
    BusTimingProbeCase(
        "flash_opcode",
        0x01,
        4_096,
        20_480,
        "five fixed-page opcode fetches per call to 00:0CE6",
    ),
    BusTimingProbeCase(
        "flash_read",
        0x02,
        16_384,
        16_384,
        "one fixed-page data read per iteration",
    ),
    BusTimingProbeCase(
        "flash_write",
        0x04,
        16_384,
        16_384,
        "one locked 0xF0 reset-command write per iteration",
    ),
    BusTimingProbeCase(
        "ram_opcode",
        0x10,
        16_384,
        65_537,
        "four loop opcode fetches per iteration plus the counter-read opcode",
    ),
    BusTimingProbeCase(
        "ram_read",
        0x20,
        16_384,
        32_769,
        "one data and one branch-operand read per iteration plus the counter operand",
    ),
    BusTimingProbeCase(
        "ram_write",
        0x40,
        16_384,
        16_384,
        "one idempotent scratch write per iteration",
    ),
)


@dataclass(frozen=True)
class PrefixM1ProbeCase:
    """One RAM-resident instruction shape in the physical M1 matrix."""

    key: str
    encoding: bytes
    instruction: str
    z80_m1_fetches: int
    tilem_m1_fetches: int
    wabbitemu_m1_fetches: int
    iterations: int = PREFIX_M1_PROBE_ITERATIONS
    wait_mask: int = 0x10

    @property
    def wait_sensitive_accesses(self) -> int:
        """Return Z80 M1 cycles in the complete timed loop."""

        return (4 + self.z80_m1_fetches) * self.iterations + 1

    @property
    def operation(self) -> str:
        """Return the instruction and exact bytes used by the loop."""

        return f"{self.instruction} ({self.encoding.hex().upper()})"

    def model_wait_sensitive_accesses(self) -> dict[str, int]:
        """Return complete-loop M1 counts for the compared source models."""

        return {
            "z80": (4 + self.z80_m1_fetches) * self.iterations + 1,
            "tilem": (4 + self.tilem_m1_fetches) * self.iterations + 1,
            "wabbitemu": (
                (4 + self.wabbitemu_m1_fetches) * self.iterations + 1
            ),
        }


PREFIX_M1_PROBE_CASES = (
    PrefixM1ProbeCase("unprefixed", bytes.fromhex("00"), "NOP", 1, 1, 1),
    PrefixM1ProbeCase("cb", bytes.fromhex("CB42"), "BIT 0,D", 2, 2, 2),
    PrefixM1ProbeCase("ed", bytes.fromhex("ED44"), "NEG", 2, 2, 2),
    PrefixM1ProbeCase("dd", bytes.fromhex("DD7C"), "LD A,IXH", 2, 2, 2),
    PrefixM1ProbeCase(
        "dd_dd",
        bytes.fromhex("DDDD7C"),
        "LD A,IXH with a repeated DD prefix",
        3,
        3,
        3,
    ),
    PrefixM1ProbeCase(
        "dd_cb",
        bytes.fromhex("DDCB0046"),
        "BIT 0,(IX+0)",
        2,
        2,
        3,
    ),
)


def _decode_paired_wait_measurements(
    data: bytes,
    cases: tuple[BusTimingProbeCase | PrefixM1ProbeCase, ...],
) -> dict[str, object]:
    """Decode baseline/enabled timer-2 triples for one wait-state matrix."""

    pair_size = 2 * BUS_TIMING_PROBE_MEASUREMENT_SIZE
    expected_size = len(cases) * pair_size
    if len(data) != expected_size:
        raise ValueError(f"wait measurements must contain {expected_size} bytes")

    rows = []
    for index, case in enumerate(cases):
        offset = index * pair_size
        baseline_counter, baseline_mode, baseline_port04 = data[offset : offset + 3]
        enabled_counter, enabled_mode, enabled_port04 = data[offset + 3 : offset + 6]
        baseline_elapsed = 0xFF - baseline_counter
        enabled_elapsed = 0xFF - enabled_counter
        baseline_completed = bool(
            (baseline_mode & 0x04) or (baseline_port04 & 0x40)
        )
        enabled_completed = bool(
            (enabled_mode & 0x04) or (enabled_port04 & 0x40)
        )
        delta_ticks = enabled_elapsed - baseline_elapsed
        valid = (
            not baseline_completed
            and not enabled_completed
            and delta_ticks >= 0
        )
        inferred_hz = (
            Fraction(
                case.wait_sensitive_accesses * BUS_TIMING_PROBE_TIMER_TICK_HZ,
                delta_ticks,
            )
            if valid and delta_ticks > 0
            else None
        )
        rows.append(
            {
                "case": case.key,
                "wait_mask": case.wait_mask,
                "iterations": case.iterations,
                "wait_sensitive_accesses": case.wait_sensitive_accesses,
                "operation": case.operation,
                "baseline": {
                    "counter": baseline_counter,
                    "mode": baseline_mode,
                    "port_0x04": baseline_port04,
                    "elapsed_timer_ticks": baseline_elapsed,
                    "completed": baseline_completed,
                },
                "enabled": {
                    "counter": enabled_counter,
                    "mode": enabled_mode,
                    "port_0x04": enabled_port04,
                    "elapsed_timer_ticks": enabled_elapsed,
                    "completed": enabled_completed,
                },
                "valid": valid,
                "added_timer_ticks": delta_ticks if valid else None,
                "wait_observed": bool(valid and delta_ticks > 0),
                "inferred_cpu_hz_fraction": (
                    str(inferred_hz) if inferred_hz is not None else None
                ),
                "inferred_cpu_hz": (
                    float(inferred_hz) if inferred_hz is not None else None
                ),
            }
        )
    return {
        "timer_source": BUS_TIMING_PROBE_TIMER_SOURCE,
        "timer_tick_hz": BUS_TIMING_PROBE_TIMER_TICK_HZ,
        "measurement_order": "case-major, baseline then enabled",
        "cases": rows,
    }


def decode_bus_timing_probe_measurements(data: bytes) -> dict[str, object]:
    """Decode paired timer-2 samples from the physical bus-timing probe."""

    try:
        return _decode_paired_wait_measurements(data, BUS_TIMING_PROBE_CASES)
    except ValueError as error:
        raise ValueError(
            "bus-timing measurements must contain "
            f"{len(BUS_TIMING_PROBE_CASES) * 2 * BUS_TIMING_PROBE_MEASUREMENT_SIZE} "
            "bytes"
        ) from error


def decode_prefix_m1_probe_measurements(data: bytes) -> dict[str, object]:
    """Decode the physical prefix-fetch matrix and its emulator discriminator."""

    try:
        report = _decode_paired_wait_measurements(data, PREFIX_M1_PROBE_CASES)
    except ValueError as error:
        raise ValueError(
            "prefix-M1 measurements must contain "
            f"{len(PREFIX_M1_PROBE_CASES) * 2 * BUS_TIMING_PROBE_MEASUREMENT_SIZE} "
            "bytes"
        ) from error

    cases_by_key = {case.key: case for case in PREFIX_M1_PROBE_CASES}
    rows_by_key = {row["case"]: row for row in report["cases"]}
    for row in report["cases"]:
        case = cases_by_key[row["case"]]
        model_accesses = case.model_wait_sensitive_accesses()
        delta_ticks = row["added_timer_ticks"]
        row["encoding_hex"] = case.encoding.hex().upper()
        row["instruction_m1_fetches"] = {
            "z80": case.z80_m1_fetches,
            "tilem": case.tilem_m1_fetches,
            "wabbitemu": case.wabbitemu_m1_fetches,
        }
        row["model_wait_sensitive_accesses"] = model_accesses
        row["model_inferred_cpu_hz"] = {
            model: (
                float(
                    Fraction(
                        accesses * BUS_TIMING_PROBE_TIMER_TICK_HZ,
                        delta_ticks,
                    )
                )
                if delta_ticks is not None and delta_ticks > 0
                else None
            )
            for model, accesses in model_accesses.items()
        }

    single_prefix_ticks = tuple(
        rows_by_key[key]["added_timer_ticks"] for key in ("cb", "ed", "dd")
    )
    dd_dd_ticks = rows_by_key["dd_dd"]["added_timer_ticks"]
    dd_cb_ticks = rows_by_key["dd_cb"]["added_timer_ticks"]
    if (
        dd_dd_ticks is None
        or dd_cb_ticks is None
        or any(value is None for value in single_prefix_ticks)
    ):
        discriminator = {
            "valid": False,
            "closer_to": None,
            "single_prefix_mean_ticks": None,
            "repeated_prefix_ticks": dd_dd_ticks,
            "indexed_cb_ticks": dd_cb_ticks,
        }
    else:
        single_prefix_mean = Fraction(sum(single_prefix_ticks), 3)
        distance_to_z80 = abs(Fraction(dd_cb_ticks) - single_prefix_mean)
        distance_to_wabbitemu = abs(Fraction(dd_cb_ticks) - dd_dd_ticks)
        if distance_to_z80 < distance_to_wabbitemu:
            closer_to = "z80-and-tilem-two-m1"
        elif distance_to_wabbitemu < distance_to_z80:
            closer_to = "wabbitemu-three-m1"
        else:
            closer_to = "equidistant"
        discriminator = {
            "valid": True,
            "closer_to": closer_to,
            "single_prefix_mean_ticks": float(single_prefix_mean),
            "repeated_prefix_ticks": dd_dd_ticks,
            "indexed_cb_ticks": dd_cb_ticks,
            "distance_to_z80_and_tilem_ticks": float(distance_to_z80),
            "distance_to_wabbitemu_ticks": float(distance_to_wabbitemu),
        }
    report["indexed_cb_discriminator"] = discriminator
    return report


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
    def ti84p_os(cls, speed_mode: int = 1) -> BusTiming:
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
        self.port2d = 0
        self.writes = 0
        self.ignored_writes: list[tuple[int, int]] = []

    @classmethod
    def ti84p_os(
        cls,
        profile: str | TimingImplementationProfile = "documented",
        *,
        speed_value: int = 1,
        extra_speeds: bool = False,
    ) -> TimingImplementation:
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

        if port not in IMPLEMENTATION_PORTS:
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
        elif port == 0x2D:
            self.port2d = value
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
        if port == 0x2D:
            return self.port2d
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
