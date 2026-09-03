"""Extract and compare length-prefixed Flash workers from a paged ROM."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256

from ti84re.rom.image import RomImage, RomLocation


@dataclass(frozen=True)
class LengthPrefixedWorker:
    """A two-byte little-endian length followed by RAM-worker code."""

    descriptor: RomLocation
    entry: RomLocation
    code: bytes

    @property
    def length(self) -> int:
        return len(self.code)

    @property
    def sha256(self) -> str:
        return sha256(self.code).hexdigest()


@dataclass(frozen=True)
class WorkerDifference:
    """One nonmatching byte span from a sequence comparison."""

    operation: str
    left_offset: int
    left_bytes: bytes
    right_offset: int
    right_bytes: bytes


@dataclass(frozen=True)
class WorkerComparison:
    """Matching-byte total and edit spans for two workers."""

    left: LengthPrefixedWorker
    right: LengthPrefixedWorker
    matching_bytes: int
    differences: tuple[WorkerDifference, ...]


def extract_length_prefixed_worker(
    rom: RomImage, descriptor: RomLocation
) -> LengthPrefixedWorker:
    """Extract a worker whose descriptor starts with a little-endian length."""

    length = rom.u16le(descriptor.page, descriptor.address)
    entry = RomLocation(descriptor.page, descriptor.address + 2)
    code = rom.bytes_at(entry.page, entry.address, length)
    return LengthPrefixedWorker(descriptor, entry, code)


def compare_workers(
    left: LengthPrefixedWorker, right: LengthPrefixedWorker
) -> WorkerComparison:
    """Compare workers without assuming that their entries have equal length."""

    matcher = SequenceMatcher(None, left.code, right.code, autojunk=False)
    matching_bytes = 0
    differences = []
    for (
        operation,
        left_start,
        left_end,
        right_start,
        right_end,
    ) in matcher.get_opcodes():
        if operation == "equal":
            matching_bytes += left_end - left_start
            continue
        differences.append(
            WorkerDifference(
                operation=operation,
                left_offset=left_start,
                left_bytes=left.code[left_start:left_end],
                right_offset=right_start,
                right_bytes=right.code[right_start:right_end],
            )
        )
    return WorkerComparison(left, right, matching_bytes, tuple(differences))
