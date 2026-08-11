#!/usr/bin/env python3
"""Regression tests for the reusable two-wire link-port model."""

import unittest

from link_port import (
    assemble_observed_byte,
    byte_drive_sequence,
    drive_mask,
    handshake_phases,
    observed_sequence,
    observed_state_to_bit,
    physical_high_mask,
    port_read_value,
    receiver_ack_drive,
    sender_drive,
)


class LinkPortTests(unittest.TestCase):
    def test_write_uses_only_low_two_bits(self):
        self.assertEqual(2, drive_mask(0xA6))

    def test_wired_and_truth_table(self):
        for local in range(4):
            for peer in range(4):
                with self.subTest(local=local, peer=peer):
                    self.assertEqual((~(local | peer)) & 3, physical_high_mask(local, peer))

    def test_port_read_includes_local_latch(self):
        self.assertEqual(0x21, port_read_value(local_drive=2, peer_drive=0))
        self.assertEqual(0x20, port_read_value(local_drive=2, peer_drive=1))

    def test_bit_encoding_and_receive_decode_are_inverses(self):
        self.assertEqual(1, sender_drive(0))
        self.assertEqual(2, sender_drive(1))
        self.assertEqual(0, observed_state_to_bit(2))
        self.assertEqual(1, observed_state_to_bit(1))
        self.assertEqual(2, receiver_ack_drive(2))
        self.assertEqual(1, receiver_ack_drive(1))

    def test_invalid_receive_states_are_rejected(self):
        for state in (0, 3):
            with self.subTest(state=state):
                with self.assertRaises(ValueError):
                    observed_state_to_bit(state)

    def test_byte_sequence_is_lsb_first(self):
        self.assertEqual((2, 1, 2, 1, 1, 2, 1, 2), byte_drive_sequence(0xA5))
        self.assertEqual((1, 2, 1, 2, 2, 1, 2, 1), observed_sequence(0xA5))

    def test_every_byte_round_trips_through_observed_states(self):
        for value in range(256):
            with self.subTest(value=value):
                self.assertEqual(value, assemble_observed_byte(observed_sequence(value)))

    def test_four_phase_bit_zero_handshake(self):
        phases = handshake_phases(0)
        self.assertEqual(
            (
                ("sender-assert", 1, 0, 2),
                ("receiver-acknowledge", 1, 2, 0),
                ("sender-release", 0, 2, 1),
                ("receiver-release", 0, 0, 3),
            ),
            tuple(
                (phase.name, phase.sender_drive, phase.receiver_drive, phase.high_lines)
                for phase in phases
            ),
        )

    def test_four_phase_bit_one_handshake(self):
        phases = handshake_phases(1)
        self.assertEqual((1, 0, 2, 3), tuple(phase.high_lines for phase in phases))

    def test_exactly_eight_states_are_required(self):
        with self.assertRaises(ValueError):
            assemble_observed_byte((1, 2))


if __name__ == "__main__":
    unittest.main()
