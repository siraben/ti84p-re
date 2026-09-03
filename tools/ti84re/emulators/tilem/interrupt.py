"""Pinned TilEm interrupt build helpers, typed report, and source oracle."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ti84re.hardware.interrupt_controller import TilemLegacyInterruptState
from ti84re.emulators.tilem.core import TilemCoreError, run_probe
from ti84re.emulators.tilem.core import build_command as build_core_command
from ti84re.emulators.tilem.core import build_probe as build_core_probe
from ti84re.paths import PROBES

REPORT_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")
MASK_VALUES = (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0xFF)
TilemInterruptError = TilemCoreError


@dataclass(frozen=True)
class TilemInterruptReport:
    """Complete direct-core legacy-interrupt observations."""

    initial_reset: tuple[int, ...]
    reset: tuple[int, ...]
    reset_synced: tuple[int, ...]
    mask_readback: tuple[int, ...]
    mask_on: tuple[int, ...]
    mask_power: tuple[int, ...]
    mask_link: tuple[int, ...]
    mask_no_halt: tuple[int, ...]
    mask_agree: bool
    ack03_status: tuple[int, ...]
    ack03_other: tuple[int, ...]
    ack02_status: tuple[int, ...]
    ack02_other: tuple[int, ...]
    on_status: tuple[int, ...]
    timer_status: tuple[int, ...]
    timer_before: tuple[int, ...]
    timer_after: tuple[int, ...]
    timer_periods: tuple[int, ...]
    link_status: tuple[int, ...]
    programmable: tuple[int, ...]
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
    """Return the direct-core interrupt-probe compiler command."""

    return build_core_command(
        source,
        [PROBES / "tilem/tilem_probe_support.c", adapter],
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
    """Validate pinned sources and compile the direct-core interrupt probe."""

    return build_core_probe(
        source,
        [PROBES / "tilem/tilem_probe_support.c", adapter],
        output,
        cc=cc,
    )


def _vector(
    fields: dict[str, str], name: str, length: int, *, base: int
) -> tuple[int, ...]:
    try:
        values = tuple(int(value, base) for value in fields[name].split(","))
    except (KeyError, ValueError) as error:
        raise TilemInterruptError(
            f"invalid native TilEm interrupt field {name}"
        ) from error
    if len(values) != length:
        raise TilemInterruptError(
            f"native TilEm interrupt field {name} must contain {length} values"
        )
    return values


def parse_interrupt_report(line: str) -> TilemInterruptReport:
    """Parse the complete one-line native TilEm interrupt report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    if fields.get("mode") != "tilem-interrupt-probe":
        raise TilemInterruptError("native TilEm interrupt report has an invalid mode")
    try:
        mask_agree = int(fields["mask_agree"], 0)
    except (KeyError, ValueError) as error:
        raise TilemInterruptError(
            "invalid native TilEm interrupt field mask_agree"
        ) from error
    if mask_agree not in (0, 1):
        raise TilemInterruptError("native TilEm mask_agree must be zero or one")
    return TilemInterruptReport(
        initial_reset=_vector(fields, "initial_reset", 8, base=16),
        reset=_vector(fields, "reset", 8, base=16),
        reset_synced=_vector(fields, "reset_synced", 8, base=16),
        mask_readback=_vector(fields, "mask_readback", 7, base=16),
        mask_on=_vector(fields, "mask_on", 7, base=16),
        mask_power=_vector(fields, "mask_power", 7, base=16),
        mask_link=_vector(fields, "mask_link", 7, base=16),
        mask_no_halt=_vector(fields, "mask_no_halt", 7, base=16),
        mask_agree=bool(mask_agree),
        ack03_status=_vector(fields, "ack03_status", 7, base=16),
        ack03_other=_vector(fields, "ack03_other", 7, base=16),
        ack02_status=_vector(fields, "ack02_status", 7, base=16),
        ack02_other=_vector(fields, "ack02_other", 7, base=16),
        on_status=_vector(fields, "on_status", 9, base=16),
        timer_status=_vector(fields, "timer_status", 7, base=16),
        timer_before=_vector(fields, "timer_before", 3, base=10),
        timer_after=_vector(fields, "timer_after", 3, base=10),
        timer_periods=_vector(fields, "timer_periods", 12, base=10),
        link_status=_vector(fields, "link_status", 5, base=16),
        programmable=_vector(fields, "programmable", 9, base=16),
    )


def expected_interrupt_report() -> TilemInterruptReport:
    """Derive the complete native report from pinned TilEm's source policy."""

    reset = TilemLegacyInterruptState()
    seeded = replace(
        reset,
        legacy_pending=0x17,
        programmable_finished=0xE0,
    )
    ack03 = tuple(seeded.write_port03(value).status for value in MASK_VALUES)
    ack02 = tuple(seeded.write_port02(value).status for value in MASK_VALUES)

    on = reset.sample_on(True)
    on_values = [on.status]
    on = on.write_port03(0x01)
    on_values.append(on.status)
    on = on.sample_on(False)
    on_values.append(on.status)
    on = on.write_port02(0xFE)
    on_values.append(on.status)
    on = on.sample_on(True)
    on_values.append(on.status)
    on = on.write_port02(0xFE)
    on_values.append(on.status)
    on = on.sample_on(False)
    on_values.append(on.status)
    on = on.write_port03(0)
    on_values.append(on.status)
    on_values.append(on.sample_on(True).status)

    disabled = reset.write_port03(0)
    timer_values = [
        disabled.standard_timer_tick(1).status,
        disabled.standard_timer_tick(2).status,
        disabled.standard_timer_tick(2).status,
    ]
    enabled = reset.write_port03(0x06)
    timer_values.extend(
        (
            enabled.standard_timer_tick(1).status,
            enabled.standard_timer_tick(2).status,
            enabled.standard_timer_tick(2).status,
            enabled.standard_timer_tick(2).standard_timer_tick(1).status,
        )
    )

    link = reset.write_port03(0x10).link_transition()
    link_values = [link.status]
    link = link.write_port02(0xEF)
    link_values.append(link.status)
    link = link.link_transition()
    link_values.append(link.status)
    link = link.write_port03(0)
    link_values.append(link.status)
    link_values.append(link.link_transition().status)

    return TilemInterruptReport(
        initial_reset=(0x0B, 0x08, 0, 1, 0, 0, 0, 0),
        reset=(0x0B, 0x08, 0, 0, 0, 0, 0, 0),
        reset_synced=(0x0B, 0x08, 1, 1, 0, 0, 0, 0),
        mask_readback=MASK_VALUES,
        mask_on=tuple(int(bool(value & 0x01)) for value in MASK_VALUES),
        mask_power=tuple(int(bool(value & 0x08)) for value in MASK_VALUES),
        mask_link=tuple(int(bool(value & 0x10)) for value in MASK_VALUES),
        mask_no_halt=tuple(int(not bool(value & 0x06)) for value in MASK_VALUES),
        mask_agree=True,
        ack03_status=ack03,
        ack03_other=(0x38,) * len(MASK_VALUES),
        ack02_status=ack02,
        ack02_other=(0x38,) * len(MASK_VALUES),
        on_status=tuple(on_values),
        timer_status=tuple(timer_values),
        timer_before=(1600, 1300, 1000),
        timer_after=(1600, 1300, 1000),
        timer_periods=(1953,) * 3 + (4395,) * 3 + (6836,) * 3 + (9277,) * 3,
        link_status=tuple(link_values),
        programmable=(0x302, 0, 0x28, 0x102, 0x08, 0x28, 0x302, 0x08, 0x28),
    )


def validate_interrupt_report(report: TilemInterruptReport) -> dict[str, object]:
    """Require direct observations implied by the pinned TilEm source model."""

    expected = expected_interrupt_report()
    comparable = replace(report, warnings=(), binary_sha256="")
    if comparable != expected:
        disagreements = {
            name: {
                "expected": expected.to_dict()[name],
                "observed": comparable.to_dict()[name],
            }
            for name in expected.to_dict()
            if expected.to_dict()[name] != comparable.to_dict()[name]
        }
        raise TilemInterruptError(
            "native TilEm interrupt report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "port03_read": "complete stored byte",
            "port04_read": "live ON level, four legacy latches, and three completion flags",
            "port02_write": "clear each legacy source whose corresponding bit is zero",
            "port03_write": "store all bits, clear disabled legacy sources, and update internal policy",
            "on_edges": "both press and release transitions when internally enabled",
            "standard_timer_period_us": [1953, 4395, 6836, 9277],
            "timer2_callbacks": 2,
            "programmable_halt_gate": "standard-timer mask bits jointly control all three timers",
            "reset_mismatch": "port 0x03 reads 0x0B before its internal ON enable is synchronized",
            "physical_scope": False,
        },
        "native": report.to_dict(),
    }


def run_interrupt_probe(binary: Path) -> TilemInterruptReport:
    """Run the direct interrupt matrix through a built probe."""

    completed = run_probe(binary, ["--interrupt-probe"])
    report = parse_interrupt_report(completed.stdout)
    return TilemInterruptReport(
        **{
            **report.to_dict(),
            "warnings": completed.stderr_lines,
            "binary_sha256": completed.binary_sha256,
        }
    )
