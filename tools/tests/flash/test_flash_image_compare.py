#!/usr/bin/env python3
"""Regression tests for byte-complete Flash image comparison."""

import unittest


from ti84re.flash.image_compare import DifferenceRange, compare_flash_images


class FlashImageCompareTests(unittest.TestCase):
    def test_equal_images_have_no_difference_ranges(self):
        comparison = compare_flash_images(b"abc", b"abc")

        self.assertTrue(comparison.equal)
        self.assertEqual(0, comparison.differing_bytes)
        self.assertEqual((), comparison.ranges)
        self.assertEqual(comparison.left_sha256, comparison.right_sha256)

    def test_groups_ranges_and_counts_physical_pages(self):
        left = bytes(0x4002)
        right = bytearray(left)
        right[1:3] = b"\x01\x02"
        right[0x4001] = 3

        comparison = compare_flash_images(left, bytes(right))

        self.assertEqual(3, comparison.differing_bytes)
        self.assertEqual(
            (DifferenceRange(1, 3), DifferenceRange(0x4001, 0x4002)),
            comparison.ranges,
        )
        self.assertEqual(((0, 2), (1, 1)), comparison.page_counts)

    def test_rejects_size_mismatch(self):
        with self.assertRaisesRegex(ValueError, "sizes differ"):
            compare_flash_images(b"a", b"ab")


if __name__ == "__main__":
    unittest.main()
