#!/usr/bin/env python3
"""Regression tests for the reusable two-wire link-port model."""

from pathlib import Path
import unittest

from link_port import (
    KEYBOARD_STATUS_RETURNS,
    LINK_PORT_PROFILES,
    KeyboardFrame,
    KeyboardGetKeyObservation,
    KeyboardRomSignatureError,
    analyze_keyboard_rom,
    assemble_observed_byte,
    abort_pulse_delay_tstates,
    abort_pulse_instruction_count,
    abort_pulse_report,
    byte_drive_sequence,
    classify_keyboard_getkey,
    decode_ti_keyboard_frame,
    drive_mask,
    emulator_port_write,
    emulator_write_sequence,
    handshake_phases,
    link_port_profile,
    mame_plus_connector_drive,
    mame_plus_port_read,
    mame_plus_state_after_write,
    observed_sequence,
    observed_state_to_bit,
    physical_high_mask,
    port_read_value,
    receiver_ack_drive,
    sender_drive,
)
from rom_image import RomImage


ROM = Path(__file__).resolve().parent / "rom.bin"


class LinkPortTests(unittest.TestCase):
    def test_keyboard_rom_guard_verifies_bcall_and_control_flow_regions(self):
        analysis = analyze_keyboard_rom(RomImage.from_path(ROM))

        self.assertEqual("3C:6D5E", analysis.target)
        self.assertEqual("5e6d7c", analysis.bcall_table_bytes)
        self.assertEqual(3, len(analysis.regions))

    def test_keyboard_rom_guard_rejects_a_changed_status_body(self):
        rom = RomImage.from_path(ROM)
        data = bytearray(rom.data)
        data[rom.flat_offset(0x3C, 0x444A)] ^= 1

        with self.assertRaisesRegex(
            KeyboardRomSignatureError,
            "lnk_rec_status signature mismatch",
        ):
            analyze_keyboard_rom(RomImage(bytes(data)))

    def test_logical_keyboard_decoder_consumes_but_does_not_return_data(self):
        result = decode_ti_keyboard_frame(KeyboardFrame(data=0x42))

        self.assertEqual(0x01, result.status)
        self.assertEqual(0x42, result.data)
        self.assertTrue(result.data_consumed)
        self.assertFalse(result.data_returned)

    def test_logical_keyboard_decoder_rejects_each_frame_component(self):
        cases = (
            (None, 0x00),
            (KeyboardFrame(prefix=0xE1), 0x02),
            (KeyboardFrame(delimiter="ordinary"), 0x02),
            (KeyboardFrame(delimiter="timeout"), 0x02),
            (KeyboardFrame(command=0x02), 0xFC),
        )
        for frame, status in cases:
            with self.subTest(frame=frame):
                self.assertEqual(status, decode_ti_keyboard_frame(frame).status)

    def test_keyboard_control_flow_reaches_every_explicit_status_tail(self):
        cases = {
            0x00: KeyboardGetKeyObservation(assist_status=0),
            0x01: KeyboardGetKeyObservation(),
            0x02: KeyboardGetKeyObservation(frame=KeyboardFrame(prefix=0x42)),
            0xF9: KeyboardGetKeyObservation(assist_status=0x40),
            0xFA: KeyboardGetKeyObservation(
                assist_status=0x50,
                buffered_byte=0x42,
            ),
            0xFB: KeyboardGetKeyObservation(
                assist_status=0x50,
                buffered_byte=0xE0,
            ),
            0xFC: KeyboardGetKeyObservation(frame=KeyboardFrame(command=0x02)),
            0xFD: KeyboardGetKeyObservation(
                initial_high_lines=2,
                assist_available=False,
                receive_status=1,
            ),
            0xFE: KeyboardGetKeyObservation(
                receive_status=1,
                frame=KeyboardFrame(prefix=0x42),
            ),
            0xFF: KeyboardGetKeyObservation(error_handler_invoked=True),
        }

        self.assertEqual(set(KEYBOARD_STATUS_RETURNS), set(cases))
        for expected, observation in cases.items():
            with self.subTest(status=expected):
                result = classify_keyboard_getkey(observation)
                self.assertEqual(expected, result.status)
                self.assertEqual(
                    KEYBOARD_STATUS_RETURNS[expected].address,
                    result.return_address,
                )

    def test_buffered_assist_prefix_skips_delimiter_test(self):
        result = classify_keyboard_getkey(
            KeyboardGetKeyObservation(
                receive_status=1,
                frame=KeyboardFrame(delimiter="ordinary", data=0x7F),
            )
        )

        self.assertEqual(0x01, result.status)
        self.assertTrue(result.data_consumed)

    def test_entry_assist_error_data_requires_a_buffered_byte(self):
        with self.assertRaises(ValueError):
            classify_keyboard_getkey(
                KeyboardGetKeyObservation(assist_status=0x50)
            )

    def test_abort_pulse_loop_has_exact_rom_tstate_count(self):
        self.assertEqual(7_077_785, abort_pulse_delay_tstates())
        self.assertEqual(1_114_096, abort_pulse_instruction_count())

        report = abort_pulse_report()
        self.assertEqual(6_000_000, report["cpu_hz"])
        self.assertEqual(8_191_881, report["delay_tstates"])
        self.assertAlmostEqual(1.3653135, report["nominal_seconds"])

    def test_abort_pulse_counter_handles_small_loop(self):
        # LD HL (10), one outer body (7 + 4 + 11 + 6 + 4 + 4), final JR (7).
        self.assertEqual(
            53,
            abort_pulse_delay_tstates(
                outer_iterations=1,
                inner_iterations=1,
                padding_nops=1,
            ),
        )

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

    def test_profile_catalog_has_reference_and_three_emulators(self):
        self.assertEqual(
            {"documented", "tilem", "wabbitemu", "mame"},
            set(LINK_PORT_PROFILES),
        )
        self.assertEqual("mame0287", link_port_profile("MAME").revision)

    def test_standard_profiles_drive_the_low_write_bits(self):
        for profile in ("documented", "tilem", "wabbitemu"):
            for value in range(256):
                with self.subTest(profile=profile, value=value):
                    result = emulator_port_write(profile, value)
                    self.assertEqual(value & 3, result.local_latch)
                    self.assertEqual(value & 3, result.connector_drive)
                    self.assertEqual(
                        port_read_value(value & 3, 0), result.port_read
                    )

    def test_mame_normal_raw_writes_change_readback_but_not_connector(self):
        zero = emulator_port_write("mame", 1)
        one = emulator_port_write("mame", 2)

        self.assertEqual((0x10, 1, 0, 0x12), (
            zero.state_after,
            zero.local_latch,
            zero.connector_drive,
            zero.port_read,
        ))
        self.assertEqual((0x20, 2, 0, 0x21), (
            one.state_after,
            one.local_latch,
            one.connector_drive,
            one.port_read,
        ))

    def test_mame_connector_uses_bit_pairs_two_four_and_three_five(self):
        self.assertEqual(1, mame_plus_connector_drive(0x14))
        self.assertEqual(2, mame_plus_connector_drive(0x28))
        self.assertEqual(3, mame_plus_connector_drive(0x3C))

    def test_mame_peer_lines_still_affect_low_read_bits(self):
        state = mame_plus_state_after_write(0)

        self.assertEqual(3, mame_plus_port_read(state, 0))
        self.assertEqual(2, mame_plus_port_read(state, 1))
        self.assertEqual(1, mame_plus_port_read(state, 2))
        self.assertEqual(0, mame_plus_port_read(state, 3))

    def test_write_sequence_preserves_mame_pcr_state(self):
        results = emulator_write_sequence("mame", (1, 2, 0))

        self.assertEqual((0, 0x10, 0x20), tuple(row.state_before for row in results))
        self.assertEqual((0x10, 0x20, 0), tuple(row.state_after for row in results))

    def test_mame_advertises_assist_without_implementing_assist_ports(self):
        profile = link_port_profile("mame")

        self.assertTrue(profile.advertises_assist)
        self.assertFalse(profile.assist_operational)
        self.assertEqual((0x09,), profile.mapped_assist_ports)


if __name__ == "__main__":
    unittest.main()
