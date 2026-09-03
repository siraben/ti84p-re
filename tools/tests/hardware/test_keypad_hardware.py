#!/usr/bin/env python3
"""Regression tests for pinned emulator keypad and ON-key models."""

import unittest


from ti84re.hardware.keypad import (
    KEYPAD_EMULATOR_PROFILES,
    app_mouse_force_key,
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

    def test_app_mouse_cardinal_and_diagonal_movement(self):
        expected = {
            0x01: (0x20, 0x30),
            0x02: (0x1F, 0x2F),
            0x03: (0x1F, 0x31),
            0x04: (0x1E, 0x30),
            0xF3: (0x1E, 0x31),
            0xF5: (0x1E, 0x2F),
            0xFA: (0x20, 0x31),
            0xFC: (0x20, 0x2F),
        }
        for scan_code, coordinates in expected.items():
            with self.subTest(scan_code=scan_code):
                result = app_mouse_force_key(0x1F, 0x30, scan_code)
                self.assertEqual(coordinates, (result.row, result.column))
                self.assertEqual(scan_code >= 0xF3, result.diagonal)
                self.assertEqual(0x0A, result.return_code)
                self.assertTrue(result.coordinates_returned_in_hl)

    def test_app_mouse_diagonal_moves_unblocked_axis_at_edge(self):
        result = app_mouse_force_key(0, 10, 0xF5)

        self.assertEqual((0, 9), (result.row, result.column))
        self.assertEqual((0, -1), (result.delta_row, result.delta_column))
        self.assertEqual("move", result.outcome)

    def test_app_mouse_waits_when_all_requested_axes_are_blocked(self):
        cardinal = app_mouse_force_key(0, 10, 0x04)
        diagonal = app_mouse_force_key(0, 0, 0xF5)
        unsupported = app_mouse_force_key(10, 10, 0x36)

        for result in (cardinal, diagonal, unsupported):
            self.assertEqual("wait", result.outcome)
            self.assertIsNone(result.return_code)

    def test_app_mouse_enter_and_second_return_codes(self):
        enter = app_mouse_force_key(10, 20, 0x09, second_modifier=True)
        movement = app_mouse_force_key(10, 20, 0x01, second_modifier=True)

        self.assertEqual(("enter", 0x0C), (enter.outcome, enter.return_code))
        self.assertEqual(0x08, movement.return_code)
        self.assertFalse(movement.coordinates_returned_in_hl)

    def test_app_mouse_rejects_coordinates_outside_lcd(self):
        with self.assertRaises(ValueError):
            app_mouse_force_key(0x40, 0, 0x01)
        with self.assertRaises(ValueError):
            app_mouse_force_key(0, 0x60, 0x01)


if __name__ == "__main__":
    unittest.main()
