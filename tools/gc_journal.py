"""Byte-verified TI-84 Plus archive-GC journal structure and phase flow."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable

from flash_trace import FlashCommand
from rom_image import RomImage, RomLocation


PAGE = 0x3C
GC_BLOCK_OFFSET = 0x1DEA
GC_BLOCK_LENGTH = 0x0066
MASTER_PHASE_OFFSET = GC_BLOCK_OFFSET + 3
SECTOR_STATE_OFFSET = GC_BLOCK_OFFSET + 6
TI84_PLUS_ARCHIVE_LIMIT = 0x2A
MAX_ARCHIVE_LIMIT = 0x6A
CERTIFICATE_HALF_BASES = (0xF8000, 0xFA000)


class GcJournalSignatureError(ValueError):
    """A required OS 2.55MP GC-journal byte signature did not match."""


@dataclass(frozen=True)
class JournalField:
    """One journal field selected through a model-dependent RAM helper."""

    name: str
    relative_offset: int
    certificate_offset: int
    helper: RomLocation
    ram_addresses: tuple[int, ...]
    role: str


@dataclass(frozen=True)
class PhaseCase:
    """One master-phase value and its recovery-dispatch branch."""

    value: int
    branch: RomLocation
    role: str
    continuation: RomLocation | None


@dataclass(frozen=True)
class PhaseWrite:
    """One immediate master-phase write through the shared journal helper."""

    value: int
    load: RomLocation
    call: RomLocation
    condition: str


@dataclass(frozen=True)
class PhaseTransition:
    """One ROM-reachable monotonic transition between master phases."""

    source: int
    destination: int
    condition: str


@dataclass(frozen=True)
class SectorStateWrite:
    """One value passed to the archive-sector state writer."""

    value: int
    load: RomLocation
    call: RomLocation
    role: str


@dataclass(frozen=True)
class JournalTraceEvent:
    """One decoded byte-program command targeting GC journal state."""

    kind: str
    clock: int
    instruction_index: int
    physical_address: int
    half_base: int
    certificate_offset: int
    sector_index: int | None
    value: int
    pc_space: str | None
    pc_address: int | None


@dataclass(frozen=True)
class JournalInitialization:
    """Model-selected RAM erase-state initialization before GC."""

    load_current_entry: RomLocation
    initialize_entry: RomLocation
    port: int
    mask: int
    set_bit_ram_base: int
    set_bit_erased_length: int
    clear_bit_ram_base: int
    clear_bit_erased_length: int
    erased_byte: int
    certificate_rebuild_entry: RomLocation
    certificate_rebuild_length: int
    retained_tail_offset: int
    retained_tail_length: int
    ti84_plus_archive_limit: int
    ti84_plus_live_sector_state_count: int
    maximum_archive_limit: int
    maximum_live_sector_state_count: int


@dataclass(frozen=True)
class GcJournalAnalysis:
    """Validated static description of the OS 2.55MP GC journal."""

    rom_sha256: str
    block_offset: int
    block_length: int
    fields: tuple[JournalField, ...]
    dispatch_entry: RomLocation
    phase_cases: tuple[PhaseCase, ...]
    phase_write_helper: RomLocation
    phase_writes: tuple[PhaseWrite, ...]
    transitions: tuple[PhaseTransition, ...]
    sector_state_writer: RomLocation
    sector_state_writes: tuple[SectorStateWrite, ...]
    initialization: JournalInitialization


FIELDS = (
    JournalField(
        "flags",
        0,
        GC_BLOCK_OFFSET,
        RomLocation(PAGE, 0x7E78),
        (0x837B, 0x82A5),
        "control bits tested by GC preparation and phase recovery",
    ),
    JournalField(
        "archive_limit",
        1,
        GC_BLOCK_OFFSET + 1,
        RomLocation(PAGE, 0x7E83),
        (0x837C, 0x82A6),
        "model-dependent archive scan limit plus one",
    ),
    JournalField(
        "selected_sector_page",
        2,
        GC_BLOCK_OFFSET + 2,
        RomLocation(PAGE, 0x7E8E),
        (0x837D, 0x82A7),
        "selected 64 KiB archive-sector page",
    ),
    JournalField(
        "master_phase",
        3,
        MASTER_PHASE_OFFSET,
        RomLocation(PAGE, 0x7E99),
        (0x837E, 0x82A8),
        "top-level interruption-recovery phase",
    ),
    JournalField(
        "recovery_page",
        4,
        GC_BLOCK_OFFSET + 4,
        RomLocation(PAGE, 0x7EA4),
        (0x837F, 0x82A9),
        "archive page consumed by the phase-0xF8 recovery branch",
    ),
    JournalField(
        "secondary_recovery_page",
        5,
        GC_BLOCK_OFFSET + 5,
        RomLocation(PAGE, 0x7EBA),
        (0x8380, 0x82AA),
        "optional second page erased by the phase-0xFC recovery branch",
    ),
    JournalField(
        "sector_states",
        6,
        SECTOR_STATE_OFFSET,
        RomLocation(PAGE, 0x7EAF),
        (0x8381, 0x82AB),
        "array indexed by (archive page >> 2) - 2",
    ),
)


PHASE_CASES = (
    PhaseCase(
        0xFF,
        RomLocation(PAGE, 0x7C43),
        "write phase 0xFE, then enter the normal phase machine",
        RomLocation(PAGE, 0x7CFB),
    ),
    PhaseCase(
        0xFE,
        RomLocation(PAGE, 0x7C48),
        "repair scratch-sector setup and resume phase processing",
        RomLocation(PAGE, 0x7CFB),
    ),
    PhaseCase(
        0xFC,
        RomLocation(PAGE, 0x7CC6),
        "erase the journal-selected recovery page or pages",
        RomLocation(PAGE, 0x7D0A),
    ),
    PhaseCase(
        0xF8,
        RomLocation(PAGE, 0x7CDA),
        "erase the recovery-page field and continue finalization",
        RomLocation(PAGE, 0x7D1B),
    ),
    PhaseCase(
        0xF0,
        RomLocation(PAGE, 0x7CE3),
        "repair archive-sector header states before cleanup",
        RomLocation(PAGE, 0x7D30),
    ),
    PhaseCase(
        0xE0,
        RomLocation(PAGE, 0x7D30),
        "run final journal cleanup",
        None,
    ),
)


PHASE_WRITES = (
    PhaseWrite(
        0xFE,
        RomLocation(PAGE, 0x7ACF),
        RomLocation(PAGE, 0x7AD1),
        "always after optional scratch-sector header programming",
    ),
    PhaseWrite(
        0xFC,
        RomLocation(PAGE, 0x7D05),
        RomLocation(PAGE, 0x7D07),
        "only when journal flags bit 3 is clear",
    ),
    PhaseWrite(
        0xF8,
        RomLocation(PAGE, 0x7D10),
        RomLocation(PAGE, 0x7D12),
        "only when journal flags bit 3 is clear",
    ),
    PhaseWrite(
        0xF0,
        RomLocation(PAGE, 0x7D20),
        RomLocation(PAGE, 0x7D22),
        "only when the archive-sector consistency check returns carry",
    ),
    PhaseWrite(
        0xE0,
        RomLocation(PAGE, 0x7D2B),
        RomLocation(PAGE, 0x7D2D),
        "always before final cleanup",
    ),
)


TRANSITIONS = (
    PhaseTransition(0xFF, 0xFE, "journal initialization or 0xFF recovery"),
    PhaseTransition(0xFE, 0xFC, "journal flags bit 3 is clear"),
    PhaseTransition(0xFE, 0xF0, "bit 3 is set and consistency check carries"),
    PhaseTransition(0xFE, 0xE0, "bit 3 is set and consistency check does not carry"),
    PhaseTransition(0xFC, 0xF8, "after post-0xFC sector work"),
    PhaseTransition(0xF8, 0xF0, "archive-sector consistency check carries"),
    PhaseTransition(0xF8, 0xE0, "archive-sector consistency check does not carry"),
    PhaseTransition(0xF0, 0xE0, "after phase-0xF0 sector repair"),
)


SECTOR_STATE_WRITES = (
    SectorStateWrite(
        0xFE,
        RomLocation(PAGE, 0x7846),
        RomLocation(PAGE, 0x7848),
        "begin one archive-sector operation",
    ),
    SectorStateWrite(
        0xFC,
        RomLocation(PAGE, 0x7851),
        RomLocation(PAGE, 0x7853),
        "complete the ordinary archive-sector operation",
    ),
    SectorStateWrite(
        0xFC,
        RomLocation(PAGE, 0x7C52),
        RomLocation(PAGE, 0x7C54),
        "complete a recovered archive-sector operation",
    ),
)


_SIGNATURES = (
    (
        RomLocation(PAGE, 0x72A5),
        bytes.fromhex(
            "CD7F2CCD6B7E21A582060ACD371820052100800680CB203EFF7723"
            "10FCCD1773"
        ),
    ),
    (
        RomLocation(PAGE, 0x7317),
        bytes.fromhex("21A5820664CD37182805217B8306123EFF772310FCC9"),
    ),
    (
        RomLocation(PAGE, 0x77B5),
        bytes.fromhex(
            "3EF0327784CD6B7ECD1773FDCB24BE06FBCD717ECD6B2B783CCD837E77"
        ),
    ),
    (
        RomLocation(PAGE, 0x7C1F),
        bytes.fromhex(
            "CD2A7BCD997E7EFEFF2819FEFE281AFEFC"
            "CAC67CFEF8CADA7CFEF0CAE37CFEE0CA307DC9"
        ),
    ),
    (
        RomLocation(PAGE, 0x7AA6),
        bytes.fromhex("111100CD487ECDB47ACD997E77C9"),
    ),
    (
        RomLocation(PAGE, 0x7ABC),
        bytes.fromhex(
            "CD787ECB5E200CCD8E7E7E0670110040EF21803EFECDA67AC9"
        ),
    ),
    (
        RomLocation(PAGE, 0x7CFB),
        bytes.fromhex(
            "CD1A78CD787ECB5E20163EFCCDA67ACD557ACD2A7B"
            "3EF8CDA67ACD337BCD2A7BCD3C7B300B3EF0CDA67A"
            "CD6D7BCD2A7B3EE0CDA67ACD907BCD2A7BC9"
        ),
    ),
    (
        RomLocation(PAGE, 0x7DA9),
        bytes.fromhex(
            "C5CB2FCB2FD602F516005FCDAF7E197877111400CD487E"
            "F116005F19EBC1CD057FEF2180C9"
        ),
    ),
    (
        RomLocation(PAGE, 0x7DCE),
        bytes.fromhex(
            "0600CDAF7E7EFEFE2809230478FE0420F4B7C978C602CB27CB2737C9"
        ),
    ),
    (
        RomLocation(PAGE, 0x7E78),
        bytes.fromhex(
            "217B83CD3718C021A582C9217C83CD3718C021A682C9"
            "217D83CD3718C021A782C9217E83CD3718C021A882C9"
            "217F83CD3718C021A982C9218183CD3718C021AB82C9"
            "218083CD3718C021AA82C9"
        ),
    ),
    (
        RomLocation(PAGE, 0x7EC5),
        bytes.fromhex("3E15CD3718C03E29CD2F18C83E69C9"),
    ),
    (
        RomLocation(0x3D, 0x4274),
        bytes.fromhex("CD415201660011A582CDE348EBCD8B73CDE872C9"),
    ),
    (
        RomLocation(0x3D, 0x4806),
        bytes.fromhex(
            "F5C5D5E5DDE5CD37182018FE01280CFE032010CDA342CDB342180B"
            "CDDF42CDB3421803CDF242C3E746"
        ),
    ),
    (
        RomLocation(0x00, 0x2B6B),
        bytes.fromhex("CD092B13647D"),
    ),
)


def _validate_bytes(rom: RomImage, location: RomLocation, expected: bytes) -> None:
    actual = rom.bytes_at(location.page, location.address, len(expected))
    if actual != expected:
        raise GcJournalSignatureError(
            f"signature mismatch at {location}: expected {expected.hex()}, "
            f"got {actual.hex()}"
        )


def sector_state_index(page: int) -> int:
    """Return the journal index for a 64 KiB archive-sector start page."""

    if page < 0x08 or page & 3:
        raise ValueError(
            "archive sector page must be a multiple of four at or above 0x08"
        )
    return (page >> 2) - 2


def sector_state_count(archive_limit: int) -> int:
    """Count 64 KiB sector-start pages below an exclusive archive limit."""

    if not 0x08 <= archive_limit <= 0x100:
        raise ValueError("archive limit must be in 0x08-0x100")
    return len(range(0x08, archive_limit, 4))


def analyze_gc_journal(rom: RomImage) -> GcJournalAnalysis:
    """Validate and report the OS 2.55MP archive-GC journal structure."""

    if rom.page_count <= 0x3D:
        raise GcJournalSignatureError(
            f"ROM has {rom.page_count} page(s); physical pages 0x{PAGE:02X}-0x3D "
            "are required"
        )
    for location, expected in _SIGNATURES:
        _validate_bytes(rom, location, expected)
    return GcJournalAnalysis(
        rom_sha256=sha256(rom.data).hexdigest(),
        block_offset=GC_BLOCK_OFFSET,
        block_length=GC_BLOCK_LENGTH,
        fields=FIELDS,
        dispatch_entry=RomLocation(PAGE, 0x7C1F),
        phase_cases=PHASE_CASES,
        phase_write_helper=RomLocation(PAGE, 0x7AA6),
        phase_writes=PHASE_WRITES,
        transitions=TRANSITIONS,
        sector_state_writer=RomLocation(PAGE, 0x7DA9),
        sector_state_writes=SECTOR_STATE_WRITES,
        initialization=JournalInitialization(
            load_current_entry=RomLocation(PAGE, 0x7E6B),
            initialize_entry=RomLocation(PAGE, 0x7317),
            port=0x02,
            mask=0x80,
            set_bit_ram_base=0x82A5,
            set_bit_erased_length=0x64,
            clear_bit_ram_base=0x837B,
            clear_bit_erased_length=0x12,
            erased_byte=0xFF,
            certificate_rebuild_entry=RomLocation(0x3D, 0x4274),
            certificate_rebuild_length=GC_BLOCK_LENGTH,
            retained_tail_offset=0x64,
            retained_tail_length=2,
            ti84_plus_archive_limit=TI84_PLUS_ARCHIVE_LIMIT,
            ti84_plus_live_sector_state_count=sector_state_count(
                TI84_PLUS_ARCHIVE_LIMIT
            ),
            maximum_archive_limit=MAX_ARCHIVE_LIMIT,
            maximum_live_sector_state_count=sector_state_count(
                MAX_ARCHIVE_LIMIT
            ),
        ),
    )


def journal_trace_events(
    commands: Iterable[FlashCommand],
) -> tuple[JournalTraceEvent, ...]:
    """Extract state-changing journal writes from decoded Flash commands.

    Rebuild workers also issue byte-program commands whose data byte is
    ``0xFF``.  Those commands cannot clear a NOR Flash bit, so they are copy
    traffic rather than journal transitions and are omitted here.
    """

    events = []
    for command in commands:
        if command.kind != "byte_program" or command.value == 0xFF:
            continue
        for half_base in CERTIFICATE_HALF_BASES:
            certificate_offset = command.target_address - half_base
            if certificate_offset == MASTER_PHASE_OFFSET:
                kind = "master_phase"
                sector_index = None
            elif (
                SECTOR_STATE_OFFSET
                <= certificate_offset
                < SECTOR_STATE_OFFSET + sector_state_count(MAX_ARCHIVE_LIMIT)
            ):
                kind = "sector_state"
                sector_index = certificate_offset - SECTOR_STATE_OFFSET
            else:
                continue
            final_write = command.writes[-1] if command.writes else None
            events.append(
                JournalTraceEvent(
                    kind=kind,
                    clock=command.clock,
                    instruction_index=command.instruction_index,
                    physical_address=command.target_address,
                    half_base=half_base,
                    certificate_offset=certificate_offset,
                    sector_index=sector_index,
                    value=command.value,
                    pc_space=(final_write.pc_space if final_write else None),
                    pc_address=(final_write.pc_address if final_write else None),
                )
            )
            break
    return tuple(events)
