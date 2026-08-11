#!/usr/bin/env python3
"""Regression tests for TI-8x backup parsing and ROM DATA framing."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ti8x_backup import (
    BackupFormatError,
    LEGACY_SYSTEM_FLAGS_WORD,
    LEGACY_SYSTEM_SECTION_LENGTH,
    backup_checksum,
    parse_backup,
    rom_data_payload,
)


def synthetic_backup(
    *,
    header_size: int = 12,
    sections: tuple[bytes, bytes, bytes] = (b"\x63\x00abc", b"de", b"fgh"),
    data_region_length: int | None = None,
) -> bytes:
    lengths = tuple(map(len, sections))
    version = 6 if header_size == 12 else 0
    header = bytearray()
    header += lengths[0].to_bytes(2, "little")
    header += b"\x13"
    header += lengths[1].to_bytes(2, "little")
    header += lengths[2].to_bytes(2, "little")
    header += (0x9D95).to_bytes(2, "little")
    if header_size == 12:
        header += b"\x00\x00" + bytes((version,))
    body = bytearray()
    for index, section in enumerate(sections, start=1):
        if index == 3 and not section:
            continue
        body += len(section).to_bytes(2, "little") + section
    checksum = backup_checksum(
        header_size=header_size,
        section_lengths=lengths,
        type_id=0x13,
        memory_address=0x9D95,
        version=version,
        sections=sections,
    )
    if data_region_length is None:
        data_region_length = sum(lengths) + 17
    return (
        b"**TI83F*"
        + b"\x1A\x0A\x00"
        + b"test".ljust(42, b"\x00")
        + data_region_length.to_bytes(2, "little")
        + header_size.to_bytes(2, "little")
        + header
        + body
        + checksum.to_bytes(2, "little")
    )


class RomDataPayloadTests(unittest.TestCase):
    def test_oversized_backup_section_is_capped_and_normalized(self):
        source = bytes(index & 0xFF for index in range(0x13A5))
        result = rom_data_payload(source, snd_rec_state=0x08, var_class=0x0A)

        self.assertTrue(result.normalized_system_flags)
        self.assertEqual(LEGACY_SYSTEM_SECTION_LENGTH, result.length)
        self.assertEqual(
            LEGACY_SYSTEM_FLAGS_WORD,
            int.from_bytes(result.payload[:2], "little"),
        )
        self.assertEqual(source[2:LEGACY_SYSTEM_SECTION_LENGTH], result.payload[2:])
        self.assertEqual(sum(result.payload) & 0xFFFF, result.checksum)

    def test_equal_length_and_other_states_are_unchanged(self):
        source = bytes(LEGACY_SYSTEM_SECTION_LENGTH)
        equal = rom_data_payload(source, snd_rec_state=0x08, var_class=0x0A)
        other = rom_data_payload(source + b"x", snd_rec_state=0x15, var_class=0x0A)

        self.assertFalse(equal.normalized_system_flags)
        self.assertEqual(source, equal.payload)
        self.assertFalse(other.normalized_system_flags)
        self.assertEqual(source + b"x", other.payload)


class BackupParserTests(unittest.TestCase):
    def test_extended_backup_round_trip(self):
        backup = parse_backup(synthetic_backup())

        self.assertEqual("**TI83F*", backup.signature)
        self.assertEqual(12, backup.header_size)
        self.assertEqual(6, backup.version)
        self.assertEqual((5, 2, 3), backup.section_lengths)
        self.assertEqual(b"\x63\x00", backup.sections[0][:2])
        self.assertTrue(backup.data_region_length_valid)
        self.assertTrue(backup.checksum_valid)

    def test_old_nine_byte_header_has_zero_version(self):
        backup = parse_backup(synthetic_backup(header_size=9))
        self.assertEqual(0, backup.version)
        self.assertTrue(backup.checksum_valid)

    def test_mismatched_section_length_is_rejected(self):
        data = bytearray(synthetic_backup())
        section_length_offset = 55 + 2 + 12
        data[section_length_offset : section_length_offset + 2] = b"\x04\x00"
        with self.assertRaises(BackupFormatError):
            parse_backup(bytes(data))

    def test_empty_third_section_omits_its_repeated_length(self):
        backup = parse_backup(
            synthetic_backup(sections=(b"\x63\x00abc", b"de", b""))
        )

        self.assertEqual((5, 2, 0), backup.section_lengths)
        self.assertEqual(b"", backup.sections[2])
        self.assertTrue(backup.checksum_valid)

    def test_outer_data_region_length_is_reported_independently(self):
        backup = parse_backup(synthetic_backup(data_region_length=1))

        self.assertEqual(1, backup.data_region_length)
        self.assertEqual(27, backup.expected_data_region_length)
        self.assertFalse(backup.data_region_length_valid)
        self.assertTrue(backup.checksum_valid)

    def test_ti86_four_section_format_is_rejected(self):
        data = bytearray(synthetic_backup())
        data[:8] = b"**TI86**"
        with self.assertRaises(BackupFormatError):
            parse_backup(bytes(data))


if __name__ == "__main__":
    unittest.main()
