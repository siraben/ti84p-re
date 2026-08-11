"""Typed report and oracle for MAME's TI-84 Plus timers and absent RTC."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction

from mame_runtime import MAME_VERSION, MameRuntimeError, parse_report_fields
from timer_hardware import CRYSTAL_HZ, decode_timer_source, timer_expiry

ATTOSECONDS_PER_SECOND = 10**18
FAMILY_SOURCES = (0x01, 0x41, 0x81)
FAMILY_COUNTER = 0xFF
FAMILY_ELAPSED_ATTOSECONDS = 20_000_000_000_000_000
ZERO_ELAPSED_FRAMES = 15
SOURCE_OFF_ELAPSED_FRAMES = 2


@dataclass(frozen=True)
class MameTimerReport:
    """Complete native programmable-timer and unmapped-port observations."""

    machine: str
    version: str
    aux_initial: tuple[int, ...]
    aux_patterned: tuple[int, ...]
    rtc_initial: tuple[int, ...]
    rtc_patterned: tuple[int, ...]
    mask_setup: int
    mask_mode: int
    mask_count: int
    family_elapsed_attoseconds: int
    family_sources: tuple[int, ...]
    family_counts: tuple[int, ...]
    zero_elapsed_frames: int
    zero_count: int
    zero_setup: int
    zero_mode: int
    zero_port4: int
    bit1_set_count: int
    bit1_set_setup: int
    bit1_set_mode: int
    bit1_set_port4: int
    bit1_clear_count: int
    bit1_clear_setup: int
    bit1_clear_mode: int
    bit1_clear_port4: int
    loop_count: int
    loop_setup: int
    loop_mode: int
    loop_port4: int
    global_before: int
    global_after: int
    source_off_elapsed_frames: int
    source_off_count: int
    source_off_setup: int
    source_off_mode: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _report_line(output: str, prefix: str) -> dict[str, str]:
    lines = [line for line in output.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        raise MameRuntimeError(f"MAME timer output omits {prefix.strip()} report")
    return parse_report_fields(lines[0])


def _hex_bytes(value: str, expected: int, name: str) -> tuple[int, ...]:
    if len(value) != expected * 2:
        raise MameRuntimeError(f"MAME timer {name} must contain {expected} bytes")
    try:
        return tuple(
            int(value[index : index + 2], 16) for index in range(0, len(value), 2)
        )
    except ValueError as error:
        raise MameRuntimeError(f"invalid MAME timer {name}") from error


def parse_mame_timer_report(output: str) -> MameTimerReport:
    """Parse every native timer, status, and unmapped-port report line."""

    identity = _report_line(output, "MAME_TIMER identity ")
    mapping = _report_line(output, "MAME_TIMER mapping ")
    masks = _report_line(output, "MAME_TIMER masks ")
    family = _report_line(output, "MAME_TIMER family ")
    zero = _report_line(output, "MAME_TIMER zero ")
    polarity = _report_line(output, "MAME_TIMER polarity ")
    loop = _report_line(output, "MAME_TIMER loop ")
    global_status = _report_line(output, "MAME_TIMER global ")
    source_off = _report_line(output, "MAME_TIMER source_off ")
    try:
        return MameTimerReport(
            machine=identity["machine"],
            version=identity["version"],
            aux_initial=_hex_bytes(mapping["aux_initial"], 3, "aux block"),
            aux_patterned=_hex_bytes(mapping["aux_patterned"], 3, "aux block"),
            rtc_initial=_hex_bytes(mapping["rtc_initial"], 9, "RTC block"),
            rtc_patterned=_hex_bytes(mapping["rtc_patterned"], 9, "RTC block"),
            mask_setup=int(masks["setup"], 16),
            mask_mode=int(masks["mode"], 16),
            mask_count=int(masks["count"], 16),
            family_elapsed_attoseconds=int(family["elapsed_attoseconds"], 10),
            family_sources=_hex_bytes(family["sources"], 3, "family sources"),
            family_counts=_hex_bytes(family["counts"], 3, "family counts"),
            zero_elapsed_frames=int(zero["elapsed_frames"], 10),
            zero_count=int(zero["count"], 16),
            zero_setup=int(zero["setup"], 16),
            zero_mode=int(zero["mode"], 16),
            zero_port4=int(zero["port4"], 16),
            bit1_set_count=int(polarity["bit1_set_count"], 16),
            bit1_set_setup=int(polarity["bit1_set_setup"], 16),
            bit1_set_mode=int(polarity["bit1_set_mode"], 16),
            bit1_set_port4=int(polarity["bit1_set_port4"], 16),
            bit1_clear_count=int(polarity["bit1_clear_count"], 16),
            bit1_clear_setup=int(polarity["bit1_clear_setup"], 16),
            bit1_clear_mode=int(polarity["bit1_clear_mode"], 16),
            bit1_clear_port4=int(polarity["bit1_clear_port4"], 16),
            loop_count=int(loop["count"], 16),
            loop_setup=int(loop["setup"], 16),
            loop_mode=int(loop["mode"], 16),
            loop_port4=int(loop["port4"], 16),
            global_before=int(global_status["before"], 16),
            global_after=int(global_status["after"], 16),
            source_off_elapsed_frames=int(source_off["elapsed_frames"], 10),
            source_off_count=int(source_off["count"], 16),
            source_off_setup=int(source_off["setup"], 16),
            source_off_mode=int(source_off["mode"], 16),
        )
    except KeyError as error:
        raise MameRuntimeError(
            f"MAME timer report omits field {error.args[0]}"
        ) from error
    except MameRuntimeError:
        raise
    except ValueError as error:
        raise MameRuntimeError("invalid numeric MAME timer report field") from error


def _mame_nonloop_count(source: int, counter: int, elapsed_attoseconds: int) -> int:
    decoded = decode_timer_source("MAME", source)
    if decoded is None or counter == 0:
        return counter
    period = Fraction(
        decoded.divisor * ATTOSECONDS_PER_SECOND,
        CRYSTAL_HZ,
    )
    callbacks = int(Fraction(elapsed_attoseconds, 1) // period) + 1
    return max(0, counter - callbacks)


def expected_mame_timer_report() -> MameTimerReport:
    """Return the exact report derived from the reusable MAME timer model."""

    bit1_set = timer_expiry("MAME", 0x02)
    bit1_clear = timer_expiry("MAME", 0x00)
    loop = timer_expiry("MAME", 0x01)
    return MameTimerReport(
        machine="ti84pv3",
        version=MAME_VERSION,
        aux_initial=(0, 0, 0),
        aux_patterned=(0, 0, 0),
        rtc_initial=(0,) * 9,
        rtc_patterned=(0,) * 9,
        mask_setup=0xFF,
        mask_mode=0x03,
        mask_count=0x00,
        family_elapsed_attoseconds=FAMILY_ELAPSED_ATTOSECONDS,
        family_sources=FAMILY_SOURCES,
        family_counts=tuple(
            _mame_nonloop_count(
                source,
                FAMILY_COUNTER,
                FAMILY_ELAPSED_ATTOSECONDS,
            )
            for source in FAMILY_SOURCES
        ),
        zero_elapsed_frames=ZERO_ELAPSED_FRAMES,
        zero_count=0,
        zero_setup=0x07,
        zero_mode=0,
        zero_port4=0x08,
        bit1_set_count=0,
        bit1_set_setup=0,
        bit1_set_mode=bit1_set.mode_read_after_expiry,
        bit1_set_port4=0x08,
        bit1_clear_count=0,
        bit1_clear_setup=0,
        bit1_clear_mode=bit1_clear.mode_read_after_expiry,
        bit1_clear_port4=0x88,
        loop_count=0,
        loop_setup=0,
        loop_mode=loop.mode_read_after_expiry,
        loop_port4=0x88,
        global_before=0x68,
        global_after=0x08,
        source_off_elapsed_frames=SOURCE_OFF_ELAPSED_FRAMES,
        source_off_count=5,
        source_off_setup=0,
        source_off_mode=0x02,
    )


def validate_mame_timer_report(report: MameTimerReport) -> dict[str, object]:
    """Require native observations implied by MAME 0.287's pinned source."""

    expected = expected_mame_timer_report()
    if report != expected:
        raise MameRuntimeError(
            "MAME timer report disagrees with the 0.287 source model"
        )
    return {
        "source_model": {
            "mapped_timer_ports": list(range(0x30, 0x39)),
            "unmapped_aux_ports": list(range(0x2D, 0x30)),
            "unmapped_rtc_ports": list(range(0x40, 0x49)),
            "nonzero_source_family": "32.768 kHz and low-three-bit divisor",
            "first_callback_delay": "zero",
            "counter_zero_expires": False,
            "interrupt_polarity": "mode bit 1 clear",
            "loop_bit_retained": False,
            "mode_write_status_scope": "all three timers",
        },
        "native": report.to_dict(),
    }
