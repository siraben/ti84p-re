"""Reusable checks for binary dumps produced by hardware trace fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoryExpectation:
    """Expected bytes at one file offset in a binary memory dump."""

    name: str
    dump: Path
    offset: int
    expected: bytes


class MemoryMismatch(ValueError):
    """A dump is missing, too short, or contains unexpected bytes."""


def read_memory_region(path: Path, offset: int, length: int) -> bytes:
    """Read an exact region from *path* and reject truncated dumps."""

    if offset < 0:
        raise ValueError("offset must be nonnegative")
    if length < 0:
        raise ValueError("length must be nonnegative")
    try:
        with path.open("rb") as fp:
            fp.seek(offset)
            data = fp.read(length)
    except FileNotFoundError as error:
        raise MemoryMismatch(f"missing memory dump: {path}") from error
    if len(data) != length:
        raise MemoryMismatch(
            f"{path}: offset 0x{offset:X} has {len(data)} byte(s), "
            f"expected {length}"
        )
    return data


def check_memory_expectation(expectation: MemoryExpectation) -> bytes:
    """Return matching bytes or raise :class:`MemoryMismatch`."""

    actual = read_memory_region(
        expectation.dump, expectation.offset, len(expectation.expected)
    )
    if actual != expectation.expected:
        raise MemoryMismatch(
            f"{expectation.name} at dump offset 0x{expectation.offset:X} was "
            f"{actual.hex()}, expected {expectation.expected.hex()}"
        )
    return actual
