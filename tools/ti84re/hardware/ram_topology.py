"""Decode the restoring RAM-selector alias probe without assuming two topologies."""

from __future__ import annotations

from dataclasses import dataclass

RAM_ALIAS_SELECTORS = tuple(range(0x82, 0x88))
RAM_ALIAS_PATTERNS = bytes((0x11, 0x22, 0x33, 0x44, 0x55, 0x66))
RAM_ALIAS_PAYLOAD_SIZE = 18


def _exact_bytes(values: bytes, name: str, size: int) -> bytes:
    if len(values) != size:
        raise ValueError(f"{name} must contain {size} bytes, got {len(values)}")
    return values


def infer_alias_groups(
    observed: bytes,
    *,
    selectors: tuple[int, ...] = RAM_ALIAS_SELECTORS,
    patterns: bytes = RAM_ALIAS_PATTERNS,
) -> tuple[tuple[int, ...], ...] | None:
    """Infer selector equivalence classes from the probe's ordered writes.

    The probe writes one unique pattern through each selector in ascending
    order. Every selector in one alias group must therefore read the pattern
    written through the highest-numbered selector in that group. ``None``
    means the bytes cannot arise from that model.
    """

    if len(selectors) != len(patterns):
        raise ValueError("selectors and patterns must have equal lengths")
    if len(set(selectors)) != len(selectors) or len(set(patterns)) != len(patterns):
        raise ValueError("selectors and patterns must be unique")
    if tuple(sorted(selectors)) != selectors:
        raise ValueError("selectors must be in ascending write order")
    observed = _exact_bytes(observed, "observed sequence", len(selectors))

    writer_for_pattern = {
        pattern: selector for selector, pattern in zip(selectors, patterns, strict=True)
    }
    groups: dict[int, list[int]] = {}
    for selector, value in zip(selectors, observed, strict=True):
        writer = writer_for_pattern.get(value)
        if writer is None:
            return None
        groups.setdefault(writer, []).append(selector)

    inferred = tuple(
        tuple(members)
        for _, members in sorted(groups.items(), key=lambda item: min(item[1]))
    )
    if any(max(group) != writer for writer, group in groups.items()):
        return None
    return inferred


def topology_name(groups: tuple[tuple[int, ...], ...] | None) -> str:
    """Return the stable user-facing classification for inferred groups."""

    if groups is None:
        return "mixed-or-unexpected"
    if len(groups) == len(RAM_ALIAS_SELECTORS) and all(
        len(group) == 1 for group in groups
    ):
        return "independent-selectors"
    if len(groups) == 1 and groups[0] == RAM_ALIAS_SELECTORS:
        return "selectors-82-through-87-alias"
    return "partial-selector-aliases"


@dataclass(frozen=True)
class RamTopologyObservation:
    """Decoded original, patterned, and restored RAM-selector reads."""

    original: bytes
    observed: bytes
    restored: bytes
    alias_groups: tuple[tuple[int, ...], ...] | None

    def __post_init__(self) -> None:
        for name, values in (
            ("original", self.original),
            ("observed", self.observed),
            ("restored", self.restored),
        ):
            _exact_bytes(values, name, len(RAM_ALIAS_SELECTORS))
        expected_groups = infer_alias_groups(self.observed)
        if self.alias_groups != expected_groups:
            raise ValueError("alias groups do not match the observed sequence")

    @property
    def restore_matches(self) -> bool:
        return self.restored == self.original

    @property
    def topology(self) -> str:
        return topology_name(self.alias_groups)

    def to_dict(self) -> dict[str, object]:
        return {
            "selectors": [f"0x{selector:02X}" for selector in RAM_ALIAS_SELECTORS],
            "original": self.original.hex().upper(),
            "observed": self.observed.hex().upper(),
            "restored": self.restored.hex().upper(),
            "restore_matches": self.restore_matches,
            "topology_observation": self.topology,
            "alias_groups": (
                None
                if self.alias_groups is None
                else [
                    [f"0x{selector:02X}" for selector in group]
                    for group in self.alias_groups
                ]
            ),
        }


def decode_ram_alias_payload(payload: bytes) -> RamTopologyObservation:
    """Decode the 18-byte payload emitted by ``HWPRAM``."""

    if len(payload) != RAM_ALIAS_PAYLOAD_SIZE:
        raise ValueError(
            f"RAM alias payload must contain {RAM_ALIAS_PAYLOAD_SIZE} bytes, "
            f"got {len(payload)}"
        )
    original = payload[0:6]
    observed = payload[6:12]
    restored = payload[12:18]
    return RamTopologyObservation(
        original=original,
        observed=observed,
        restored=restored,
        alias_groups=infer_alias_groups(observed),
    )


def simulate_alias_writes(
    backing_ids: tuple[int, ...],
    *,
    patterns: bytes = RAM_ALIAS_PATTERNS,
) -> bytes:
    """Return probe reads for an explicit selector-to-backing assignment."""

    if len(backing_ids) != len(RAM_ALIAS_SELECTORS):
        raise ValueError(
            f"backing assignment must contain {len(RAM_ALIAS_SELECTORS)} values"
        )
    if len(patterns) != len(backing_ids):
        raise ValueError("patterns and backing assignment must have equal lengths")
    backing: dict[int, int] = {}
    for backing_id, pattern in zip(backing_ids, patterns, strict=True):
        backing[backing_id] = pattern
    return bytes(backing[backing_id] for backing_id in backing_ids)
