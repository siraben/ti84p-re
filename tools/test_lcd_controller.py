#!/usr/bin/env python3
"""Regression tests for LCD command and emulator pointer models."""

import unittest

from lcd_controller import (
    LCD_EMULATOR_PROFILES,
    decode_lcd_command,
    lcd_emulator_profile,
    lcd_status,
    read_latch_sequence,
    walk_lcd_transfers,
)


class LcdControllerTests(unittest.TestCase):
    def test_decodes_os_initialization_commands(self):
        commands = [
            decode_lcd_command(value)
            for value in (0x40, 0x05, 0x01, 0x03, 0x17, 0x0B, 0xEF)
        ]
        self.assertEqual(
            [
                ("row_shift", 0),
                ("movement", 5),
                ("word_length", 8),
                ("display", 1),
                ("power_level", 7),
                ("power_enhancement", 3),
                ("contrast", 47),
            ],
            [(command.kind, command.argument) for command in commands],
        )

    def test_status_byte(self):
        self.assertEqual(
            0x63,
            lcd_status(word_length=8, display_on=True, movement=7),
        )
        self.assertEqual(
            0xE3,
            lcd_status(word_length=8, display_on=True, movement=7, busy=True),
        )

    def test_profiles_have_unique_names(self):
        self.assertEqual(3, len({profile.name for profile in LCD_EMULATOR_PROFILES}))
        self.assertEqual(15, lcd_emulator_profile("mame").row_stride)

    def test_visible_twelve_byte_row_is_safe_in_all_models(self):
        for profile in LCD_EMULATOR_PROFILES:
            with self.subTest(emulator=profile.name):
                accesses = walk_lcd_transfers(
                    profile.name,
                    row=0,
                    column=0,
                    movement=7,
                    count=12,
                )
                self.assertTrue(all(a.logical_column_in_range for a in accesses))
                self.assertTrue(all(a.array_index_in_range for a in accesses))

    def test_column_increment_diverges_at_hidden_edge(self):
        tilem = walk_lcd_transfers(
            "TilEm", row=0, column=14, movement=7, count=4
        )
        wabbitemu = walk_lcd_transfers(
            "Wabbitemu", row=0, column=14, movement=7, count=4
        )
        mame = walk_lcd_transfers(
            "MAME", row=0, column=14, movement=7, count=4
        )
        self.assertEqual([14, 15, 0, 1], [a.accessed_column for a in tilem])
        self.assertEqual([14, 0, 1, 2], [a.accessed_column for a in wabbitemu])
        self.assertEqual([14, 15, 16, 17], [a.accessed_column for a in mame])
        self.assertEqual([True, False, False, False],
                         [a.logical_column_in_range for a in mame])

    def test_direct_out_of_range_column_mapping(self):
        tilem = walk_lcd_transfers(
            "TilEm", row=1, column=31, movement=5, count=1
        )[0]
        wabbitemu = walk_lcd_transfers(
            "Wabbitemu", row=1, column=31, movement=5, count=1
        )[0]
        mame = walk_lcd_transfers(
            "MAME", row=1, column=31, movement=5, count=1
        )[0]
        self.assertEqual((1, 0, 16),
                         (tilem.accessed_row, tilem.accessed_column,
                          tilem.array_index))
        self.assertEqual((1, 31, 31),
                         (wabbitemu.accessed_row, wabbitemu.accessed_column,
                          wabbitemu.array_index))
        self.assertEqual((1, 31, 46),
                         (mame.accessed_row, mame.accessed_column,
                          mame.array_index))
        self.assertFalse(mame.logical_column_in_range)
        self.assertTrue(mame.array_index_in_range)

    def test_six_bit_first_byte_addresses_follow_each_source(self):
        tilem = walk_lcd_transfers(
            "TilEm", row=0, column=21, movement=5, count=1, word_length=6
        )[0]
        wabbitemu = walk_lcd_transfers(
            "Wabbitemu", row=0, column=31, movement=5, count=1, word_length=6
        )[0]
        mame = walk_lcd_transfers(
            "MAME", row=63, column=31, movement=7, count=1, word_length=6
        )[0]
        self.assertEqual(15, tilem.array_index)
        self.assertTrue(tilem.logical_column_in_range)
        self.assertEqual(7, wabbitemu.array_index)
        self.assertFalse(wabbitemu.logical_column_in_range)
        self.assertEqual(968, mame.array_index)
        self.assertFalse(mame.array_index_in_range)

    def test_mame_can_index_past_its_array(self):
        access = walk_lcd_transfers(
            "MAME", row=63, column=31, movement=7, count=1
        )[0]
        self.assertEqual(976, access.array_index)
        self.assertFalse(access.array_index_in_range)

    def test_dummy_read_latch(self):
        self.assertEqual(
            (0xAA, 0x12, 0x34),
            read_latch_sequence((0x12, 0x34, 0x56), initial_latch=0xAA),
        )

    def test_rejects_invalid_transfer_parameters(self):
        with self.assertRaises(ValueError):
            walk_lcd_transfers("TilEm", row=64, column=0, movement=7, count=1)
        with self.assertRaises(ValueError):
            walk_lcd_transfers("TilEm", row=0, column=32, movement=7, count=1)
        with self.assertRaises(ValueError):
            walk_lcd_transfers("TilEm", row=0, column=0, movement=3, count=1)


if __name__ == "__main__":
    unittest.main()
