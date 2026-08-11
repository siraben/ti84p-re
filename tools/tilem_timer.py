"""Pinned TilEm timer/RTC build helpers, typed report, and source oracle."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
from pathlib import Path

from tilem_core import TilemCoreError, run_probe
from tilem_core import build_command as build_core_command
from tilem_core import build_probe as build_core_probe
from timer_hardware import decode_timer_source, timer_duration

REPORT_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")
TOOLS = Path(__file__).resolve().parent
CRYSTAL_SOURCES = tuple(range(0x40, 0x48))
CPU_SOURCES = (0x80, 0x81, 0x82, 0x84, 0x88, 0x90, 0xA0)
TilemTimerError = TilemCoreError


@dataclass(frozen=True)
class TilemTimerReport:
    """Complete direct-core programmable-timer and RTC observations."""

    reset: tuple[int, ...]
    crystal_us: tuple[int, ...]
    crystal_count: tuple[int, ...]
    cpu_clocks: tuple[int, ...]
    off_running: tuple[int, ...]
    off_count: tuple[int, ...]
    mode3_clocks: tuple[int, ...]
    mode_mask: tuple[int, ...]
    expiry: tuple[int, ...]
    acknowledged: tuple[int, ...]
    restarted: tuple[int, ...]
    mapping_status: tuple[int, ...]
    mapping_interrupts: tuple[int, ...]
    source_stop: tuple[int, ...]
    rtc: tuple[int, ...]
    warnings: tuple[str, ...] = ()
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_command(
    source: Path,
    adapter: Path,
    output: Path,
    *,
    cc: str = "cc",
) -> list[str]:
    """Return the direct-core timer-probe compiler command."""

    return build_core_command(
        source,
        [TOOLS / "tilem_probe_support.c", adapter],
        output,
        cc=cc,
    )


def build_probe(
    source: Path,
    adapter: Path,
    output: Path,
    *,
    cc: str = "cc",
) -> list[str]:
    """Validate pinned sources and compile the direct-core timer probe."""

    return build_core_probe(
        source,
        [TOOLS / "tilem_probe_support.c", adapter],
        output,
        cc=cc,
    )


def _vector(
    fields: dict[str, str], name: str, length: int, *, base: int
) -> tuple[int, ...]:
    try:
        values = tuple(int(value, base) for value in fields[name].split(","))
    except (KeyError, ValueError) as error:
        raise TilemTimerError(f"invalid native TilEm timer field {name}") from error
    if len(values) != length:
        raise TilemTimerError(
            f"native TilEm timer field {name} must contain {length} values"
        )
    return values


def parse_timer_report(line: str) -> TilemTimerReport:
    """Parse the complete one-line native TilEm timer and RTC report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    if fields.get("mode") != "tilem-timer-probe":
        raise TilemTimerError("native TilEm timer report has an invalid mode")
    return TilemTimerReport(
        reset=_vector(fields, "reset", 15, base=16),
        crystal_us=_vector(fields, "crystal_us", 8, base=10),
        crystal_count=_vector(fields, "crystal_count", 8, base=10),
        cpu_clocks=_vector(fields, "cpu_clocks", 7, base=10),
        off_running=_vector(fields, "off_running", 3, base=10),
        off_count=_vector(fields, "off_count", 3, base=10),
        mode3_clocks=_vector(fields, "mode3_clocks", 3, base=10),
        mode_mask=_vector(fields, "mode_mask", 4, base=16),
        expiry=_vector(fields, "expiry", 25, base=16),
        acknowledged=_vector(fields, "acknowledged", 4, base=16),
        restarted=_vector(fields, "restarted", 5, base=16),
        mapping_status=_vector(fields, "mapping_status", 3, base=16),
        mapping_interrupts=_vector(fields, "mapping_interrupts", 3, base=16),
        source_stop=_vector(fields, "source_stop", 5, base=16),
        rtc=_vector(fields, "rtc", 13, base=16),
    )


def _microseconds(source: int, counter: int) -> int:
    duration = timer_duration("TilEm", source, counter).duration_seconds * 1_000_000
    if not isinstance(duration, Fraction) or duration.denominator != 1:
        raise AssertionError("TilEm crystal duration must be a whole microsecond")
    return duration.numerator


def expected_timer_report() -> TilemTimerReport:
    """Derive every direct observation from the pinned TilEm source model."""

    crystal_us = tuple(_microseconds(source, 1) for source in CRYSTAL_SOURCES)
    crystal_overflow_us = tuple(_microseconds(source, 0) for source in CRYSTAL_SOURCES)
    crystal_count = tuple(
        duration * 256 // overflow
        for duration, overflow in zip(crystal_us, crystal_overflow_us, strict=True)
    )
    cpu_clocks = tuple(
        decode_timer_source("TilEm", source).divisor for source in CPU_SOURCES
    )
    return TilemTimerReport(
        reset=(0,) * 9 + (0x08, 0, 0, 0, 0, 0),
        crystal_us=crystal_us,
        crystal_count=crystal_count,
        cpu_clocks=cpu_clocks,
        off_running=(0, 0, 0),
        off_count=(5, 5, 5),
        mode3_clocks=(1, 1, 1),
        mode_mask=(0x203, 0x03, 0x200, 0x00),
        expiry=(
            0x02,
            0x02,
            0x08,
            0,
            0x100,
            0x100,
            0,
            0x28,
            0,
            0,
            0x104,
            0x04,
            0x28,
            0,
            0,
            0x102,
            0x02,
            0x28,
            0x08,
            0,
            0x107,
            0x07,
            0x28,
            0x08,
            0x100,
        ),
        acknowledged=(0x02, 0x02, 0x08, 0),
        restarted=(0x100, 0, 0x28, 0x100, 1),
        mapping_status=(0x28, 0x68, 0xE8),
        mapping_interrupts=(0x08, 0x18, 0x38),
        source_stop=(6, 6, 0, 0x81, 0x03),
        rtc=(
            0,
            0x12345678,
            0x12345678,
            0x12345682,
            0x12345682,
            0x12345687,
            0xDEADBEEF,
            0xDEADBEEF,
            0x02,
            0xDEADBEEF,
            0x00FFFFFF,
            0,
            0x01000000,
        ),
    )


def validate_timer_report(report: TilemTimerReport) -> dict[str, object]:
    """Require direct observations implied by the pinned TilEm source model."""

    expected = expected_timer_report()
    comparable = replace(report, warnings=(), binary_sha256="")
    if comparable != expected:
        expected_values = expected.to_dict()
        observed_values = comparable.to_dict()
        disagreements = {
            name: {
                "expected": expected_values[name],
                "observed": observed_values[name],
            }
            for name in expected_values
            if expected_values[name] != observed_values[name]
        }
        raise TilemTimerError(
            "native TilEm timer report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "crystal_divisors": [3, 33, 328, 3277, 1, 16, 256, 4096],
            "crystal_rounding": "nearest whole microsecond",
            "cpu_divisors": [1, 2, 4, 8, 16, 32, 64],
            "mode3_port2f_effect": False,
            "counter_zero_completion": False,
            "second_unacknowledged_expiry_sets_overflow": True,
            "unacknowledged_nonloop_restart_period": 256,
            "source_write_stops_and_retains_counter": True,
            "rtc_source": "probe-controlled time_t plus 32-bit offset",
            "rtc_disabled_read": "frozen offset",
            "rtc_byte_read_latch": False,
            "rtc_reset_retains_fields": True,
            "physical_scope": False,
        },
        "native": report.to_dict(),
    }


def run_timer_probe(binary: Path) -> TilemTimerReport:
    """Run the direct programmable-timer and RTC matrix."""

    completed = run_probe(binary, ["--timer-probe"])
    report = parse_timer_report(completed.stdout)
    return TilemTimerReport(
        **{
            **report.to_dict(),
            "warnings": completed.stderr_lines,
            "binary_sha256": completed.binary_sha256,
        }
    )
