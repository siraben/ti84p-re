"""Pinned TilEm raw-link build helpers, typed report, and source oracle."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ti84re.link.port import (
    TILEM_INTERRUPT_LINK_ERROR,
    TILEM_INTERRUPT_LINK_IDLE,
    TILEM_INTERRUPT_LINK_READ,
    TILEM_LINK_ASSIST_READ_BYTE,
    TILEM_LINK_ASSIST_READ_ERROR,
    byte_drive_sequence,
    emulator_port_write,
    link_port_profile,
    port_read_value,
    raw_port_truth_table,
    tilem_assist_status,
)
from ti84re.emulators.tilem.core import TilemCoreError, run_probe
from ti84re.emulators.tilem.core import build_command as build_core_command
from ti84re.emulators.tilem.core import build_probe as build_core_probe
from ti84re.paths import PROBES

REPORT_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")
TilemLinkError = TilemCoreError


@dataclass(frozen=True)
class TilemLinkReport:
    """Complete direct-core raw-link, assist, and reset observations."""

    initial: tuple[int, ...]
    aux_stored: tuple[int, ...]
    aux_reads: tuple[int, ...]
    raw_reads: tuple[int, ...]
    raw_high_write: int
    raw_peer: tuple[int, ...]
    idle: tuple[int, ...]
    send_drives: tuple[int, ...]
    send: tuple[int, ...]
    receive: tuple[int, ...]
    error: tuple[int, ...]
    clock_delta: int
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
    """Return the direct-core link-probe compiler command."""

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
    """Validate pinned sources and compile the direct-core link probe."""

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
        raise TilemLinkError(f"invalid native TilEm link field {name}") from error


def _vector(fields: dict[str, str], name: str, length: int) -> tuple[int, ...]:
    try:
        values = tuple(int(value, 16) for value in fields[name].split(","))
    except (KeyError, ValueError) as error:
        raise TilemLinkError(f"invalid native TilEm link field {name}") from error
    if len(values) != length:
        raise TilemLinkError(
            f"native TilEm link field {name} must contain {length} values"
        )
    return values


def parse_link_report(line: str) -> TilemLinkReport:
    """Parse the complete one-line native TilEm link report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    if fields.get("mode") != "tilem-link-probe":
        raise TilemLinkError("native TilEm link report has an invalid mode")
    return TilemLinkReport(
        initial=_vector(fields, "initial", 9),
        aux_stored=_vector(fields, "aux_stored", 4),
        aux_reads=_vector(fields, "aux_reads", 5),
        raw_reads=_vector(fields, "raw_reads", 16),
        raw_high_write=_value(fields, "raw_high_write"),
        raw_peer=_vector(fields, "raw_peer", 2),
        idle=_vector(fields, "idle", 3),
        send_drives=_vector(fields, "send_drives", 8),
        send=_vector(fields, "send", 5),
        receive=_vector(fields, "receive", 4),
        error=_vector(fields, "error", 4),
        clock_delta=_value(fields, "clock_delta", base=10),
        reset=_vector(fields, "reset", 17),
    )


def expected_link_report() -> TilemLinkReport:
    """Derive every direct observation from reusable TilEm link models."""

    profile = link_port_profile("tilem")
    idle_status = tilem_assist_status(0, TILEM_INTERRUPT_LINK_IDLE)
    read_flags = TILEM_LINK_ASSIST_READ_BYTE
    read_status = tilem_assist_status(read_flags, TILEM_INTERRUPT_LINK_READ)
    error_flags = TILEM_LINK_ASSIST_READ_ERROR
    return TilemLinkReport(
        initial=(0x80, tilem_assist_status(0, 0), 0, 0, 0, 0, 0, 0, 0),
        aux_stored=(0x91, 0xA2, 0xB3, 0xC4),
        aux_reads=(tilem_assist_status(0, 0), 0, 0, 0, 0),
        raw_reads=raw_port_truth_table(),
        raw_high_write=emulator_port_write("tilem", 0xA6).port_read,
        raw_peer=(port_read_value(0, 1), int(profile.raw_activity_interrupt)),
        idle=(idle_status, 1, idle_status),
        send_drives=byte_drive_sequence(0xA5),
        send=(idle_status, 1, 0, idle_status, 0),
        receive=(read_status, 1, 0xA5, tilem_assist_status(0, 0)),
        error=(
            tilem_assist_status(error_flags, TILEM_INTERRUPT_LINK_ERROR),
            1,
            tilem_assist_status(error_flags, 0),
            error_flags,
        ),
        clock_delta=0,
        reset=(
            0x80,
            0x91,
            0xA2,
            0xB3,
            0xC4,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
            port_read_value(0, 1),
            tilem_assist_status(0, 0),
        ),
    )


def validate_link_report(report: TilemLinkReport) -> dict[str, object]:
    """Require direct observations implied by the pinned TilEm source model."""

    expected = expected_link_report()
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
        raise TilemLinkError(
            "native TilEm link report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "raw_port": "open-collector lines plus local latch in bits 4 and 5",
            "raw_activity_interrupt": True,
            "assist_ports": [8, 9, 10, 11, 12, 13],
            "assist_reset_enable": "0x80 disabled",
            "assist_send_order": "eight LSB-first four-phase handshakes",
            "assist_receive_order": "eight LSB-first four-phase handshakes",
            "port0d_read_acknowledgement": False,
            "port09_error_acknowledgement": "interrupt only; error flag remains",
            "reset_retains_auxiliary_registers": True,
            "reset_retains_external_lines": True,
            "modeled_latency_clocks": 0,
            "physical_scope": False,
        },
        "native": report.to_dict(),
    }


def run_link_probe(binary: Path) -> TilemLinkReport:
    """Run the direct raw-link and link-assist matrix."""

    completed = run_probe(binary, ["--link-probe"])
    report = parse_link_report(completed.stdout)
    return TilemLinkReport(
        **{
            **report.to_dict(),
            "warnings": completed.stderr_lines,
            "binary_sha256": completed.binary_sha256,
        }
    )
