"""Audit the system-flag word normalized by the legacy backup sender.

The ROM-facing part of this module is deliberately mechanical.  It reports
which bits the fixed word selects and counts exact ``BIT``, ``RES``, and
``SET`` candidates for ``(IY+0)`` and ``(IY+1)``.  Symbol names come from the
bundled public include and remain separate from the ROM scan.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from indexed_flags import scan_indexed_bit_references
from rom_image import RomImage
from ti8x_backup import LEGACY_SYSTEM_FLAGS_WORD

PUBLIC_FLAG_SYMBOLS = {
    (0, 0): "inDelete",
    (0, 2): "trigDeg",
    (0, 3): "kbdSCR",
    (0, 4): "kbdKeyPress",
    (0, 5): "donePrgm",
    (1, 2): "editOpen",
    (1, 3): "AnsScroll",
    (1, 4): "monAbandon",
}


@dataclass(frozen=True)
class SystemFlagBitAudit:
    """One bit in the two-byte flags image emitted by the backup sender."""

    byte_offset: int
    bit: int
    normalized_value: int
    public_symbol: str | None
    bit_tests: int
    resets: int
    sets: int

    @property
    def direct_reference_count(self) -> int:
        return self.bit_tests + self.resets + self.sets

    def as_dict(self) -> dict[str, object]:
        return {
            "byte_offset": self.byte_offset,
            "bit": self.bit,
            "normalized_value": self.normalized_value,
            "public_symbol": self.public_symbol,
            "bit_tests": self.bit_tests,
            "resets": self.resets,
            "sets": self.sets,
            "direct_reference_count": self.direct_reference_count,
        }


def audit_legacy_system_flags(
    rom: RomImage,
) -> tuple[SystemFlagBitAudit, ...]:
    """Return a bitwise audit of the fixed ``0x0063`` system-flags word.

    Counts cover exact memory-only indexed bit instructions.  Linear ROM data
    can contain instruction-shaped bytes, so callers must still confirm the
    surrounding control flow before assigning semantics to a candidate.
    """

    rows = []
    for byte_offset in range(2):
        normalized_byte = (LEGACY_SYSTEM_FLAGS_WORD >> (8 * byte_offset)) & 0xFF
        for bit in range(8):
            references = scan_indexed_bit_references(
                rom,
                displacement=byte_offset,
                bit=bit,
                index_register="iy",
            )
            counts = Counter(reference.operation for reference in references)
            rows.append(
                SystemFlagBitAudit(
                    byte_offset=byte_offset,
                    bit=bit,
                    normalized_value=(normalized_byte >> bit) & 1,
                    public_symbol=PUBLIC_FLAG_SYMBOLS.get((byte_offset, bit)),
                    bit_tests=counts["bit"],
                    resets=counts["res"],
                    sets=counts["set"],
                )
            )
    return tuple(rows)
