"""Typed report and complete-image oracle for MAME Flash erase probes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path

from mame_runtime import MameRuntimeError, file_sha256, parse_report_fields

FLASH_SIZE = 0x100000
ERASED_FLASH_SHA256 = (
    "f5fb04aa5b882706b9309e885f19477261336ef76a150c3b4d3489dfac3953ec"
)


@dataclass(frozen=True)
class MameFlashEraseSectorReport:
    """Immediate and completed observations for one sector erase."""

    name: str
    start: int
    size: int
    probe_address: int
    immediate_before: int
    immediate_selected: tuple[int, int]
    immediate_selected_end: int
    immediate_probe: int
    complete_frame: int
    complete_before: int
    complete_selected: int
    complete_selected_end: int
    complete_probe: int


@dataclass(frozen=True)
class MameFlashChipEraseReport:
    """Immediate and completed observations for one chip erase."""

    start_seconds: int
    immediate_array0: int
    immediate_array1: int
    immediate_stale_start: int
    immediate_stale_end: int
    complete_seconds: int
    complete_array0: int
    complete_array1: int
    complete_stale_start: int
    complete_stale_end: int


@dataclass(frozen=True)
class MameFlashEraseReport:
    """Complete MAME sector-geometry and chip-erase matrix."""

    machine: str
    version: str
    sectors: tuple[MameFlashEraseSectorReport, ...]
    chip: MameFlashChipEraseReport

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _required(fields: dict[str, str], names: set[str], scope: str) -> None:
    missing = sorted(names - fields.keys())
    if missing:
        raise MameRuntimeError(f"{scope} omits " + ", ".join(missing))


def _hex(fields: dict[str, str], name: str) -> int:
    return int(fields[name], 16)


def _hex_pair(fields: dict[str, str], name: str) -> tuple[int, int]:
    values = tuple(int(item, 16) for item in fields[name].split(","))
    if len(values) != 2:
        raise ValueError(f"{name} must contain two values")
    return values


def parse_flash_erase_report(output: str) -> MameFlashEraseReport:
    """Parse all sector and chip lines emitted by the MAME erase adapter."""

    lines = output.splitlines()
    try:
        identity_line = next(
            line
            for line in lines
            if line.startswith("MAME_FLASH_ERASE identity ")
        )
        chip_immediate_line = next(
            line
            for line in lines
            if line.startswith("MAME_FLASH_ERASE chip_immediate ")
        )
        chip_complete_line = next(
            line
            for line in lines
            if line.startswith("MAME_FLASH_ERASE chip_complete ")
        )
    except StopIteration as error:
        raise MameRuntimeError(
            "MAME Flash erase output omits an identity or chip line"
        ) from error

    immediate_by_case = {
        fields["case"]: fields
        for line in lines
        if line.startswith("MAME_FLASH_ERASE immediate ")
        for fields in (parse_report_fields(line),)
        if "case" in fields
    }
    complete_by_case = {
        fields["case"]: fields
        for line in lines
        if line.startswith("MAME_FLASH_ERASE complete ")
        for fields in (parse_report_fields(line),)
        if "case" in fields
    }
    case_names = ("regular64", "top32", "top8a", "top8b", "top16")
    if set(immediate_by_case) != set(case_names):
        raise MameRuntimeError("MAME Flash erase output has incomplete immediate cases")
    if set(complete_by_case) != set(case_names):
        raise MameRuntimeError("MAME Flash erase output has incomplete complete cases")

    identity = parse_report_fields(identity_line)
    chip_immediate = parse_report_fields(chip_immediate_line)
    chip_complete = parse_report_fields(chip_complete_line)
    _required(identity, {"machine", "version"}, "MAME Flash erase identity")
    _required(
        chip_immediate,
        {"start_seconds", "array0", "array1", "stale_start", "stale_end"},
        "MAME chip-erase immediate report",
    )
    _required(
        chip_complete,
        {"complete_seconds", "array0", "array1", "stale_start", "stale_end"},
        "MAME chip-erase complete report",
    )

    try:
        sectors = []
        for name in case_names:
            immediate = immediate_by_case[name]
            complete = complete_by_case[name]
            _required(
                immediate,
                {
                    "case",
                    "start",
                    "size",
                    "probe_addr",
                    "before",
                    "selected",
                    "selected_end",
                    "probe",
                },
                f"MAME sector {name} immediate report",
            )
            _required(
                complete,
                {
                    "case",
                    "frame",
                    "before",
                    "selected",
                    "selected_end",
                    "probe",
                },
                f"MAME sector {name} complete report",
            )
            sectors.append(
                MameFlashEraseSectorReport(
                    name=name,
                    start=_hex(immediate, "start"),
                    size=_hex(immediate, "size"),
                    probe_address=_hex(immediate, "probe_addr"),
                    immediate_before=_hex(immediate, "before"),
                    immediate_selected=_hex_pair(immediate, "selected"),
                    immediate_selected_end=_hex(immediate, "selected_end"),
                    immediate_probe=_hex(immediate, "probe"),
                    complete_frame=int(complete["frame"], 10),
                    complete_before=_hex(complete, "before"),
                    complete_selected=_hex(complete, "selected"),
                    complete_selected_end=_hex(complete, "selected_end"),
                    complete_probe=_hex(complete, "probe"),
                )
            )
        chip = MameFlashChipEraseReport(
            start_seconds=int(chip_immediate["start_seconds"], 10),
            immediate_array0=_hex(chip_immediate, "array0"),
            immediate_array1=_hex(chip_immediate, "array1"),
            immediate_stale_start=_hex(chip_immediate, "stale_start"),
            immediate_stale_end=_hex(chip_immediate, "stale_end"),
            complete_seconds=int(chip_complete["complete_seconds"], 10),
            complete_array0=_hex(chip_complete, "array0"),
            complete_array1=_hex(chip_complete, "array1"),
            complete_stale_start=_hex(chip_complete, "stale_start"),
            complete_stale_end=_hex(chip_complete, "stale_end"),
        )
    except (KeyError, ValueError) as error:
        raise MameRuntimeError(
            "invalid numeric MAME Flash erase report field"
        ) from error
    return MameFlashEraseReport(
        machine=identity["machine"],
        version=identity["version"],
        sectors=tuple(sectors),
        chip=chip,
    )


def expected_flash_erase_report() -> MameFlashEraseReport:
    """Return exact observations implied by the MAME 0.287 erase model."""

    definitions = (
        ("regular64", 0xE0000, 0x10000, 0xF0000, 0x00, 50),
        ("top32", 0xF0000, 0x8000, 0xF8000, 0x08, 75),
        ("top8a", 0xF8000, 0x2000, 0xFA000, 0x08, 88),
        ("top8b", 0xFA000, 0x2000, 0xFC000, 0x08, 101),
        ("top16", 0xFC000, 0x4000, 0xFBFFE, 0x00, 126),
    )
    sectors = tuple(
        MameFlashEraseSectorReport(
            name=name,
            start=start,
            size=size,
            probe_address=probe,
            immediate_before=0x00,
            immediate_selected=(0x4C, 0x08),
            immediate_selected_end=0x4C,
            immediate_probe=immediate_probe,
            complete_frame=complete_frame,
            complete_before=0x00,
            complete_selected=0xFF,
            complete_selected_end=0xFF,
            complete_probe=0x00,
        )
        for name, start, size, probe, immediate_probe, complete_frame in definitions
    )
    return MameFlashEraseReport(
        machine="ti84pv3",
        version="0.287",
        sectors=sectors,
        chip=MameFlashChipEraseReport(
            start_seconds=2,
            immediate_array0=0xFF,
            immediate_array1=0xFF,
            immediate_stale_start=0x4C,
            immediate_stale_end=0x08,
            complete_seconds=18,
            complete_array0=0xFF,
            complete_array1=0xFF,
            complete_stale_start=0xFF,
            complete_stale_end=0xFF,
        ),
    )


def validate_flash_erase_report(
    report: MameFlashEraseReport,
) -> dict[str, object]:
    """Check runtime observations against the pinned MAME erase model."""

    expected_template = expected_flash_erase_report()
    frames = tuple(sector.complete_frame for sector in report.sectors)
    if len(frames) != 5 or any(
        later <= earlier for earlier, later in pairwise(frames)
    ):
        raise MameRuntimeError("MAME Flash sector completion frames are not ordered")
    if report.chip.complete_seconds - report.chip.start_seconds < 16:
        raise MameRuntimeError("MAME chip erase ran for less than 16 emulated seconds")
    if report != expected_template:
        raise MameRuntimeError(
            "MAME Flash erase report disagrees with the 0.287 model"
        )
    return {
        "source_model": {
            "sector_ranges": [
                [sector.start, sector.start + sector.size]
                for sector in expected_template.sectors
            ],
            "sector_busy_range_size": 0x10000,
            "chip_erase_range": [0, FLASH_SIZE],
            "chip_busy_range_source": "stale last-sector start",
        },
        "native": report.to_dict(),
    }


def validate_erased_flash_image(
    source_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Require MAME's saved chip-erase result to be exactly one MiB of `FF`."""

    source = source_path.read_bytes()
    output = output_path.read_bytes()
    if len(source) != FLASH_SIZE:
        raise MameRuntimeError(
            f"MAME Flash source must be {FLASH_SIZE} bytes, found {len(source)}"
        )
    if output != b"\xFF" * FLASH_SIZE:
        first = next(
            (index for index, value in enumerate(output) if value != 0xFF),
            min(len(output), FLASH_SIZE),
        )
        raise MameRuntimeError(
            f"MAME chip-erase image is not all FF; first offset 0x{first:X}"
        )
    output_sha256 = file_sha256(output_path)
    if output_sha256 != ERASED_FLASH_SHA256:
        raise MameRuntimeError("MAME chip-erase image SHA-256 disagrees")
    return {
        "output_sha256": output_sha256,
        "changed_byte_count": sum(value != 0xFF for value in source),
        "non_ff_byte_count": 0,
    }
