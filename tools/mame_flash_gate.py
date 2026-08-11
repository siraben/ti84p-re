"""Typed report and complete-image oracle for the MAME Flash-gate probe."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from mame_runtime import MameRuntimeError, file_sha256, parse_report_fields

FLASH_SIZE = 0x100000
PROGRAM_TARGET = 0x20100
MAME_FLASH_GATE_IMAGE_SHA256 = (
    "2fd21a6b139a641d40a71a0e68df492e4555e79c6f1cf44858b4dcfd9158bbeb"
)


@dataclass(frozen=True)
class MameFlashGateCase:
    """One CPU-mapped program result and port-`0x02` gate status."""

    name: str
    gate_status: int
    cpu_byte: int
    physical_byte: int


@dataclass(frozen=True)
class MameFlashGateReport:
    """Complete CPU-mapped Flash-gate matrix."""

    machine: str
    version: str
    mapped_page: int
    initial_byte: int
    cases: tuple[MameFlashGateCase, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def parse_flash_gate_report(output: str) -> MameFlashGateReport:
    """Parse identity, mapping, and gate-transition report lines."""

    lines = output.splitlines()
    try:
        identity_line = next(
            line for line in lines if line.startswith("MAME_FLASH_GATE identity ")
        )
        mapping_line = next(
            line for line in lines if line.startswith("MAME_FLASH_GATE mapping ")
        )
    except StopIteration as error:
        raise MameRuntimeError(
            "MAME Flash-gate output omits identity or mapping"
        ) from error

    case_fields = [
        parse_report_fields(line)
        for line in lines
        if line.startswith("MAME_FLASH_GATE case=")
    ]
    expected_names = ("locked", "unlock_between", "relock_between")
    if tuple(fields.get("case") for fields in case_fields) != expected_names:
        raise MameRuntimeError("MAME Flash-gate output has incomplete cases")

    identity = parse_report_fields(identity_line)
    mapping = parse_report_fields(mapping_line)
    required_identity = {"machine", "version"}
    required_mapping = {"page", "initial"}
    if missing := sorted(required_identity - identity.keys()):
        raise MameRuntimeError("MAME Flash-gate identity omits " + ", ".join(missing))
    if missing := sorted(required_mapping - mapping.keys()):
        raise MameRuntimeError("MAME Flash-gate mapping omits " + ", ".join(missing))
    try:
        cases = tuple(
            MameFlashGateCase(
                name=fields["case"],
                gate_status=int(fields["gate_status"], 16),
                cpu_byte=int(fields["cpu"], 16),
                physical_byte=int(fields["physical"], 16),
            )
            for fields in case_fields
        )
        return MameFlashGateReport(
            machine=identity["machine"],
            version=identity["version"],
            mapped_page=int(mapping["page"], 16),
            initial_byte=int(mapping["initial"], 16),
            cases=cases,
        )
    except (KeyError, ValueError) as error:
        raise MameRuntimeError("invalid numeric MAME Flash-gate field") from error


def expected_flash_gate_report() -> MameFlashGateReport:
    """Return exact observations implied by the MAME 0.287 TI driver."""

    return MameFlashGateReport(
        machine="ti84pv3",
        version="0.287",
        mapped_page=0x08,
        initial_byte=0xFF,
        cases=(
            MameFlashGateCase("locked", 0xC3, 0x50, 0x50),
            MameFlashGateCase("unlock_between", 0xC7, 0xD0, 0xD0),
            MameFlashGateCase("relock_between", 0xC3, 0x20, 0x20),
        ),
    )


def validate_flash_gate_report(report: MameFlashGateReport) -> dict[str, object]:
    """Check CPU-visible gate observations against the pinned source model."""

    if report != expected_flash_gate_report():
        raise MameRuntimeError(
            "MAME Flash-gate report disagrees with the 0.287 source model"
        )
    return {
        "source_model": {
            "gate_write_port": 0x14,
            "gate_status_port": 0x02,
            "locked_status": 0xC3,
            "unlocked_status": 0xC7,
            "gate_checked_by_memory_write": False,
            "cpu_window": [0x4000, 0x8000],
            "physical_page": 0x08,
        },
        "native": report.to_dict(),
    }


def modeled_flash_gate_image(source: bytes) -> bytes:
    """Apply the final CPU-mapped byte-program mutation from the gate probe."""

    if len(source) != FLASH_SIZE:
        raise MameRuntimeError(
            f"MAME Flash source must be {FLASH_SIZE} bytes, found {len(source)}"
        )
    expected = bytearray(source)
    expected[PROGRAM_TARGET] = 0x20
    return bytes(expected)


def validate_flash_gate_image(
    source_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Compare MAME's saved Flash with the complete one-byte mutation model."""

    source = source_path.read_bytes()
    output = output_path.read_bytes()
    expected = modeled_flash_gate_image(source)
    if output != expected:
        differing = [
            index
            for index, (modeled, observed) in enumerate(zip(expected, output))
            if modeled != observed
        ]
        if len(output) != len(expected):
            differing.append(min(len(output), len(expected)))
        raise MameRuntimeError(
            "MAME Flash-gate image disagrees; first offsets "
            + ", ".join(f"0x{offset:X}" for offset in differing[:16])
        )
    output_sha256 = file_sha256(output_path)
    if output_sha256 != MAME_FLASH_GATE_IMAGE_SHA256:
        raise MameRuntimeError("MAME Flash-gate image SHA-256 disagrees")
    changed_offsets = [
        index
        for index, (before, after) in enumerate(zip(source, output))
        if before != after
    ]
    return {
        "output_sha256": output_sha256,
        "modeled_sha256": sha256(expected).hexdigest(),
        "changed_byte_count": len(changed_offsets),
        "changed_offsets": changed_offsets,
    }
