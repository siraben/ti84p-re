"""Typed report and source-derived oracle for MAME's TI-84 Plus ASIC I/O."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ti84re.hardware.asic_control import asic_implementation, implementation_port21_readback
from ti84re.hardware.bus_timing import TimingImplementation, timing_profile
from ti84re.emulators.mame.runtime import MAME_VERSION, MameRuntimeError, parse_report_fields

GATE_VALUES = (0x00, 0x01, 0x02, 0x3F, 0x40, 0xFF)
SPEED_VALUES = (0x00, 0x01, 0x02, 0x03, 0xFF)
PROTECTION_PORTS = tuple(range(0x22, 0x30))
GPIO_PORTS = (0x39, 0x3A)
USB_PORTS = tuple(range(0x4A, 0x5C))


@dataclass(frozen=True)
class MameAsicReport:
    """Complete status, control, mapping, clock, and soft-reset observations."""

    machine: str
    version: str
    reset_status02: int
    reset_port14: int
    reset_identity15: int
    reset_speed20: int
    reset_control21: int
    reset_usb55: int
    reset_usb56: int
    reset_pc: int
    gate_values: tuple[int, ...]
    gate_status: tuple[int, ...]
    gate_readback: tuple[int, ...]
    speed_values: tuple[int, ...]
    speed_readback: tuple[int, ...]
    control_locked33: int
    control_unlocked30: int
    control_unlocked03: int
    control_unlocked33: int
    control_unlockedff: int
    protection_initial: tuple[int, ...]
    protection_patterned: tuple[int, ...]
    gpio_initial: tuple[int, ...]
    gpio_patterned: tuple[int, ...]
    usb_initial: tuple[int, ...]
    usb_patterned: tuple[int, ...]
    clock_frames: int
    clock_low_count: int
    clock_low_attoseconds: int
    clock_high_count: int
    clock_high_attoseconds: int
    clock_control21: int
    clock_protection: tuple[int, ...]
    soft_status02: int
    soft_port14: int
    soft_identity15: int
    soft_speed20: int
    soft_control21: int
    soft_usb55: int
    soft_usb56: int
    soft_pc: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _one_line(output: str, prefix: str) -> dict[str, str]:
    matches = [line for line in output.splitlines() if line.startswith(prefix)]
    if len(matches) != 1:
        raise MameRuntimeError(
            f"MAME ASIC output requires exactly one {prefix.strip()} line"
        )
    return parse_report_fields(matches[0])


def _hex(fields: dict[str, str], name: str) -> int:
    try:
        return int(fields[name], 16)
    except KeyError as error:
        raise MameRuntimeError(f"MAME ASIC report omits field {name}") from error
    except ValueError as error:
        raise MameRuntimeError(f"invalid MAME ASIC field {name}") from error


def _decimal(fields: dict[str, str], name: str) -> int:
    try:
        return int(fields[name], 10)
    except KeyError as error:
        raise MameRuntimeError(f"MAME ASIC report omits field {name}") from error
    except ValueError as error:
        raise MameRuntimeError(f"invalid MAME ASIC field {name}") from error


def _bytes(value: str, count: int, name: str) -> tuple[int, ...]:
    if len(value) != count * 2:
        raise MameRuntimeError(f"MAME ASIC {name} must contain exactly {count} bytes")
    try:
        return tuple(
            int(value[index : index + 2], 16) for index in range(0, count * 2, 2)
        )
    except ValueError as error:
        raise MameRuntimeError(f"invalid MAME ASIC {name}") from error


def _block(fields: dict[str, str], name: str, count: int) -> tuple[int, ...]:
    try:
        return _bytes(fields[name], count, name)
    except KeyError as error:
        raise MameRuntimeError(f"MAME ASIC report omits field {name}") from error


def parse_mame_asic_report(output: str) -> MameAsicReport:
    """Parse the complete guarded MAME ASIC-control report."""

    identity = _one_line(output, "MAME_ASIC identity ")
    reset = _one_line(output, "MAME_ASIC reset ")
    gate = _one_line(output, "MAME_ASIC gate ")
    speed = _one_line(output, "MAME_ASIC speed ")
    control = _one_line(output, "MAME_ASIC control ")
    mapping = _one_line(output, "MAME_ASIC mapping ")
    clocks = _one_line(output, "MAME_ASIC clocks ")
    soft = _one_line(output, "MAME_ASIC soft_reset ")
    try:
        machine = identity["machine"]
        version = identity["version"]
    except KeyError as error:
        raise MameRuntimeError(
            f"MAME ASIC identity omits field {error.args[0]}"
        ) from error
    return MameAsicReport(
        machine=machine,
        version=version,
        reset_status02=_hex(reset, "status02"),
        reset_port14=_hex(reset, "port14"),
        reset_identity15=_hex(reset, "identity15"),
        reset_speed20=_hex(reset, "speed20"),
        reset_control21=_hex(reset, "control21"),
        reset_usb55=_hex(reset, "usb55"),
        reset_usb56=_hex(reset, "usb56"),
        reset_pc=_hex(reset, "pc"),
        gate_values=_block(gate, "values", len(GATE_VALUES)),
        gate_status=_block(gate, "status", len(GATE_VALUES)),
        gate_readback=_block(gate, "readback", len(GATE_VALUES)),
        speed_values=_block(speed, "values", len(SPEED_VALUES)),
        speed_readback=_block(speed, "readback", len(SPEED_VALUES)),
        control_locked33=_hex(control, "locked33"),
        control_unlocked30=_hex(control, "unlocked30"),
        control_unlocked03=_hex(control, "unlocked03"),
        control_unlocked33=_hex(control, "unlocked33"),
        control_unlockedff=_hex(control, "unlockedff"),
        protection_initial=_block(mapping, "protection_initial", len(PROTECTION_PORTS)),
        protection_patterned=_block(
            mapping, "protection_patterned", len(PROTECTION_PORTS)
        ),
        gpio_initial=_block(mapping, "gpio_initial", len(GPIO_PORTS)),
        gpio_patterned=_block(mapping, "gpio_patterned", len(GPIO_PORTS)),
        usb_initial=_block(mapping, "usb_initial", len(USB_PORTS)),
        usb_patterned=_block(mapping, "usb_patterned", len(USB_PORTS)),
        clock_frames=_decimal(clocks, "frames"),
        clock_low_count=_hex(clocks, "low_count"),
        clock_low_attoseconds=_decimal(clocks, "low_attoseconds"),
        clock_high_count=_hex(clocks, "high_count"),
        clock_high_attoseconds=_decimal(clocks, "high_attoseconds"),
        clock_control21=_hex(clocks, "control21"),
        clock_protection=_block(clocks, "protection", 5),
        soft_status02=_hex(soft, "status02"),
        soft_port14=_hex(soft, "port14"),
        soft_identity15=_hex(soft, "identity15"),
        soft_speed20=_hex(soft, "speed20"),
        soft_control21=_hex(soft, "control21"),
        soft_usb55=_hex(soft, "usb55"),
        soft_usb56=_hex(soft, "usb56"),
        soft_pc=_hex(soft, "pc"),
    )


def mame_status_for_gate(value: int) -> int:
    """Return MAME's byte result for one raw port-``0x14`` value."""

    if not 0 <= value <= 0xFF:
        raise ValueError("gate value must be a byte")
    return (0xC3 | (value << 2)) & 0xFF


def _usb_block() -> tuple[int, ...]:
    return tuple(0x1F if port == 0x55 else 0 for port in USB_PORTS)


def _speed_vectors() -> tuple[tuple[int, ...], tuple[int, ...]]:
    implementation = TimingImplementation(profile="mame")
    reads = []
    clocks = []
    for value in SPEED_VALUES:
        if not implementation.write_port(0x20, value):
            raise AssertionError("MAME timing profile omitted port 0x20")
        read = implementation.read_port(0x20)
        if read is None:
            raise AssertionError("MAME timing profile lost speed readback")
        reads.append(read)
        clocks.append(implementation.clock_mhz() * 1_000_000)
    return tuple(reads), tuple(clocks)


def expected_mame_asic_report() -> MameAsicReport:
    """Return the exact runtime report derived from the pinned source models."""

    speed_reads, speed_clocks = _speed_vectors()
    frame_attoseconds = 20_000_000_000_000_000
    frames = 5
    interval_attoseconds = frames * frame_attoseconds
    loop_tstates = 50
    low_count = speed_clocks[0] * frames // 50 // loop_tstates
    high_count = speed_clocks[1] * frames // 50 // loop_tstates
    zeros14 = (0,) * len(PROTECTION_PORTS)
    zeros2 = (0,) * len(GPIO_PORTS)
    zeros5 = (0,) * 5
    usb = _usb_block()
    return MameAsicReport(
        machine="ti84pv3",
        version=MAME_VERSION,
        reset_status02=asic_implementation("mame").fixed_port02_locked or 0,
        reset_port14=0,
        reset_identity15=asic_implementation("mame").fixed_port15 or 0,
        reset_speed20=0,
        reset_control21=0,
        reset_usb55=0x1F,
        reset_usb56=0,
        reset_pc=0,
        gate_values=GATE_VALUES,
        gate_status=tuple(mame_status_for_gate(value) for value in GATE_VALUES),
        gate_readback=(0,) * len(GATE_VALUES),
        speed_values=SPEED_VALUES,
        speed_readback=speed_reads,
        control_locked33=implementation_port21_readback("mame", 0x33),
        control_unlocked30=implementation_port21_readback("mame", 0x30),
        control_unlocked03=implementation_port21_readback("mame", 0x03),
        control_unlocked33=implementation_port21_readback("mame", 0x33),
        control_unlockedff=implementation_port21_readback("mame", 0xFF),
        protection_initial=zeros14,
        protection_patterned=zeros14,
        gpio_initial=zeros2,
        gpio_patterned=zeros2,
        usb_initial=usb,
        usb_patterned=usb,
        clock_frames=frames,
        clock_low_count=low_count,
        clock_low_attoseconds=interval_attoseconds,
        clock_high_count=high_count,
        clock_high_attoseconds=interval_attoseconds,
        clock_control21=0x03,
        clock_protection=zeros5,
        soft_status02=mame_status_for_gate(0x01),
        soft_port14=0,
        soft_identity15=0x33,
        soft_speed20=0x03,
        soft_control21=implementation_port21_readback("mame", 0xAB),
        soft_usb55=0x1F,
        soft_usb56=0,
        soft_pc=0,
    )


def validate_mame_asic_report(report: MameAsicReport) -> dict[str, object]:
    """Require every native value implied by MAME 0.287's TI-84 Plus source."""

    expected = expected_mame_asic_report()
    if report != expected:
        raise MameRuntimeError("MAME ASIC report disagrees with the 0.287 source model")
    timing = timing_profile("mame")
    return {
        "source_model": {
            "mapped_control_ports": sorted(asic_implementation("mame").mapped_ports),
            "mapped_timing_ports": sorted(timing.mapped_ports),
            "raw_gate_status_formula": "(C3 | (value << 2)) & FF",
            "port14_readback": "unmapped read returns 00",
            "port21_policy": "write and readback masked with 0F; gate ignored",
            "protection_ports_22_2f": "unmapped",
            "gpio_ports_39_3a": "unmapped",
            "usb_ports_4a_5b": "only 55=1F and 56=00 are mapped",
            "speed_policy": timing.speed_policy,
            "clock_loop": "50 T-states over five 20 ms frames",
            "clock_ratio": report.clock_high_count / report.clock_low_count,
            "ram_fetch_with_patterned_protection_ports": True,
            "soft_reset_retained": ["port14 state", "port20", "port21"],
        },
        "native": report.to_dict(),
    }
