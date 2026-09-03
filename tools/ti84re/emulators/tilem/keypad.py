"""Pinned TilEm keypad build helpers, typed report, and source oracle."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ti84re.hardware.keypad import on_transition_requests_interrupt, read_keypad_matrix
from ti84re.emulators.tilem.core import TilemCoreError, run_probe
from ti84re.emulators.tilem.core import build_command as build_core_command
from ti84re.emulators.tilem.core import build_probe as build_core_probe
from ti84re.paths import PROBES

REPORT_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")
GROUP_VALUES = (0x00, 0x7F, 0x80, 0xFE, 0xFF)
TILEM_KEYPAD_CASES = (
    ("release", 0xFF, ((0, 0),)),
    ("single", 0xFE, ((0, 0),)),
    ("unselected", 0xFE, ((1, 0),)),
    ("same_column", 0xFC, ((0, 0), (1, 0))),
    ("rectangle", 0xFE, ((0, 0), (1, 0), (1, 1))),
    (
        "transitive_chain",
        0xFE,
        ((0, 0), (1, 0), (1, 1), (2, 1), (2, 2)),
    ),
    ("column_7", 0xF7, ((3, 7),)),
    ("all_selected", 0x00, ((0, 0), (1, 0), (2, 1))),
    ("row_7", 0x7F, ((7, 0),)),
)
TilemKeypadError = TilemCoreError


@dataclass(frozen=True)
class TilemKeypadReport:
    """Complete direct-core keypad and ON-edge observations."""

    matrix: tuple[int, ...]
    group_readback: tuple[int, ...]
    scancode: tuple[int, ...]
    on: tuple[int, ...]
    reset: tuple[int, ...]
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
    """Return the direct-core keypad-probe compiler command."""

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
    """Validate pinned sources and compile the direct-core keypad probe."""

    return build_core_probe(
        source,
        [PROBES / "tilem/tilem_probe_support.c", adapter],
        output,
        cc=cc,
    )


def _vector(fields: dict[str, str], name: str, length: int) -> tuple[int, ...]:
    try:
        values = tuple(int(value, 16) for value in fields[name].split(","))
    except (KeyError, ValueError) as error:
        raise TilemKeypadError(f"invalid native TilEm keypad field {name}") from error
    if len(values) != length:
        raise TilemKeypadError(
            f"native TilEm keypad field {name} must contain {length} values"
        )
    return values


def parse_keypad_report(line: str) -> TilemKeypadReport:
    """Parse the complete one-line native TilEm keypad report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    if fields.get("mode") != "tilem-keypad-probe":
        raise TilemKeypadError("native TilEm keypad report has an invalid mode")
    return TilemKeypadReport(
        matrix=_vector(fields, "matrix", 9),
        group_readback=_vector(fields, "group_readback", 5),
        scancode=_vector(fields, "scancode", 8),
        on=_vector(fields, "on", 12),
        reset=_vector(fields, "reset", 12),
    )


def expected_keypad_report() -> TilemKeypadReport:
    """Derive every direct observation from the pinned TilEm source model."""

    matrix = tuple(
        read_keypad_matrix("TilEm", group, keys).active_low_value
        for _, group, keys in TILEM_KEYPAD_CASES
    )
    press_latches = on_transition_requests_interrupt("TilEm", "press")
    release_latches = on_transition_requests_interrupt("TilEm", "release")
    return TilemKeypadReport(
        matrix=matrix,
        group_readback=GROUP_VALUES,
        scancode=(0xFF, 0xFE, 1, 1, 0xFF, 0, 0, 0),
        on=(
            0xFF,
            0,
            1,
            0xFF,
            1,
            int(press_latches),
            0,
            0xFF,
            0,
            0x08 | int(release_latches),
            0x08,
            0,
        ),
        reset=(0xFF, 0xFF) + (0,) * 10,
    )


def validate_keypad_report(report: TilemKeypadReport) -> dict[str, object]:
    """Require direct observations implied by the pinned TilEm source model."""

    expected = expected_keypad_report()
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
        raise TilemKeypadError(
            "native TilEm keypad report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "cases": [
            {
                "name": name,
                "group_mask": group,
                "pressed_keys": keys,
                "active_low_value": value,
            }
            for (name, group, keys), value in zip(
                TILEM_KEYPAD_CASES, report.matrix, strict=True
            )
        ],
        "source_model": {
            "matrix_algorithm": "iterated transitive closure across eight rows",
            "group_byte_stored_exactly": True,
            "ordinary_scancodes": "1 through 64 map row-major",
            "invalid_scancodes_ignored": True,
            "on_matrix_separate": True,
            "on_press_interrupt": True,
            "on_release_interrupt": True,
            "duplicate_transitions_idempotent": True,
            "reset_clears_keypad_and_on_policy": True,
            "physical_scope": False,
        },
        "native": report.to_dict(),
    }


def run_keypad_probe(binary: Path) -> TilemKeypadReport:
    """Run the direct keypad and ON-edge matrix."""

    completed = run_probe(binary, ["--keypad-probe"])
    report = parse_keypad_report(completed.stdout)
    return TilemKeypadReport(
        **{
            **report.to_dict(),
            "warnings": completed.stderr_lines,
            "binary_sha256": completed.binary_sha256,
        }
    )
