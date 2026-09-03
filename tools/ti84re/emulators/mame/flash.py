"""Typed report, image model, and oracle for the MAME Flash probe."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from ti84re.emulators.mame.runtime import (
    MAME_VERSION,
    MameRuntimeError,
    file_sha256,
    parse_report_fields,
)

MAME_BINARY_SHA256 = "fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91"
MAME_FLASH_IMAGE_SHA256 = (
    "1dc4eec678252588df24118e96603b6c80806b8b9ea8e0e12b2169ac6aae3935"
)

FLASH_SIZE = 0x100000
PROGRAM_TARGET = 0x20100
TOP_SECTOR_START = 0xF8000
TOP_SECTOR_END = 0xFA000

@dataclass(frozen=True)
class MameFlashReport:
    """Stable fields emitted by the MAME 0.287 Flash Lua probe."""

    machine: str
    version: str
    initial_target: int
    autoselect: tuple[int, ...]
    legal_stored: int
    illegal_stored: int
    partial_reset_byte: int
    cfi_byte: int
    fast_program_stored: int
    fast_exit_id: int
    fast_exit_array: int
    top_before: int
    adjacent_before: int
    boot_before: int
    outside_before: int
    busy_selected: tuple[int, ...]
    busy_adjacent: int
    busy_boot: int
    busy_outside: int
    complete_frame: int
    complete_selected: int
    complete_adjacent: int
    complete_boot: int
    complete_outside: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _hex_vector(value: str, length: int, name: str) -> tuple[int, ...]:
    values = tuple(int(item, 16) for item in value.split(","))
    if len(values) != length:
        raise ValueError(f"{name} must contain {length} values")
    return values


def parse_flash_report(output: str) -> MameFlashReport:
    """Parse identity, immediate, and completed-timer MAME Flash lines."""

    lines = output.splitlines()
    try:
        identity_line = next(line for line in lines if line.startswith("MAME_FLASH identity "))
        immediate_line = next(
            line for line in lines if line.startswith("MAME_FLASH immediate ")
        )
        complete_line = next(line for line in lines if line.startswith("MAME_FLASH complete "))
    except StopIteration as error:
        raise MameRuntimeError("MAME Flash output omits a required report line") from error

    identity = parse_report_fields(identity_line)
    immediate = parse_report_fields(immediate_line)
    complete = parse_report_fields(complete_line)
    immediate_names = {
        "initial_target",
        "autoselect",
        "legal_stored",
        "illegal_stored",
        "partial_reset_byte",
        "cfi_byte",
        "fast_program_stored",
        "fast_exit_id",
        "fast_exit_array",
        "top_before",
        "adjacent_before",
        "boot_before",
        "outside_before",
        "busy_selected",
        "busy_adjacent",
        "busy_boot",
        "busy_outside",
    }
    complete_names = {"frame", "selected", "adjacent", "boot", "outside"}
    missing = sorted(
        {"machine", "version"} - identity.keys()
        | immediate_names - immediate.keys()
        | complete_names - complete.keys()
    )
    if missing:
        raise MameRuntimeError("MAME Flash report omits " + ", ".join(missing))
    try:
        return MameFlashReport(
            machine=identity["machine"],
            version=identity["version"],
            initial_target=int(immediate["initial_target"], 16),
            autoselect=_hex_vector(immediate["autoselect"], 4, "autoselect"),
            legal_stored=int(immediate["legal_stored"], 16),
            illegal_stored=int(immediate["illegal_stored"], 16),
            partial_reset_byte=int(immediate["partial_reset_byte"], 16),
            cfi_byte=int(immediate["cfi_byte"], 16),
            fast_program_stored=int(immediate["fast_program_stored"], 16),
            fast_exit_id=int(immediate["fast_exit_id"], 16),
            fast_exit_array=int(immediate["fast_exit_array"], 16),
            top_before=int(immediate["top_before"], 16),
            adjacent_before=int(immediate["adjacent_before"], 16),
            boot_before=int(immediate["boot_before"], 16),
            outside_before=int(immediate["outside_before"], 16),
            busy_selected=_hex_vector(
                immediate["busy_selected"], 2, "busy_selected"
            ),
            busy_adjacent=int(immediate["busy_adjacent"], 16),
            busy_boot=int(immediate["busy_boot"], 16),
            busy_outside=int(immediate["busy_outside"], 16),
            complete_frame=int(complete["frame"], 10),
            complete_selected=int(complete["selected"], 16),
            complete_adjacent=int(complete["adjacent"], 16),
            complete_boot=int(complete["boot"], 16),
            complete_outside=int(complete["outside"], 16),
        )
    except ValueError as error:
        raise MameRuntimeError("invalid numeric MAME Flash report field") from error


def expected_report_values() -> dict[str, object]:
    """Return exact observations implied by the MAME 0.287 source model."""

    return {
        "machine": "ti84pv3",
        "version": MAME_VERSION,
        "initial_target": 0xFF,
        "autoselect": (0x01, 0xDA, 0x00, 0x00),
        "legal_stored": 0x50,
        "illegal_stored": 0xD0,
        "partial_reset_byte": 0xD0,
        "cfi_byte": 0xD0,
        "fast_program_stored": 0xD0,
        "fast_exit_id": 0x01,
        "fast_exit_array": 0xD0,
        "top_before": 0x00,
        "adjacent_before": 0xFF,
        "boot_before": 0x3E,
        "outside_before": 0x9F,
        "busy_selected": (0x4C, 0x08),
        "busy_adjacent": 0x4C,
        "busy_boot": 0x08,
        "busy_outside": 0x9F,
        "complete_frame": 20,
        "complete_selected": 0xFF,
        "complete_adjacent": 0xFF,
        "complete_boot": 0x3E,
        "complete_outside": 0x9F,
    }


def validate_flash_report(report: MameFlashReport) -> dict[str, object]:
    """Check runtime observations against the pinned MAME source model."""

    expected = expected_report_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise MameRuntimeError(
            "MAME Flash report disagrees with the 0.287 model: "
            + repr(disagreements)
        )
    return {
        "source_model": {
            "program_rule": "stored = requested",
            "autoselect_offsets": [0, 1, 2, 4],
            "autoselect_values": [0x01, 0xDA, 0, 0],
            "fast_program_for_amd_29f800t": False,
            "selected_erase_range": [TOP_SECTOR_START, TOP_SECTOR_END],
            "busy_read_range": [TOP_SECTOR_START, 0x108000],
            "direct_seed_scope": (
                "Lua calls the membank0 mapped Flash interface; no TI-OS Flash "
                "routine or physical device executes"
            ),
        },
        "native": observed,
    }


def modeled_flash_image(source: bytes) -> bytes:
    """Apply the accepted program and sector-erase mutations from the probe."""

    if len(source) != FLASH_SIZE:
        raise MameRuntimeError(
            f"MAME Flash fixture must be {FLASH_SIZE} bytes, found {len(source)}"
        )
    expected = bytearray(source)
    expected[PROGRAM_TARGET] = 0xD0
    expected[TOP_SECTOR_START:TOP_SECTOR_END] = b"\xFF" * (
        TOP_SECTOR_END - TOP_SECTOR_START
    )
    return bytes(expected)


def validate_flash_image(
    source_path: Path,
    output_path: Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, object]:
    """Compare MAME's complete saved Flash array with the command model."""

    source = source_path.read_bytes()
    output = output_path.read_bytes()
    expected = modeled_flash_image(source)
    if output != expected:
        differing = [
            index
            for index, (left, right) in enumerate(zip(expected, output))
            if left != right
        ]
        if len(output) != len(expected):
            differing.append(min(len(output), len(expected)))
        raise MameRuntimeError(
            "MAME Flash image disagrees with modeled mutations; first offsets "
            + ", ".join(f"0x{offset:X}" for offset in differing[:16])
        )
    output_sha256 = file_sha256(output_path)
    if expected_sha256 is not None and output_sha256 != expected_sha256:
        raise MameRuntimeError("MAME Flash image SHA-256 disagrees with expectation")
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
