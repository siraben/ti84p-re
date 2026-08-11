"""Pinned TilEm battery-comparator build helpers and source oracle."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from battery_hardware import SELECTORS, battery_level, comparator_samples
from tilem_core import TilemCoreError, run_probe
from tilem_core import build_command as build_core_command
from tilem_core import build_probe as build_core_probe

REPORT_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")
TOOLS = Path(__file__).resolve().parent
VOLTAGES_TENTHS = tuple(range(30, 46))
TilemBatteryError = TilemCoreError


@dataclass(frozen=True)
class TilemBatteryReport:
    """Complete direct-core TilEm comparator sweep."""

    reset_battery: int
    reset_port4: int
    reset_status: int
    voltages: tuple[int, ...]
    masks: tuple[int, ...]
    levels: tuple[int, ...]
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
    """Return the direct-core battery-probe compiler command."""

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
    """Validate pinned sources and compile the direct-core battery probe."""

    return build_core_probe(
        source,
        [TOOLS / "tilem_probe_support.c", adapter],
        output,
        cc=cc,
    )


def _value(fields: dict[str, str], name: str, *, base: int) -> int:
    try:
        return int(fields[name], base)
    except (KeyError, ValueError) as error:
        raise TilemBatteryError(
            f"invalid native TilEm battery field {name}"
        ) from error


def _vector(
    fields: dict[str, str], name: str, length: int, *, base: int
) -> tuple[int, ...]:
    try:
        values = tuple(int(value, base) for value in fields[name].split(","))
    except (KeyError, ValueError) as error:
        raise TilemBatteryError(
            f"invalid native TilEm battery field {name}"
        ) from error
    if len(values) != length:
        raise TilemBatteryError(
            f"native TilEm battery field {name} must contain {length} values"
        )
    return values


def parse_battery_report(line: str) -> TilemBatteryReport:
    """Parse the complete one-line native TilEm comparator report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    if fields.get("mode") != "tilem-battery-probe":
        raise TilemBatteryError("native TilEm battery report has an invalid mode")
    return TilemBatteryReport(
        reset_battery=_value(fields, "reset_battery", base=10),
        reset_port4=_value(fields, "reset_port4", base=16),
        reset_status=_value(fields, "reset_status", base=16),
        voltages=_vector(fields, "voltages", len(VOLTAGES_TENTHS), base=10),
        masks=_vector(fields, "masks", len(VOLTAGES_TENTHS), base=16),
        levels=_vector(fields, "levels", len(VOLTAGES_TENTHS), base=10),
    )


def expected_battery_report() -> TilemBatteryReport:
    """Derive the direct sweep from the shared threshold and ROM models."""

    masks = []
    levels = []
    for voltage in VOLTAGES_TENTHS:
        samples = comparator_samples(voltage)
        masks.append(
            sum(
                (1 << index) if samples[selector] else 0
                for index, selector in enumerate(SELECTORS)
            )
        )
        levels.append(battery_level(samples))
    return TilemBatteryReport(
        reset_battery=60,
        reset_port4=0x07,
        reset_status=0xE3,
        voltages=VOLTAGES_TENTHS,
        masks=tuple(masks),
        levels=tuple(levels),
    )


def validate_battery_report(report: TilemBatteryReport) -> dict[str, object]:
    """Require direct observations implied by the pinned TilEm source model."""

    expected = expected_battery_report()
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
        raise TilemBatteryError(
            "native TilEm battery report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "battery_units_volts": 0.1,
            "selector_threshold_tenths": [33, 39, 36, 43],
            "comparator_relation": "battery >= threshold",
            "reachable_rom_levels": sorted(set(report.levels)),
            "unreachable_rom_levels": sorted(set(range(5)) - set(report.levels)),
            "physical_scope": False,
        },
        "native": report.to_dict(),
    }


def run_battery_probe(binary: Path) -> TilemBatteryReport:
    """Run the direct comparator sweep."""

    completed = run_probe(binary, ["--battery-probe"])
    report = parse_battery_report(completed.stdout)
    return TilemBatteryReport(
        **{
            **report.to_dict(),
            "warnings": completed.stderr_lines,
            "binary_sha256": completed.binary_sha256,
        }
    )
