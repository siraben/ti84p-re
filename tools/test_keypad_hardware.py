#!/usr/bin/env python3
"""Regression tests for pinned emulator keypad and ON-key models."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from keypad_hardware import (
    KEYPAD_EMULATOR_PROFILES,
    on_transition_requests_interrupt,
    read_keypad_matrix,
)


class KeypadHardwareTests(unittest.TestCase):
    def test_single_selected_key_agrees(self):
        for profile in KEYPAD_EMULATOR_PROFILES:
            with self.subTest(emulator=profile.name):
                read = read_keypad_matrix(profile.name, 0xFE, [(0, 0)])
                self.assertEqual(0xFE, read.active_low_value)

    def test_three_key_rectangle_ghosts_only_in_closure_models(self):
        keys = [(0, 0), (1, 0), (1, 1)]
        self.assertEqual(0xFC, read_keypad_matrix("TilEm", 0xFE, keys).active_low_value)
        self.assertEqual(
            0xFC, read_keypad_matrix("Wabbitemu", 0xFE, keys).active_low_value
        )
        self.assertEqual(0xFE, read_keypad_matrix("MAME", 0xFE, keys).active_low_value)

    def test_only_tilem_closure_is_transitive(self):
        keys = [(0, 0), (1, 0), (1, 1), (2, 1), (2, 2)]
        self.assertEqual(0xF8, read_keypad_matrix("TilEm", 0xFE, keys).active_low_value)
        self.assertEqual(
            0xFC, read_keypad_matrix("Wabbitemu", 0xFE, keys).active_low_value
        )
        self.assertEqual(0xFE, read_keypad_matrix("MAME", 0xFE, keys).active_low_value)

    def test_mame_xor_cancels_same_column_in_two_selected_rows(self):
        keys = [(0, 0), (1, 0)]
        self.assertEqual(0xFE, read_keypad_matrix("TilEm", 0xFC, keys).active_low_value)
        self.assertEqual(
            0xFE, read_keypad_matrix("Wabbitemu", 0xFC, keys).active_low_value
        )
        self.assertEqual(0xFF, read_keypad_matrix("MAME", 0xFC, keys).active_low_value)

    def test_release_mask_reads_high(self):
        keys = [(group, group) for group in range(7)]
        for profile in KEYPAD_EMULATOR_PROFILES:
            with self.subTest(emulator=profile.name):
                self.assertEqual(
                    0xFF,
                    read_keypad_matrix(profile.name, 0xFF, keys).active_low_value,
                )

    def test_on_edge_policy(self):
        for profile in KEYPAD_EMULATOR_PROFILES:
            self.assertTrue(on_transition_requests_interrupt(profile.name, "press"))
        self.assertTrue(on_transition_requests_interrupt("TilEm", "release"))
        self.assertFalse(on_transition_requests_interrupt("Wabbitemu", "release"))
        self.assertFalse(on_transition_requests_interrupt("MAME", "release"))
        self.assertFalse(
            on_transition_requests_interrupt("TilEm", "press", enabled=False)
        )

    def test_rejects_invalid_positions_and_transition(self):
        with self.assertRaises(ValueError):
            read_keypad_matrix("TilEm", 0xFE, [(8, 0)])
        with self.assertRaises(ValueError):
            read_keypad_matrix("TilEm", 0x100, [])
        with self.assertRaises(ValueError):
            on_transition_requests_interrupt("TilEm", "hold")


if __name__ == "__main__":
    unittest.main()
