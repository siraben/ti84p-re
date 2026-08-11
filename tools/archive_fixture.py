"""Construct deterministic fresh-sector archive layouts from TI variables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from flash_hardware import FLASH_SIZE
from hardware_probe import TiVariable


ARCHIVE_SECTOR_SIZE = 0x10000
ARCHIVE_SECTOR_STATE = 0xF0
ARCHIVE_RECORD_STATE = 0xFC


class ArchiveFixtureError(ValueError):
    """A requested archive layout would hide an unsupported condition."""


@dataclass(frozen=True)
class ArchiveRecordPlacement:
    """One serialized archive record and its physical placement."""

    name: str
    variable_type: int
    version: int
    physical_start: int
    physical_end: int
    page: int
    logical_address: int
    data_size: int
    record_size: int


@dataclass(frozen=True)
class ArchiveFixture:
    """A complete Flash image plus its controlled archive placements."""

    image: bytes
    sector_bases: tuple[int, ...]
    records: tuple[ArchiveRecordPlacement, ...]


def _validate_variable(variable: TiVariable) -> bytes:
    if variable.archived:
        raise ArchiveFixtureError(
            f"input variable {variable.name!r} is already marked archived"
        )
    if not 0 <= variable.variable_type <= 0xFF:
        raise ArchiveFixtureError("variable type must fit in one byte")
    if not 0 <= variable.version <= 0xFF:
        raise ArchiveFixtureError("variable version must fit in one byte")
    try:
        name = variable.name.upper().encode("ascii")
    except UnicodeEncodeError as error:
        raise ArchiveFixtureError("variable name must be ASCII") from error
    if not 1 <= len(name) <= 8:
        raise ArchiveFixtureError(
            "variable name must contain one through eight characters"
        )
    if len(variable.data) > 0xFFFF:
        raise ArchiveFixtureError("variable data is too large")
    return name


def encode_archive_record(variable: TiVariable, physical_start: int) -> bytes:
    """Serialize one OS 2.55MP archive record at a physical address."""

    name = _validate_variable(variable)
    if not 0 < physical_start < FLASH_SIZE:
        raise ArchiveFixtureError("archive record start is outside Flash")
    page, page_offset = divmod(physical_start, 0x4000)
    logical_address = 0x4000 + page_offset
    if page > 0xFF:
        raise ArchiveFixtureError("archive record page does not fit in one byte")
    metadata = (
        bytes((variable.variable_type, variable.version, 0x00))
        + logical_address.to_bytes(2, "little")
        + bytes((page, len(name)))
        + name
    )
    payload_size = len(metadata) + len(variable.data)
    if payload_size > 0xFFFF:
        raise ArchiveFixtureError("archive record payload is too large")
    return (
        bytes((ARCHIVE_RECORD_STATE,))
        + payload_size.to_bytes(2, "little")
        + metadata
        + variable.data
    )


def build_fresh_archive_fixture(
    source: bytes,
    variables: Iterable[TiVariable],
    sector_bases: Iterable[int],
) -> ArchiveFixture:
    """Place variables first-fit into explicit erased 64 KiB sectors.

    This models the append-only placement used by the OS on a fresh archive
    layout. It deliberately rejects existing records, deleted slots, and
    non-erased bytes instead of pretending to model general allocation or GC.
    """

    if len(source) != FLASH_SIZE:
        raise ArchiveFixtureError(
            f"source image must contain 0x{FLASH_SIZE:X} bytes, got 0x{len(source):X}"
        )
    sectors = tuple(sorted(sector_bases))
    if not sectors:
        raise ArchiveFixtureError("at least one archive sector is required")
    if len(set(sectors)) != len(sectors):
        raise ArchiveFixtureError("archive sector bases must be unique")
    for base in sectors:
        if base % ARCHIVE_SECTOR_SIZE:
            raise ArchiveFixtureError(
                f"archive sector base 0x{base:X} is not 64 KiB aligned"
            )
        end = base + ARCHIVE_SECTOR_SIZE
        if not 0 <= base < end <= len(source):
            raise ArchiveFixtureError(
                f"archive sector 0x{base:X}–0x{end - 1:X} is outside Flash"
            )
        if source[base:end] != b"\xFF" * ARCHIVE_SECTOR_SIZE:
            raise ArchiveFixtureError(
                f"archive sector at 0x{base:05X} is not completely erased"
            )

    image = bytearray(source)
    cursors = {base: base + 1 for base in sectors}
    used: set[int] = set()
    placements: list[ArchiveRecordPlacement] = []
    for variable in variables:
        _validate_variable(variable)
        selected = None
        record = b""
        for base in sectors:
            candidate = encode_archive_record(variable, cursors[base])
            if cursors[base] + len(candidate) <= base + ARCHIVE_SECTOR_SIZE:
                selected = base
                record = candidate
                break
        if selected is None:
            raise ArchiveFixtureError(
                f"no supplied archive sector can fit variable {variable.name!r}"
            )

        start = cursors[selected]
        end = start + len(record)
        if image[start:end] != b"\xFF" * len(record):
            raise ArchiveFixtureError(
                f"archive target 0x{start:05X}–0x{end - 1:05X} is not erased"
            )
        if selected not in used:
            image[selected] = ARCHIVE_SECTOR_STATE
            used.add(selected)
        image[start:end] = record
        cursors[selected] = end
        page, page_offset = divmod(start, 0x4000)
        placements.append(
            ArchiveRecordPlacement(
                name=variable.name.upper(),
                variable_type=variable.variable_type,
                version=variable.version,
                physical_start=start,
                physical_end=end,
                page=page,
                logical_address=0x4000 + page_offset,
                data_size=len(variable.data),
                record_size=len(record),
            )
        )

    return ArchiveFixture(
        image=bytes(image),
        sector_bases=sectors,
        records=tuple(placements),
    )
