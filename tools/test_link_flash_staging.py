#!/usr/bin/env python3
"""Regression tests for the link-to-Flash staging analysis and model."""

from pathlib import Path
import unittest

from link_flash_staging import (
    LinkFlashStagingSignatureError,
    analyze_link_flash_staging,
    classify_page,
    flush_paged_flash_block,
    receive_data_staging,
)
from rom_image import RomImage


ROM = Path(__file__).resolve().parent / "rom.bin"


class LinkFlashStagingTests(unittest.TestCase):
    def test_pinned_rom_verifies_abi_and_complete_caller_sets(self):
        analysis = analyze_link_flash_staging(RomImage.from_path(ROM))

        self.assertEqual("_WriteFlash", analysis.abi.bcall_name)
        self.assertEqual(0x80C9, analysis.abi.bcall_id)
        self.assertEqual(
            ("3C:42CF", "3C:42EC", "3C:6F57"),
            tuple(str(item.location) for item in analysis.direct_references),
        )
        self.assertEqual(
            (0x03, 0x0D, 0x15, 0x00, 0x01, 0x14),
            tuple(item.mode for item in analysis.dispatcher_callers),
        )
        self.assertEqual("36:415C", str(analysis.dispatcher_callers[0].location))
        self.assertEqual("36:40E7", str(analysis.usb_receive_owner.entry))
        self.assertEqual("00:2E17", str(analysis.usb_receive_owner.endpoint_stub))
        self.assertEqual("35:4FA1", str(analysis.usb_receive_owner.endpoint_helper))
        self.assertEqual(0xA1, analysis.usb_receive_owner.endpoint_data_port)

    def test_rom_guard_rejects_changed_receive_branch(self):
        rom = RomImage.from_path(ROM)
        data = bytearray(rom.data)
        data[rom.flat_offset(0x3C, 0x42B8)] ^= 1

        with self.assertRaisesRegex(
            LinkFlashStagingSignatureError,
            "receive_data_route_and_flush signature mismatch",
        ):
            analyze_link_flash_staging(RomImage(bytes(data)))

    def test_rom_guard_rejects_changed_usb_endpoint_read(self):
        rom = RomImage.from_path(ROM)
        data = bytearray(rom.data)
        data[rom.flat_offset(0x35, 0x500E)] ^= 1

        with self.assertRaisesRegex(
            LinkFlashStagingSignatureError,
            "usb_endpoint_a1_read_loop signature mismatch",
        ):
            analyze_link_flash_staging(RomImage(bytes(data)))

    def test_ti84_page_range_masks_and_checks_both_bounds(self):
        self.assertFalse(classify_page(0x07).eligible)
        self.assertTrue(classify_page(0x08).eligible)
        self.assertTrue(classify_page(0x29).eligible)
        self.assertFalse(classify_page(0x2A).eligible)
        masked = classify_page(0xC8)
        self.assertEqual(0x08, masked.normalized_page)
        self.assertTrue(masked.eligible)

    def test_legacy_and_expanded_ranges_have_distinct_upper_limits(self):
        self.assertTrue(classify_page(0x15, "legacy").eligible)
        self.assertFalse(classify_page(0x16, "legacy").eligible)
        self.assertTrue(classify_page(0x69, "expanded").eligible)
        self.assertFalse(classify_page(0x6A, "expanded").eligible)

    def test_ram_destination_is_written_directly_without_flushes(self):
        result = receive_data_staging(0x9000, 17, page=0x08)

        self.assertEqual("ram-direct", result.storage)
        self.assertEqual(17, result.direct_ram_bytes)
        self.assertEqual((), result.flushes)
        self.assertEqual(0x9011, result.output_destination)
        self.assertEqual(0x08, result.output_page)

    def test_flash_destination_uses_sixteen_byte_blocks_and_remainder(self):
        result = receive_data_staging(0x5000, 33, page=0x08)

        self.assertEqual("flash-buffered", result.storage)
        self.assertEqual((16, 16, 1), tuple(item.count for item in result.flushes))
        self.assertEqual(0x5021, result.output_destination)
        self.assertEqual(0x08, result.output_page)
        self.assertTrue(all(item.write_attempted for item in result.flushes))

    def test_zero_length_receive_skips_the_flush_quirk(self):
        result = receive_data_staging(0x5000, 0, page=0x08)

        self.assertEqual((), result.flushes)
        self.assertEqual(0x5000, result.output_destination)
        self.assertEqual(0x08, result.output_page)

    def test_zero_count_dispatch_increments_page_without_write_attempt(self):
        result = flush_paged_flash_block(0x08, 0x5000, 0)

        self.assertTrue(result.write_bcall_invoked)
        self.assertFalse(result.write_attempted)
        self.assertEqual(0x5000, result.output_destination)
        self.assertEqual(0x09, result.output_page)
        self.assertEqual("zero-count", result.reason)

    def test_invalid_page_skips_bcall_but_still_increments_stored_page(self):
        result = flush_paged_flash_block(0x07, 0x5000, 16)

        self.assertFalse(result.write_bcall_invoked)
        self.assertFalse(result.write_attempted)
        self.assertEqual(0x5000, result.output_destination)
        self.assertEqual(0x08, result.output_page)
        self.assertEqual("page-outside-program-range", result.reason)

    def test_crossing_updates_destination_and_stored_page(self):
        result = flush_paged_flash_block(0x08, 0x7FFF, 2)

        self.assertEqual(0x4001, result.output_destination)
        self.assertEqual(0x09, result.output_page)
        self.assertTrue(result.page_incremented)

    def test_exact_boundary_defers_page_increment_until_next_flush(self):
        result = receive_data_staging(0x7FF0, 17, page=0x08)

        self.assertEqual((16, 1), tuple(item.count for item in result.flushes))
        self.assertEqual(0x8000, result.flushes[0].output_destination)
        self.assertFalse(result.flushes[0].page_incremented)
        self.assertEqual(0x4001, result.output_destination)
        self.assertEqual(0x09, result.output_page)

    def test_rejects_values_wider_than_the_rom_state(self):
        with self.assertRaises(ValueError):
            flush_paged_flash_block(0x100, 0x5000, 1)
        with self.assertRaises(ValueError):
            flush_paged_flash_block(0x08, 0x10000, 1)
        with self.assertRaises(ValueError):
            receive_data_staging(0x5000, 0x10000)


if __name__ == "__main__":
    unittest.main()
