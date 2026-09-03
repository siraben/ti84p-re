"""Decode TI-8x backup files and reproduce the ROM's DATA transformation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


LEGACY_SYSTEM_SECTION_LENGTH = 0x037D
LEGACY_SYSTEM_FLAGS_WORD = 0x0063
SYSTEM_FLAGS_ADDRESS = 0x89F0
SYSTEM_SECTION_SOURCE_LENGTH = 0x13A5


class BackupFormatError(ValueError):
    """A backup file or ROM DATA source is structurally invalid."""


@dataclass(frozen=True)
class RomDataPayload:
    """The DATA length and bytes produced by the page-3C sender."""

    source_length: int
    payload: bytes
    normalized_system_flags: bool

    @property
    def length(self) -> int:
        return len(self.payload)

    @property
    def checksum(self) -> int:
        return sum(self.payload) & 0xFFFF

    def as_dict(self) -> dict[str, object]:
        return {
            "source_length": self.source_length,
            "payload_length": self.length,
            "checksum": self.checksum,
            "normalized_system_flags": self.normalized_system_flags,
            "prefix": self.payload[:2].hex(),
        }


@dataclass(frozen=True)
class Ti8xBackup:
    """A three-section, non-TI-86 TI-8x backup file."""

    signature: str
    marker: bytes
    comment: str
    data_region_length: int
    header_size: int
    section_lengths: tuple[int, int, int]
    type_id: int
    memory_address: int
    version: int
    sections: tuple[bytes, bytes, bytes]
    stored_checksum: int
    computed_checksum: int

    @property
    def checksum_valid(self) -> bool:
        return self.stored_checksum == self.computed_checksum

    @property
    def expected_data_region_length(self) -> int:
        """Return the outer length emitted by libtifiles for this format."""

        return sum(self.section_lengths) + 17

    @property
    def data_region_length_valid(self) -> bool:
        return self.data_region_length == self.expected_data_region_length

    def as_dict(self) -> dict[str, object]:
        return {
            "signature": self.signature,
            "marker": self.marker.hex(),
            "comment": self.comment,
            "data_region_length": self.data_region_length,
            "expected_data_region_length": self.expected_data_region_length,
            "data_region_length_valid": self.data_region_length_valid,
            "header_size": self.header_size,
            "section_lengths": list(self.section_lengths),
            "type_id": self.type_id,
            "memory_address": self.memory_address,
            "version": self.version,
            "section_prefixes": [section[:2].hex() for section in self.sections],
            "stored_checksum": self.stored_checksum,
            "computed_checksum": self.computed_checksum,
            "checksum_valid": self.checksum_valid,
        }


def rom_data_payload(
    source: bytes,
    *,
    snd_rec_state: int,
    var_class: int,
) -> RomDataPayload:
    """Apply the special case at ``3C:40F5``–``3C:4137``.

    The backup case is a RAM-image normalization.  It sends exactly 0x037D
    bytes, replacing the source word at ``flags`` with 0x0063.
    """

    if not 0 <= snd_rec_state <= 0xFF or not 0 <= var_class <= 0xFF:
        raise ValueError("state and variable class must be bytes")
    normalize = (
        snd_rec_state == 0x08
        and var_class == 0x0A
        and len(source) > LEGACY_SYSTEM_SECTION_LENGTH
    )
    if not normalize:
        return RomDataPayload(len(source), source, False)
    payload = (
        LEGACY_SYSTEM_FLAGS_WORD.to_bytes(2, "little")
        + source[2:LEGACY_SYSTEM_SECTION_LENGTH]
    )
    return RomDataPayload(len(source), payload, True)


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read(self, length: int, label: str) -> bytes:
        end = self.offset + length
        if length < 0 or end > len(self.data):
            raise BackupFormatError(
                f"truncated {label} at file offset 0x{self.offset:X}"
            )
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u8(self, label: str) -> int:
        return self.read(1, label)[0]

    def u16(self, label: str) -> int:
        return int.from_bytes(self.read(2, label), "little")


def backup_checksum(
    *,
    header_size: int,
    section_lengths: tuple[int, int, int],
    type_id: int,
    memory_address: int,
    version: int,
    sections: tuple[bytes, bytes, bytes],
) -> int:
    """Compute the checksum used by libtifiles for a three-part backup."""

    total = header_size + type_id
    for length in section_lengths:
        total += sum(length.to_bytes(2, "little"))
    total += sum(memory_address.to_bytes(2, "little"))
    if header_size >= 12:
        total += version
    for length, section in zip(section_lengths, sections, strict=True):
        if len(section) != length:
            raise BackupFormatError(
                f"section has 0x{len(section):X} bytes, expected 0x{length:X}"
            )
        total += sum(length.to_bytes(2, "little")) + sum(section)
    return total & 0xFFFF


def parse_backup(data: bytes) -> Ti8xBackup:
    """Parse a three-section, non-TI-86 TI-8x backup."""

    reader = _Reader(data)
    signature_bytes = reader.read(8, "signature")
    try:
        signature = signature_bytes.decode("ascii")
    except UnicodeDecodeError as error:
        raise BackupFormatError("backup signature is not ASCII") from error
    if not signature.startswith("**TI"):
        raise BackupFormatError(f"unrecognized backup signature {signature!r}")
    if signature == "**TI86**":
        raise BackupFormatError("four-section TI-86 backups are not supported")
    marker = reader.read(3, "file marker")
    comment = reader.read(42, "comment").split(b"\x00", 1)[0].decode(
        "latin-1"
    )
    data_region_length = reader.u16("data-region length")
    header_size = reader.u16("backup-header size")
    if not 9 <= header_size <= 12:
        raise BackupFormatError(
            f"backup-header size must be 9–12 bytes, got {header_size}"
        )

    length1 = reader.u16("section-1 header length")
    type_id = reader.u8("backup type")
    length2 = reader.u16("section-2 header length")
    length3 = reader.u16("section-3 header length")
    memory_address = reader.u16("memory address")
    extra = reader.read(header_size - 9, "extended backup header")
    version = extra[2] if len(extra) >= 3 else 0
    section_lengths = (length1, length2, length3)

    sections: list[bytes] = []
    for index, expected_length in enumerate(section_lengths, start=1):
        # libtifiles omits both this word and the data for an empty third
        # section.  It always emits the first two repeated length words.
        if index == 3 and expected_length == 0:
            sections.append(b"")
            continue
        stored_length = reader.u16(f"section-{index} stored length")
        if stored_length != expected_length:
            raise BackupFormatError(
                f"section {index} stores length 0x{stored_length:X}, "
                f"header declares 0x{expected_length:X}"
            )
        sections.append(reader.read(stored_length, f"section-{index} data"))
    stored_checksum = reader.u16("checksum")
    if reader.offset != len(data):
        raise BackupFormatError(
            f"0x{len(data) - reader.offset:X} trailing byte(s) after checksum"
        )
    section_tuple = (sections[0], sections[1], sections[2])
    computed_checksum = backup_checksum(
        header_size=header_size,
        section_lengths=section_lengths,
        type_id=type_id,
        memory_address=memory_address,
        version=version,
        sections=section_tuple,
    )
    return Ti8xBackup(
        signature=signature,
        marker=marker,
        comment=comment,
        data_region_length=data_region_length,
        header_size=header_size,
        section_lengths=section_lengths,
        type_id=type_id,
        memory_address=memory_address,
        version=version,
        sections=section_tuple,
        stored_checksum=stored_checksum,
        computed_checksum=computed_checksum,
    )


def parse_backup_path(path: Path) -> Ti8xBackup:
    return parse_backup(path.read_bytes())
