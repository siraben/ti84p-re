"""Pinned TilEm MD5-assist build helpers, typed report, and source oracle."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ti84re.hardware.md5 import md5_edge_values
from ti84re.emulators.tilem.core import TilemCoreError, run_probe
from ti84re.emulators.tilem.core import build_command as build_core_command
from ti84re.emulators.tilem.core import build_probe as build_core_probe
from ti84re.paths import PROBES

REPORT_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")
TilemMd5Error = TilemCoreError


@dataclass(frozen=True)
class TilemMd5Report:
    """Complete direct-core MD5-assist edge observations."""

    reset_operand_reads: tuple[int, ...]
    reset_result: int
    one_write_result: int
    three_write_result: int
    four_write_result: int
    five_write_result: int
    masked_controls: tuple[int, ...]
    masked_control_result: int
    loaded_operand_reads: tuple[int, ...]
    before_mutation_result: int
    after_mutation_result: int
    mixed_result: int
    clock_delta: int
    reset_state: tuple[int, ...]
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
    """Return the direct-core MD5-probe compiler command."""

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
    """Validate pinned sources and compile the direct-core MD5 probe."""

    return build_core_probe(
        source,
        [PROBES / "tilem/tilem_probe_support.c", adapter],
        output,
        cc=cc,
    )


def _value(fields: dict[str, str], name: str, *, base: int = 16) -> int:
    try:
        return int(fields[name], base)
    except (KeyError, ValueError) as error:
        raise TilemMd5Error(f"invalid native TilEm MD5 field {name}") from error


def _vector(
    fields: dict[str, str], name: str, length: int, *, base: int = 16
) -> tuple[int, ...]:
    try:
        values = tuple(int(value, base) for value in fields[name].split(","))
    except (KeyError, ValueError) as error:
        raise TilemMd5Error(f"invalid native TilEm MD5 field {name}") from error
    if len(values) != length:
        raise TilemMd5Error(
            f"native TilEm MD5 field {name} must contain {length} values"
        )
    return values


def parse_md5_report(line: str) -> TilemMd5Report:
    """Parse the complete one-line native TilEm MD5 report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    if fields.get("mode") != "tilem-md5-probe":
        raise TilemMd5Error("native TilEm MD5 report has an invalid mode")
    return TilemMd5Report(
        reset_operand_reads=_vector(fields, "reset_operand_reads", 4),
        reset_result=_value(fields, "reset_result"),
        one_write_result=_value(fields, "one_write_result"),
        three_write_result=_value(fields, "three_write_result"),
        four_write_result=_value(fields, "four_write_result"),
        five_write_result=_value(fields, "five_write_result"),
        masked_controls=_vector(fields, "masked_controls", 2),
        masked_control_result=_value(fields, "masked_control_result"),
        loaded_operand_reads=_vector(fields, "loaded_operand_reads", 4),
        before_mutation_result=_value(fields, "before_mutation_result"),
        after_mutation_result=_value(fields, "after_mutation_result"),
        mixed_result=_value(fields, "mixed_result"),
        clock_delta=_value(fields, "clock_delta", base=10),
        reset_state=_vector(fields, "reset_state", 9),
    )


def expected_md5_report() -> TilemMd5Report:
    """Derive every direct observation from the shared MD5 edge model."""

    values = md5_edge_values()
    return TilemMd5Report(
        reset_operand_reads=values["reset_operand_reads"],
        reset_result=values["reset_result"],
        one_write_result=values["one_write_result"],
        three_write_result=values["three_write_result"],
        four_write_result=values["four_write_result"],
        five_write_result=values["five_write_result"],
        masked_controls=(0x1F, 0x03),
        masked_control_result=values["masked_control_result"],
        loaded_operand_reads=values["loaded_operand_reads"],
        before_mutation_result=values["before_mutation_result"],
        after_mutation_result=values["after_mutation_result"],
        mixed_result=values["mixed_result"],
        clock_delta=values["tstates"],
        reset_state=(0,) * 9,
    )


def validate_md5_report(report: TilemMd5Report) -> dict[str, object]:
    """Require direct observations implied by the pinned TilEm source model."""

    expected = expected_md5_report()
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
        raise TilemMd5Error(
            "native TilEm MD5 report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "operand_register": "(old >> 8) | (byte << 24)",
            "shift_mask": 0x1F,
            "mode_mask": 0x03,
            "recompute_on_each_result_read": True,
            "operand_read_value": 0,
            "modeled_latency_clocks": 0,
            "reset_clears_all_fields": True,
            "shift_zero_c_portability": "source evaluates a 32-bit shift by 32",
            "physical_scope": False,
        },
        "native": report.to_dict(),
    }


def run_md5_probe(binary: Path) -> TilemMd5Report:
    """Run the direct MD5-assist edge matrix."""

    completed = run_probe(binary, ["--md5-probe"])
    report = parse_md5_report(completed.stdout)
    return TilemMd5Report(
        **{
            **report.to_dict(),
            "warnings": completed.stderr_lines,
            "binary_sha256": completed.binary_sha256,
        }
    )
