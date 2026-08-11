#!/usr/bin/env python3
"""Regression tests for the certificate rebuild structural analysis."""

import unittest
from pathlib import Path

from certificate_rebuild import (
    analyze_certificate_rebuild,
    CertificateRebuildSignatureError,
    find_bjump_mode_calls,
    find_direct_mode_calls,
    TAIL_BLOCKS,
    TAIL_LENGTH,
    TAIL_START,
)
from rom_image import RomImage, RomLocation


ROM = Path(__file__).resolve().parent / "rom.bin"


class CertificateRebuildTests(unittest.TestCase):
    def test_tail_blocks_form_one_contiguous_partition(self):
        cursor = TAIL_START
        for block in TAIL_BLOCKS:
            self.assertEqual(cursor, block.offset)
            cursor = block.end
        self.assertEqual(TAIL_START + TAIL_LENGTH, cursor)

    def test_finds_raw_mode_load_call_candidates(self):
        data = bytearray(b"\xFF" * (0x3E * 0x4000))
        offset = 0x3D * 0x4000 + 0x0123
        data[offset : offset + 5] = bytes.fromhex("3E05CDF140")

        calls = find_direct_mode_calls(RomImage(bytes(data)))

        self.assertEqual(1, len(calls))
        self.assertEqual(5, calls[0].mode)
        self.assertEqual(RomLocation(0x3D, 0x4123), calls[0].load)
        self.assertEqual(RomLocation(0x3D, 0x4125), calls[0].call)

    def test_rejects_rom_without_page_3d(self):
        with self.assertRaisesRegex(CertificateRebuildSignatureError, "page 0x3D"):
            analyze_certificate_rebuild(RomImage(bytes(0x4000)))

    def test_rejects_signature_mismatch(self):
        rom = RomImage.from_path(ROM)
        data = bytearray(rom.data)
        data[0x3D * 0x4000 + 0x00F1] ^= 0xFF

        with self.assertRaisesRegex(
            CertificateRebuildSignatureError, "signature mismatch at 3D:40F1"
        ):
            analyze_certificate_rebuild(RomImage(bytes(data)))

    def test_pinned_rom_reports_all_modes_and_direct_calls(self):
        result = analyze_certificate_rebuild(RomImage.from_path(ROM))

        self.assertEqual(tuple(range(7)), tuple(mode.mode for mode in result.modes))
        self.assertEqual(
            (0, 1, 2, 5, 6), tuple(call.mode for call in result.direct_calls)
        )
        self.assertEqual(
            (0x66C7, 0x5774, 0x437E, 0x51D7, 0x7D87),
            tuple(call.call.address for call in result.direct_calls),
        )

    def test_pinned_rom_reports_cross_page_mode_calls(self):
        calls = find_bjump_mode_calls(RomImage.from_path(ROM))

        self.assertEqual((4, 3), tuple(call.mode for call in calls))
        self.assertEqual(
            (RomLocation(0x3C, 0x7313), RomLocation(0x3C, 0x7558)),
            tuple(call.call for call in calls),
        )
        self.assertEqual(
            (RomLocation(0, 0x2B77), RomLocation(0, 0x2B77)),
            tuple(call.stub for call in calls),
        )

    def test_pinned_rom_reports_app_validity_update_shape(self):
        result = analyze_certificate_rebuild(RomImage.from_path(ROM))
        update = result.app_validity

        self.assertEqual(0x1FE1, update.bitmap_offset)
        self.assertEqual("least-significant bit first", update.bit_order)
        self.assertEqual(5, update.set_rebuild_mode)
        self.assertEqual(0x8021, update.clear_bcall_id)

    def test_pinned_rom_reports_resolved_mode_owners(self):
        result = analyze_certificate_rebuild(RomImage.from_path(ROM))

        self.assertEqual(
            (0, 1, 2, 2, 3, 4, 6),
            tuple(owner.mode for owner in result.mode_owners),
        )
        self.assertEqual(
            RomLocation(0x35, 0x7205), result.mode_owners[0].call_chain[0]
        )
        self.assertEqual(
            RomLocation(0x3D, 0x5759), result.mode_owners[1].call_chain[-2]
        )
        self.assertEqual(
            RomLocation(0x3C, 0x5714), result.mode_owners[2].call_chain[1]
        )
        self.assertEqual(
            RomLocation(0x3C, 0x550D), result.mode_owners[3].owner_entry
        )
        self.assertEqual(
            RomLocation(0x3D, 0x5094), result.mode_owners[3].call_chain[-2]
        )
        self.assertEqual(
            RomLocation(0x00, 0x2B77), result.mode_owners[4].call_chain[-2]
        )
        self.assertEqual(
            RomLocation(0x3C, 0x72A5), result.mode_owners[5].call_chain[1]
        )
        self.assertEqual(
            RomLocation(0x3D, 0x7C1B), result.mode_owners[6].owner_entry
        )

    def test_pinned_rom_reports_os_validity_flag(self):
        result = analyze_certificate_rebuild(RomImage.from_path(ROM))
        validity = result.os_validity

        self.assertEqual(0x1FE0, validity.offset)
        self.assertEqual(0x01, validity.mask)
        self.assertTrue(validity.valid_when_clear)
        self.assertEqual(0x8093, validity.mark_invalid_bcall_id)
        self.assertEqual(RomLocation(0x3F, 0x5209), validity.mark_invalid_entry)
        self.assertEqual(0x8099, validity.mark_valid_bcall_id)
        self.assertEqual(RomLocation(0x3F, 0x51F5), validity.mark_valid_entry)
        self.assertEqual(0x809C, validity.check_bcall_id)
        self.assertEqual(RomLocation(0x3F, 0x52C6), validity.check_entry)
        self.assertEqual(0x1F18, validity.invalid_rebuild_span.offset)
        self.assertEqual(0x00E8, validity.invalid_rebuild_span.length)

    def test_pinned_rom_maps_app_restriction_api_to_mode_6(self):
        result = analyze_certificate_rebuild(RomImage.from_path(ROM))
        restrictions = result.app_restrictions

        self.assertEqual(0x52F6, restrictions.set_bcall_id)
        self.assertEqual(RomLocation(0x3D, 0x7B9B), restrictions.set_entry)
        self.assertEqual(0x52F9, restrictions.remove_bcall_id)
        self.assertEqual(RomLocation(0x3D, 0x7C1B), restrictions.remove_entry)
        self.assertEqual(0x52FC, restrictions.query_bcall_id)
        self.assertEqual(RomLocation(0x3D, 0x7CBA), restrictions.query_entry)
        self.assertEqual(0x1DD2, restrictions.control_span.offset)
        self.assertEqual(0x000E, restrictions.control_span.length)
        self.assertEqual(0x1DD2, restrictions.control_offset)
        self.assertEqual(0x1DD3, restrictions.record_offset)
        self.assertEqual(0x1DD3, restrictions.app_bitmap_offset)
        self.assertEqual(0x000D, restrictions.app_bitmap_length)
        self.assertEqual(8, restrictions.app_page_bias)
        self.assertEqual((0x01, 0x02, 0x04), (
            restrictions.base_mask,
            restrictions.logbase_mask,
            restrictions.summation_mask,
        ))
        self.assertEqual(6, restrictions.remove_rebuild_mode)
        self.assertEqual(tuple(range(8)), tuple(
            behavior.value for behavior in restrictions.types
        ))
        self.assertEqual("logBASE disabled", restrictions.types[6].role)
        self.assertEqual("summation disabled", restrictions.types[7].role)

    def test_pinned_rom_reports_per_app_trial_table(self):
        result = analyze_certificate_rebuild(RomImage.from_path(ROM))
        trials = result.app_trials

        self.assertEqual((0x1E50, 0x1F18), trials.model_offsets)
        self.assertEqual(0x00C8, trials.length)
        self.assertEqual(2, trials.entry_length)
        self.assertEqual(0xFF, trials.erased_byte)
        self.assertEqual(RomLocation(0x3D, 0x5759), trials.clear_routine)
        self.assertEqual(RomLocation(0x3D, 0x5BB7), trials.write_routine)
        self.assertEqual(RomLocation(0x3D, 0x5466), trials.query_routine)
        self.assertEqual("Trials Remaining:", trials.display_label)
        self.assertEqual(RomLocation(0x01, 0x41AA), trials.display_label_location)
        self.assertEqual(1, trials.clear_rebuild_mode)


if __name__ == "__main__":
    unittest.main()
