"""Audit direct and indirect I/O candidates across an exact ROM image.

The scanners deliberately generate candidates rather than asserting that raw
bytes are executable. Pinned review manifests record the separate Ghidra,
raw-control-flow, and table-shape audits for the exact retail OS image.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256

from port_definitions import PortDefinition
from rom_image import RomImage, RomLocation
from rom_io import inline_descriptor_at
from z80_disassembly import disassemble_page
from z80_io import (
    RawIndirectIO,
    iter_direct_io_accesses,
    iter_resolved_io_accesses,
    raw_indirect_io_boundary_prefixes,
    raw_indirect_io_locations,
)

RETAIL_ROM_SHA256 = "7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d"


@dataclass(frozen=True)
class UnlistedIOCandidate:
    """One aligned immediate-port instruction from linear disassembly."""

    location: RomLocation
    data: bytes
    direction: str
    port: int
    instruction: str


@dataclass(frozen=True)
class CandidateReview:
    """Pinned static classification of one candidate in the retail ROM."""

    location: RomLocation
    data: bytes
    direction: str
    port: int
    classification: str
    evidence: str


@dataclass(frozen=True)
class ReviewedCandidate:
    candidate: UnlistedIOCandidate
    review: CandidateReview


@dataclass(frozen=True)
class RomIOCoverage:
    """Reconciliation between a generated candidate set and its review manifest."""

    rom_sha256: str
    candidates: tuple[UnlistedIOCandidate, ...]
    reviewed: tuple[ReviewedCandidate, ...]
    missing_reviews: tuple[UnlistedIOCandidate, ...]
    stale_reviews: tuple[CandidateReview, ...]
    duplicate_candidate_locations: tuple[RomLocation, ...]
    duplicate_review_locations: tuple[RomLocation, ...]
    drift_errors: tuple[str, ...]

    @property
    def exact_rom(self) -> bool:
        return self.rom_sha256 == RETAIL_ROM_SHA256

    @property
    def complete(self) -> bool:
        return (
            self.exact_rom
            and not self.missing_reviews
            and not self.stale_reviews
            and not self.duplicate_candidate_locations
            and not self.duplicate_review_locations
            and not self.drift_errors
        )

    @property
    def classification_counts(self) -> dict[str, int]:
        return dict(Counter(item.review.classification for item in self.reviewed))


@dataclass(frozen=True)
class IndirectIOReview:
    """Pinned classification of one raw register or block-I/O opcode pair."""

    location: RomLocation
    data: bytes
    direction: str
    form: str
    classification: str
    evidence: str
    resolved_port: int | None = None


@dataclass(frozen=True)
class ReviewedIndirectIO:
    candidate: RawIndirectIO
    review: IndirectIOReview


@dataclass(frozen=True)
class ResolvedIndirectIO:
    """One aligned register or block-I/O instruction with a known port."""

    location: RomLocation
    direction: str
    port: int
    instruction: str


@dataclass(frozen=True)
class IndirectIOCoverage:
    """Complete raw-byte census for register and block-I/O opcodes."""

    rom_sha256: str
    candidates: tuple[RawIndirectIO, ...]
    resolved: tuple[ResolvedIndirectIO, ...]
    reviewed: tuple[ReviewedIndirectIO, ...]
    missing_reviews: tuple[RawIndirectIO, ...]
    stale_reviews: tuple[IndirectIOReview, ...]
    duplicate_candidate_locations: tuple[RomLocation, ...]
    duplicate_review_locations: tuple[RomLocation, ...]
    boundary_prefix_locations: tuple[RomLocation, ...]
    drift_errors: tuple[str, ...]

    @property
    def exact_rom(self) -> bool:
        return self.rom_sha256 == RETAIL_ROM_SHA256

    @property
    def complete(self) -> bool:
        return (
            self.exact_rom
            and not self.missing_reviews
            and not self.stale_reviews
            and not self.duplicate_candidate_locations
            and not self.duplicate_review_locations
            and not self.boundary_prefix_locations
            and not self.drift_errors
        )

    @property
    def classification_counts(self) -> dict[str, int]:
        return dict(Counter(item.review.classification for item in self.reviewed))


_NO_CODE_EVIDENCE = (
    "table-shaped bytes; rebuilt Ghidra has no containing function or xrefs, "
    "and the page-local direct CALL/JP scan has no target"
)
_OPERAND_EVIDENCE = (
    "operand bytes DB 9C inside 03:6DE0 LD HL,0x9CDB in editbuf_clr_hibit; "
    "rebuilt Ghidra has no xref to 03:6DE1"
)


def _review(
    location: str,
    data: str,
    direction: str,
    port: int,
    classification: str = "reviewed-data",
    evidence: str = _NO_CODE_EVIDENCE,
) -> CandidateReview:
    page_text, address_text = location.split(":", 1)
    return CandidateReview(
        RomLocation(int(page_text, 16), int(address_text, 16)),
        bytes.fromhex(data),
        direction,
        port,
        classification,
        evidence,
    )


RETAIL_REVIEWS = (
    _review("01:4304", "d349", "out", 0x49),
    _review("01:446A", "d34e", "out", 0x4E),
    _review("01:446E", "db4e", "in", 0x4E),
    _review("01:4C5A", "db5e", "in", 0x5E),
    _review("01:556D", "db5e", "in", 0x5E),
    _review("01:6E55", "db6e", "in", 0x6E),
    _review("01:6E95", "d370", "out", 0x70),
    _review("01:7CD6", "d3ff", "out", 0xFF),
    _review("03:630B", "d3fe", "out", 0xFE),
    _review("03:6323", "dbfe", "in", 0xFE),
    _review("03:634F", "d3fe", "out", 0xFE),
    _review("03:6367", "dbfe", "in", 0xFE),
    _review("03:656F", "db65", "in", 0x65),
    _review(
        "03:6DE1",
        "db9c",
        "in",
        0x9C,
        "operand-overlap",
        _OPERAND_EVIDENCE,
    ),
    _review("07:4076", "d3d1", "out", 0xD1),
    _review("33:4010", "d36b", "out", 0x6B),
    _review("34:6CF5", "d36d", "out", 0x6D),
    _review("34:6CF7", "d36d", "out", 0x6D),
    _review("34:73AB", "db73", "in", 0x73),
    _review("34:73AD", "db73", "in", 0x73),
    _review("37:6A9C", "db6b", "in", 0x6B),
    _review("37:6B14", "db6b", "in", 0x6B),
    _review("38:6A00", "dbdc", "in", 0xDC),
    _review("3A:7D81", "db5e", "in", 0x5E),
    _review("3A:7FED", "dbdb", "in", 0xDB),
    _review("3B:47B9", "d36f", "out", 0x6F),
    _review("3B:4F45", "d351", "out", 0x51),
    _review("3B:52AE", "db6e", "in", 0x6E),
    _review("3B:535C", "db5d", "in", 0x5D),
    _review("3B:5467", "db6d", "in", 0x6D),
    _review("3F:40FC", "d35e", "out", 0x5E),
    _review("3F:4111", "db63", "in", 0x63),
    _review("3F:56F7", "dbd1", "in", 0xD1),
    _review("3F:671B", "d3e7", "out", 0xE7),
    _review("3F:67F7", "dbe6", "in", 0xE6),
)


_INDIRECT_DATA_EVIDENCE = (
    "address- or data-table bytes; rebuilt Ghidra has no containing function "
    "or xrefs, and the page-local direct CALL/JP scan has no target"
)


def _indirect_review(
    location: str,
    data: str,
    direction: str,
    form: str,
    classification: str,
    evidence: str,
    resolved_port: int | None = None,
) -> IndirectIOReview:
    page_text, address_text = location.split(":", 1)
    return IndirectIOReview(
        RomLocation(int(page_text, 16), int(address_text, 16)),
        bytes.fromhex(data),
        direction,
        form,
        classification,
        evidence,
        resolved_port,
    )


def _indirect_data(
    location: str, data: str, direction: str, form: str
) -> IndirectIOReview:
    return _indirect_review(
        location,
        data,
        direction,
        form,
        "reviewed-data",
        _INDIRECT_DATA_EVIDENCE,
    )


def _indirect_operand(
    location: str,
    data: str,
    direction: str,
    form: str,
    owner_location: str,
    owner: str,
) -> IndirectIOReview:
    return _indirect_review(
        location,
        data,
        direction,
        form,
        "operand-overlap",
        f"little-endian operand of {owner} at {owner_location}",
    )


RETAIL_INDIRECT_REVIEWS = (
    _indirect_data("01:428C", "ed48", "in", "IN C,(C)"),
    _indirect_operand("04:4178", "ed41", "out", "OUT (C),B", "04:4177", "JP Z,0x41ED"),
    _indirect_operand("04:4182", "ed41", "out", "OUT (C),B", "04:4181", "JP C,0x41ED"),
    _indirect_operand("04:6F5B", "ed70", "in", "IN (C)", "04:6F5A", "CALL 0x70ED"),
    _indirect_operand("05:40E7", "ed40", "in", "IN B,(C)", "05:40E6", "CALL 0x40ED"),
    _indirect_operand("05:428C", "ed40", "in", "IN B,(C)", "05:428B", "CALL 0x40ED"),
    _indirect_operand("05:46E5", "ed40", "in", "IN B,(C)", "05:46E4", "CALL 0x40ED"),
    _indirect_operand("05:7159", "ed71", "out", "OUT (C),0", "05:7157", "JP NZ,0x71ED"),
    _indirect_operand("05:715F", "ed71", "out", "OUT (C),0", "05:715D", "JP NZ,0x71ED"),
    _indirect_data("07:4465", "edbb", "out", "OTDR"),
    _indirect_review(
        "37:58A9",
        "eda2",
        "in",
        "INI",
        "resolved-instruction",
        "37:58A4 loads B=4 and C=0x49; DEC C selects RTC port 0x48 before INI",
        0x48,
    ),
    _indirect_review(
        "37:5944",
        "eda3",
        "out",
        "OUTI",
        "resolved-instruction",
        "37:593F loads B=4 and C=0x45; DEC C selects RTC port 0x44 before OUTI",
        0x44,
    ),
    _indirect_data("38:40C4", "ed40", "in", "IN B,(C)"),
    _indirect_data("38:48B4", "ed49", "out", "OUT (C),C"),
    _indirect_operand("38:57AC", "ed58", "in", "IN E,(C)", "38:57AB", "CALL 0x58ED"),
    _indirect_operand("38:57D7", "ed58", "in", "IN E,(C)", "38:57D6", "CALL 0x58ED"),
    _indirect_operand("38:57F5", "ed58", "in", "IN E,(C)", "38:57F4", "CALL 0x58ED"),
    _indirect_operand("38:589F", "ed58", "in", "IN E,(C)", "38:589E", "CALL 0x58ED"),
    _indirect_operand("38:75AF", "ed69", "out", "OUT (C),L", "38:75AE", "CALL 0x69ED"),
    _indirect_data("39:7268", "ed71", "out", "OUT (C),0"),
    _indirect_operand("39:73B7", "ed40", "in", "IN B,(C)", "39:73B6", "LD HL,0x40ED"),
    _indirect_data("3B:4F15", "ed58", "in", "IN E,(C)"),
    _indirect_operand("3C:4EFE", "ed58", "in", "IN E,(C)", "3C:4EFD", "CALL 0x58ED"),
    _indirect_operand("3C:53E2", "ed58", "in", "IN E,(C)", "3C:53E1", "CALL 0x58ED"),
    _indirect_operand("3C:783B", "ed79", "out", "OUT (C),A", "3C:783A", "CALL 0x79ED"),
    _indirect_operand("3C:7F99", "ed79", "out", "OUT (C),A", "3C:7F98", "CALL 0x79ED"),
    _indirect_data("3F:408D", "ed68", "in", "IN L,(C)"),
    _indirect_operand("3F:540E", "ed68", "in", "IN L,(C)", "3F:540D", "CALL 0x68ED"),
    _indirect_data("3F:567B", "ed69", "out", "OUT (C),L"),
    _indirect_operand("3F:5C92", "ed68", "in", "IN L,(C)", "3F:5C91", "CALL 0x68ED"),
    _indirect_operand("3F:63E0", "ed68", "in", "IN L,(C)", "3F:63DF", "CALL 0x68ED"),
    _indirect_operand("3F:6C1A", "ed68", "in", "IN L,(C)", "3F:6C19", "CALL 0x68ED"),
    _indirect_operand("3F:6C2A", "ed68", "in", "IN L,(C)", "3F:6C29", "CALL 0x68ED"),
    _indirect_operand("3F:6C37", "ed68", "in", "IN L,(C)", "3F:6C36", "CALL 0x68ED"),
    _indirect_operand("3F:6C54", "ed68", "in", "IN L,(C)", "3F:6C53", "CALL 0x68ED"),
    _indirect_operand("3F:6C70", "ed68", "in", "IN L,(C)", "3F:6C6F", "CALL 0x68ED"),
    _indirect_operand("3F:6C90", "ed68", "in", "IN L,(C)", "3F:6C8F", "CALL 0x68ED"),
)


def scan_unlisted_direct_io(
    rom: RomImage,
    port_definitions: Mapping[int, PortDefinition],
    *,
    executable: str = "z80dasm",
) -> tuple[UnlistedIOCandidate, ...]:
    """Generate aligned, non-descriptor candidates for every unlabeled port."""

    candidates = []
    for page in range(rom.page_count):
        instructions = disassemble_page(rom, page, executable=executable)
        for access in iter_direct_io_accesses(instructions):
            instruction = access.instruction
            if access.port in port_definitions:
                continue
            if inline_descriptor_at(rom, instruction.location) is not None:
                continue
            candidates.append(
                UnlistedIOCandidate(
                    instruction.location,
                    instruction.data,
                    access.direction,
                    access.port,
                    instruction.text,
                )
            )
    return tuple(candidates)


def reconcile_unlisted_io(
    rom: RomImage,
    candidates: Iterable[UnlistedIOCandidate],
    reviews: Iterable[CandidateReview] = RETAIL_REVIEWS,
) -> RomIOCoverage:
    """Require one exact review for every candidate and reject manifest drift."""

    candidate_items = tuple(candidates)
    review_items = tuple(reviews)
    candidate_counts = Counter(candidate.location for candidate in candidate_items)
    duplicate_candidates = tuple(sorted(
        (location for location, count in candidate_counts.items() if count > 1),
        key=lambda location: (location.page, location.address),
    ))
    review_counts = Counter(review.location for review in review_items)
    duplicate_reviews = tuple(sorted(
        (location for location, count in review_counts.items() if count > 1),
        key=lambda location: (location.page, location.address),
    ))
    review_by_location = {review.location: review for review in review_items}
    candidate_by_location = {
        candidate.location: candidate for candidate in candidate_items
    }
    reviewed = []
    missing = []
    drift = []
    for candidate in candidate_items:
        review = review_by_location.get(candidate.location)
        if review is None:
            missing.append(candidate)
            continue
        expected = (review.data, review.direction, review.port)
        actual = (candidate.data, candidate.direction, candidate.port)
        if expected != actual:
            drift.append(
                f"{candidate.location}: expected {review.data.hex()} "
                f"{review.direction} 0x{review.port:02X}, got "
                f"{candidate.data.hex()} {candidate.direction} 0x{candidate.port:02X}"
            )
            continue
        reviewed.append(ReviewedCandidate(candidate, review))
    stale = tuple(
        review
        for review in review_items
        if review.location not in candidate_by_location
    )
    return RomIOCoverage(
        sha256(rom.data).hexdigest(),
        candidate_items,
        tuple(reviewed),
        tuple(missing),
        stale,
        duplicate_candidates,
        duplicate_reviews,
        tuple(drift),
    )


def audit_unlisted_io(
    rom: RomImage,
    port_definitions: Mapping[int, PortDefinition],
    *,
    executable: str = "z80dasm",
    reviews: Iterable[CandidateReview] = RETAIL_REVIEWS,
) -> RomIOCoverage:
    """Scan and reconcile all aligned non-descriptor unlisted-port candidates."""

    candidates = scan_unlisted_direct_io(
        rom, port_definitions, executable=executable
    )
    return reconcile_unlisted_io(rom, candidates, reviews)


def scan_resolved_indirect_io(
    rom: RomImage, *, executable: str = "z80dasm"
) -> tuple[ResolvedIndirectIO, ...]:
    """Resolve literal C-register ports in aligned linear disassembly."""

    resolved = []
    for page in range(rom.page_count):
        instructions = disassemble_page(rom, page, executable=executable)
        for access in iter_resolved_io_accesses(instructions):
            if access.source != "register-c":
                continue
            resolved.append(
                ResolvedIndirectIO(
                    access.instruction.location,
                    access.direction,
                    access.port,
                    access.instruction.text,
                )
            )
    return tuple(resolved)


def reconcile_indirect_io(
    rom: RomImage,
    candidates: Iterable[RawIndirectIO],
    resolved: Iterable[ResolvedIndirectIO],
    reviews: Iterable[IndirectIOReview] = RETAIL_INDIRECT_REVIEWS,
    *,
    boundary_prefixes: Iterable[RomLocation] = (),
) -> IndirectIOCoverage:
    """Require a drift-free review of every raw indirect-I/O opcode pair."""

    candidate_items = tuple(candidates)
    resolved_items = tuple(resolved)
    review_items = tuple(reviews)
    boundary_prefix_items = tuple(boundary_prefixes)
    candidate_counts = Counter(candidate.location for candidate in candidate_items)
    duplicate_candidates = tuple(
        sorted(
            (
                location
                for location, count in candidate_counts.items()
                if count > 1
            ),
            key=lambda location: (location.page, location.address),
        )
    )
    review_counts = Counter(review.location for review in review_items)
    duplicate_reviews = tuple(
        sorted(
            (
                location
                for location, count in review_counts.items()
                if count > 1
            ),
            key=lambda location: (location.page, location.address),
        )
    )
    review_by_location = {review.location: review for review in review_items}
    candidate_by_location = {
        candidate.location: candidate for candidate in candidate_items
    }
    resolved_by_location = {item.location: item for item in resolved_items}
    reviewed = []
    missing = []
    drift = []
    for candidate in candidate_items:
        review = review_by_location.get(candidate.location)
        if review is None:
            missing.append(candidate)
            continue
        expected = (review.data, review.direction, review.form)
        actual = (candidate.data, candidate.direction, candidate.form)
        if expected != actual:
            drift.append(
                f"{candidate.location}: expected {review.data.hex()} "
                f"{review.direction} {review.form}, got {candidate.data.hex()} "
                f"{candidate.direction} {candidate.form}"
            )
            continue
        resolution = resolved_by_location.get(candidate.location)
        actual_port = None if resolution is None else resolution.port
        if review.resolved_port != actual_port:
            expected_port = (
                "unresolved"
                if review.resolved_port is None
                else f"0x{review.resolved_port:02X}"
            )
            observed_port = (
                "unresolved" if actual_port is None else f"0x{actual_port:02X}"
            )
            drift.append(
                f"{candidate.location}: expected port {expected_port}, "
                f"got {observed_port}"
            )
            continue
        reviewed.append(ReviewedIndirectIO(candidate, review))
    stale = tuple(
        review for review in review_items if review.location not in candidate_by_location
    )
    for resolution in resolved_items:
        if resolution.location not in candidate_by_location:
            drift.append(
                f"{resolution.location}: resolved 0x{resolution.port:02X} "
                "without a raw indirect-I/O candidate"
            )
    return IndirectIOCoverage(
        sha256(rom.data).hexdigest(),
        candidate_items,
        resolved_items,
        tuple(reviewed),
        tuple(missing),
        stale,
        duplicate_candidates,
        duplicate_reviews,
        boundary_prefix_items,
        tuple(drift),
    )


def audit_indirect_io(
    rom: RomImage,
    *,
    executable: str = "z80dasm",
    reviews: Iterable[IndirectIOReview] = RETAIL_INDIRECT_REVIEWS,
) -> IndirectIOCoverage:
    """Audit every raw register and block-I/O opcode pair in the ROM."""

    candidates = raw_indirect_io_locations(rom)
    resolved = scan_resolved_indirect_io(rom, executable=executable)
    boundary_prefixes = raw_indirect_io_boundary_prefixes(rom)
    return reconcile_indirect_io(
        rom,
        candidates,
        resolved,
        reviews,
        boundary_prefixes=boundary_prefixes,
    )
