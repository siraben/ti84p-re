"""Typed report and oracle for MAME's TI-84 Plus raw-link implementation."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from link_port import (
    emulator_write_sequence,
    link_port_profile,
    mame_plus_port_read,
)
from mame_runtime import MAME_VERSION, MameRuntimeError, parse_report_fields

RAW_WRITES = (0x00, 0x01, 0x02, 0x03, 0x14, 0x28, 0x3C)
PEER_DRIVES = (0x00, 0x01, 0x02, 0x03)
ASSIST_PORTS = tuple(range(0x08, 0x0E))
ZERO_ASSIST_BLOCK = (0,) * len(ASSIST_PORTS)


@dataclass(frozen=True)
class MameLinkRawCase:
    """One port-`0x00` write, CPU readback, and connector output state."""

    write: int
    read: int
    tip_out: int
    ring_out: int


@dataclass(frozen=True)
class MameLinkPeerCase:
    """One injected peer pull-low mask and CPU-visible port read."""

    pull_low: int
    read: int


@dataclass(frozen=True)
class MameLinkReport:
    """Raw write, peer-input, and advertised-assist observations."""

    machine: str
    version: str
    raw_cases: tuple[MameLinkRawCase, ...]
    peer_cases: tuple[MameLinkPeerCase, ...]
    status: int
    assist_initial: tuple[int, ...]
    assist_patterned: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_assist_block(value: str) -> tuple[int, ...]:
    if len(value) != 2 * len(ASSIST_PORTS):
        raise MameRuntimeError("MAME link-assist block must contain six bytes")
    try:
        return tuple(
            int(value[index : index + 2], 16)
            for index in range(0, 2 * len(ASSIST_PORTS), 2)
        )
    except ValueError as error:
        raise MameRuntimeError(
            "invalid hexadecimal MAME link-assist block"
        ) from error


def parse_mame_link_report(output: str) -> MameLinkReport:
    """Parse the complete raw, peer, and advertised-assist native report."""

    lines = output.splitlines()
    identity_lines = [
        line for line in lines if line.startswith("MAME_LINK identity ")
    ]
    assist_lines = [line for line in lines if line.startswith("MAME_LINK assist ")]
    if len(identity_lines) != 1 or len(assist_lines) != 1:
        raise MameRuntimeError("MAME link output omits identity or assist report")
    raw_fields = [
        parse_report_fields(line)
        for line in lines
        if line.startswith("MAME_LINK raw ")
    ]
    peer_fields = [
        parse_report_fields(line)
        for line in lines
        if line.startswith("MAME_LINK peer ")
    ]
    try:
        raw_order = tuple(
            int(fields.get("write", "-1"), 16) for fields in raw_fields
        )
        peer_order = tuple(
            int(fields.get("pull_low", "-1"), 16) for fields in peer_fields
        )
    except ValueError as error:
        raise MameRuntimeError("invalid MAME link case selector") from error
    if raw_order != RAW_WRITES:
        raise MameRuntimeError("MAME link output has incomplete raw cases")
    if peer_order != PEER_DRIVES:
        raise MameRuntimeError("MAME link output has incomplete peer cases")

    identity = parse_report_fields(identity_lines[0])
    assist = parse_report_fields(assist_lines[0])
    try:
        return MameLinkReport(
            machine=identity["machine"],
            version=identity["version"],
            raw_cases=tuple(
                MameLinkRawCase(
                    write=int(fields["write"], 16),
                    read=int(fields["read"], 16),
                    tip_out=int(fields["tip_out"], 10),
                    ring_out=int(fields["ring_out"], 10),
                )
                for fields in raw_fields
            ),
            peer_cases=tuple(
                MameLinkPeerCase(
                    pull_low=int(fields["pull_low"], 16),
                    read=int(fields["read"], 16),
                )
                for fields in peer_fields
            ),
            status=int(assist["status"], 16),
            assist_initial=_parse_assist_block(assist["initial"]),
            assist_patterned=_parse_assist_block(assist["patterned"]),
        )
    except KeyError as error:
        raise MameRuntimeError(
            f"MAME link report omits field {error.args[0]}"
        ) from error
    except MameRuntimeError:
        raise
    except ValueError as error:
        raise MameRuntimeError("invalid numeric MAME link report field") from error


def expected_mame_link_report() -> MameLinkReport:
    """Return exact observations derived from the reusable MAME link model."""

    writes = emulator_write_sequence("mame", RAW_WRITES)
    return MameLinkReport(
        machine="ti84pv3",
        version=MAME_VERSION,
        raw_cases=tuple(
            MameLinkRawCase(
                write=result.write_value,
                read=result.port_read,
                tip_out=0 if result.connector_drive & 1 else 1,
                ring_out=0 if result.connector_drive & 2 else 1,
            )
            for result in writes
        ),
        peer_cases=tuple(
            MameLinkPeerCase(
                pull_low=peer,
                read=mame_plus_port_read(0, peer),
            )
            for peer in PEER_DRIVES
        ),
        status=0xC3,
        assist_initial=ZERO_ASSIST_BLOCK,
        assist_patterned=ZERO_ASSIST_BLOCK,
    )


def validate_mame_link_report(report: MameLinkReport) -> dict[str, object]:
    """Require the native values implied by MAME 0.287's pinned link model."""

    expected = expected_mame_link_report()
    if report != expected:
        raise MameRuntimeError(
            "MAME link report disagrees with the 0.287 source model"
        )
    profile = link_port_profile("mame")
    return {
        "source_model": {
            "raw_handler": "ti8x_plus_serial_r/ti8x_plus_serial_w",
            "normal_raw_writes": [0, 1, 2, 3],
            "normal_connector_drive": 0,
            "connector_control_pairs": {"tip": [2, 4], "ring": [3, 5]},
            "peer_input_injection": "linkport m_tip_in and m_ring_in save items",
            "advertised_assist_status": 0xC3,
            "mapped_assist_ports": list(profile.mapped_assist_ports),
            "assist_operational": profile.assist_operational,
        },
        "native": report.to_dict(),
    }
