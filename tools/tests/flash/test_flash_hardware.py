#!/usr/bin/env python3
"""Regression tests for Flash geometry and emulator behavior models."""

import unittest

from ti84re.flash.hardware import (
    EMULATOR_PROFILES,
    FLASH_COMMAND_PROFILES,
    FUJITSU_MBM29LV800TA,
    REPORTED_COMPATIBLE_PARTS,
    TOP_BOOT_SECTORS,
    emulator_profile,
    flash_command_profile,
    flash_sector,
    mame_erase_busy_read_range,
    mame_erase_duration_ms,
    mame_erase_status_reads,
    program_byte,
    rom_program_poll_decision,
    simulate_wabbitemu_rom_program_poll,
    summarize_wabbitemu_rom_program_polls,
    wabbitemu_program_error_read,
)


class FlashHardwareTests(unittest.TestCase):
    def test_photographed_part_keeps_fujitsu_and_emulator_ids_distinct(self):
        part = FUJITSU_MBM29LV800TA

        self.assertEqual("MBM29LV800TA-70PFTN", part.orderable_part)
        self.assertEqual((0xAAA, 0x555), part.byte_mode_unlock_addresses)
        self.assertEqual(
            (0x04, 0xDA),
            (part.manufacturer_code, part.device_code_byte_mode),
        )
        self.assertEqual(
            (8, 300),
            (part.byte_program_typ_us, part.byte_program_max_us),
        )
        self.assertEqual(
            (1000, 10000),
            (part.sector_erase_typ_ms, part.sector_erase_max_ms),
        )
        self.assertEqual(
            {0x01},
            {
                profile.autoselect_manufacturer_code
                for profile in EMULATOR_PROFILES
                if profile.autoselect_manufacturer_code is not None
            },
        )

    def test_reported_compatible_parts_do_not_replace_observed_identity(self):
        self.assertEqual(
            ["AMIC", "Fujitsu", "Spansion", "Macronix"],
            [part.manufacturer for part in REPORTED_COMPATIBLE_PARTS],
        )
        self.assertIn(
            ("Spansion", "S29AL008D"),
            [(part.manufacturer, part.family) for part in REPORTED_COMPATIBLE_PARTS],
        )

    def test_sector_table_covers_device_without_gaps(self):
        self.assertEqual(0, TOP_BOOT_SECTORS[0].start)
        self.assertEqual(0x100000, TOP_BOOT_SECTORS[-1].end)
        self.assertTrue(all(
            left.end == right.start
            for left, right in zip(TOP_BOOT_SECTORS, TOP_BOOT_SECTORS[1:])
        ))

    def test_top_boot_sector_boundaries(self):
        expected = {
            0xEFFFF: (0xE0000, 0x10000),
            0xF0000: (0xF0000, 0x8000),
            0xF7FFF: (0xF0000, 0x8000),
            0xF8000: (0xF8000, 0x2000),
            0xF9FFF: (0xF8000, 0x2000),
            0xFA000: (0xFA000, 0x2000),
            0xFBFFF: (0xFA000, 0x2000),
            0xFC000: (0xFC000, 0x4000),
            0xFFFFF: (0xFC000, 0x4000),
        }
        for address, sector in expected.items():
            with self.subTest(address=address):
                result = flash_sector(address)
                self.assertEqual(sector, (result.start, result.size))

    def test_rejects_address_outside_device(self):
        for address in (-1, 0x100000):
            with self.subTest(address=address):
                with self.assertRaises(ValueError):
                    flash_sector(address)

    def test_profiles_have_unique_names(self):
        self.assertEqual(3, len({profile.name for profile in EMULATOR_PROFILES}))
        self.assertEqual("MAME", emulator_profile("mame").name)

    def test_tilem_profile_uses_real_time_timer_units(self):
        tilem = emulator_profile("tilem")

        self.assertIn("7 us", tilem.program_completion)
        self.assertIn("42 clocks", tilem.program_completion)
        self.assertIn("200 ms", tilem.erase_completion)
        self.assertIn("1200000 clocks", tilem.erase_completion)

    def test_command_profiles_keep_physical_and_emulator_support_distinct(self):
        self.assertEqual(4, len(FLASH_COMMAND_PROFILES))
        fujitsu = flash_command_profile("fujitsu mbm29lv800ta")
        tilem = flash_command_profile("tilem")

        self.assertEqual("data sheet", fujitsu.source_kind)
        self.assertEqual("defined", fujitsu.erase_suspend_resume.status)
        self.assertEqual("not defined", fujitsu.cfi.status)
        self.assertEqual("partial", tilem.fast_program.status)
        self.assertEqual("not implemented", tilem.erase_suspend_resume.status)
        self.assertEqual("partial", flash_command_profile("MAME").fast_program.status)

    def test_emulator_command_profiles_expose_chip_erase_qualification(self):
        for name in ("TilEm", "Wabbitemu", "MAME"):
            with self.subTest(name=name):
                self.assertEqual("partial", flash_command_profile(name).chip_erase.status)

    def test_and_models_preserve_zero_bits(self):
        for emulator in ("TilEm", "Wabbitemu"):
            with self.subTest(emulator=emulator):
                result = program_byte(emulator, 0x00, 0xFF)
                self.assertEqual(0x00, result.stored)
                self.assertTrue(result.requested_zero_to_one)

    def test_mame_assignment_permits_zero_to_one(self):
        result = program_byte("MAME", 0x00, 0xFF)
        self.assertEqual(0xFF, result.stored)
        self.assertTrue(result.requested_zero_to_one)
        self.assertEqual("array data", result.poll_behavior)

    def test_wabbitemu_error_status(self):
        self.assertEqual(0xA0, wabbitemu_program_error_read(0x00))
        self.assertEqual(0xE0, wabbitemu_program_error_read(0x00, dq6=True))
        self.assertEqual(0x20, wabbitemu_program_error_read(0x80))

    def test_wabbitemu_rom_poll_legal_program_succeeds_on_first_read(self):
        result = simulate_wabbitemu_rom_program_poll(0xFF, 0xD0)

        self.assertFalse(result.requested_zero_to_one)
        self.assertEqual(0xD0, result.stored)
        self.assertEqual("success", result.outcome)
        self.assertEqual(
            [(0xD0, "success")], [(read.value, read.decision) for read in result.reads]
        )

    def test_wabbitemu_rom_poll_accepts_illegal_lower_bit_request(self):
        for old, requested in ((0x00, 0x01), (0x20, 0x21)):
            with self.subTest(old=old, requested=requested):
                result = simulate_wabbitemu_rom_program_poll(old, requested)
                self.assertTrue(result.requested_zero_to_one)
                self.assertEqual(old & requested, result.stored)
                self.assertEqual("success", result.outcome)

    def test_wabbitemu_rom_poll_fails_illegal_dq7_request(self):
        result = simulate_wabbitemu_rom_program_poll(0x20, 0xA0)

        self.assertEqual(0x20, result.stored)
        self.assertEqual("failure", result.outcome)
        self.assertEqual([0x20, 0x20], [read.value for read in result.reads])

    def test_wabbitemu_rom_poll_fails_when_stored_dq5_is_clear(self):
        result = simulate_wabbitemu_rom_program_poll(0x50, 0xD0)

        self.assertEqual(0x50, result.stored)
        self.assertEqual("failure", result.outcome)
        self.assertEqual([0x20, 0x50], [read.value for read in result.reads])

    def test_wabbitemu_rom_poll_dq6_toggle_does_not_change_decision(self):
        result = simulate_wabbitemu_rom_program_poll(
            0x50,
            0xD0,
            initial_error_dq6=True,
        )

        self.assertTrue(result.initial_error_dq6)
        self.assertEqual(0x60, result.reads[0].value)
        self.assertEqual("failure", result.outcome)

    def test_wabbitemu_rom_poll_exhaustive_outcomes(self):
        summary = summarize_wabbitemu_rom_program_polls()

        self.assertEqual(0x10000, summary.total_pairs)
        self.assertEqual(49152, summary.successes)
        self.assertEqual(16384, summary.failures)
        self.assertEqual(6561, summary.legal_successes)
        self.assertEqual(42591, summary.illegal_reported_successes)

    def test_mame_erase_durations_follow_sector_size(self):
        self.assertEqual(1000, mame_erase_duration_ms(0xE0000))
        self.assertEqual(500, mame_erase_duration_ms(0xF0000))
        self.assertEqual(250, mame_erase_duration_ms(0xF8000))
        self.assertEqual(250, mame_erase_duration_ms(0xFA000))
        self.assertEqual(500, mame_erase_duration_ms(0xFC000))

    def test_mame_erase_status_toggles_dq6_and_dq2(self):
        self.assertEqual((0x4C, 0x08, 0x4C, 0x08), mame_erase_status_reads(4))

    def test_mame_uses_64k_busy_read_window_for_small_sector(self):
        self.assertEqual((0xF8000, 0x100000), mame_erase_busy_read_range(0xF9000))
        self.assertEqual((0xFC000, 0x100000), mame_erase_busy_read_range(0xFFFFF))

    def test_rom_poll_decisions(self):
        self.assertEqual("success", rom_program_poll_decision(0x80, 0x80))
        self.assertEqual("retry", rom_program_poll_decision(0x80, 0x00))
        self.assertEqual(
            "need-final-read",
            rom_program_poll_decision(0x80, 0x20),
        )
        self.assertEqual(
            "failure",
            rom_program_poll_decision(
                0x80, 0x20, final_read=0x00
            ),
        )
        self.assertEqual(
            "success",
            rom_program_poll_decision(
                0x80, 0x20, final_read=0x80
            ),
        )


if __name__ == "__main__":
    unittest.main()
