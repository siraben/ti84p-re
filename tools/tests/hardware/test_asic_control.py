#!/usr/bin/env python3
"""Regression tests for TI-84 Plus ASIC-control decoders."""

import unittest


from ti84re.hardware.asic_control import (
    ASIC_IMPLEMENTATIONS,
    asic_implementation,
    audit_immediate_io,
    decode_battery_configuration,
    decode_port02,
    decode_port15,
    decode_port21,
    implementation_port21_readback,
    iter_gpio_read_modify_writes,
    iter_immediate_port_consumers,
    iter_port02_consumers,
    port02_consumer,
    raw_immediate_io_locations,
    raw_port02_read_locations,
    summarize_port02_consumers,
)
from ti84re.rom.image import PAGE_SIZE, RomImage, RomLocation
from ti84re.rom.z80_disassembly import Z80Instruction


def instruction(
    address: int, text: str, data: bytes = b"\0", *, page: int = 0x33
) -> Z80Instruction:
    return Z80Instruction(RomLocation(page, address), data, text)


class AsicControlTests(unittest.TestCase):
    def test_decodes_observed_port02_values(self):
        locked = decode_port02(0xE3)
        waiting = decode_port02(0xE1)
        unlocked = decode_port02(0xE7)

        self.assertTrue(locked.battery_comparator_high)
        self.assertTrue(locked.lcd_ready)
        self.assertFalse(locked.flash_unlocked)
        self.assertFalse(waiting.lcd_ready)
        self.assertTrue(unlocked.flash_unlocked)

    def test_identity_table_and_unknown_value(self):
        identity = decode_port15(0x55)

        self.assertIsNotNone(identity)
        self.assertEqual(48, identity.ram_kib)
        self.assertIsNone(decode_port15(0x00))

    def test_port21_decodes_visible_fields_and_execution_pattern(self):
        mode0 = decode_port21(0xCC)
        mode2 = decode_port21(0x22)

        self.assertEqual(0x00, mode0.visible_value)
        self.assertEqual(0x7C00, mode0.tilem_ram_address_mask)
        self.assertEqual(4096, mode2.documented_flash_kib)
        self.assertEqual(128, mode2.documented_ram_kib)

    def test_decodes_tilem_battery_selector_without_reordering_it(self):
        self.assertEqual(43, decode_battery_configuration(0xC6).tilem_threshold_tenths_volt)
        self.assertEqual(36, decode_battery_configuration(0x86).tilem_threshold_tenths_volt)
        self.assertEqual(39, decode_battery_configuration(0x46).tilem_threshold_tenths_volt)
        self.assertEqual(33, decode_battery_configuration(0x06).tilem_threshold_tenths_volt)

    def test_finds_gpio_set_and_clear_sequences(self):
        instructions = (
            instruction(0x4000, "in a,(03ah)"),
            instruction(0x4002, "or 080h"),
            instruction(0x4004, "out (03ah),a"),
            instruction(0x4006, "in a,(039h)"),
            instruction(0x4008, "and 0efh"),
            instruction(0x400A, "out (039h),a"),
        )

        operations = tuple(iter_gpio_read_modify_writes(instructions))

        self.assertEqual(2, len(operations))
        self.assertEqual((0x3A, "set", 0x80), (
            operations[0].port,
            operations[0].operation,
            operations[0].mask,
        ))
        self.assertEqual((0x39, "clear", 0x10), (
            operations[1].port,
            operations[1].operation,
            operations[1].mask,
        ))

    def test_classifies_port02_and_and_bit_consumers(self):
        instructions = (
            instruction(0x4000, "in a,(002h)"),
            instruction(0x4002, "and 080h"),
            instruction(0x4004, "jr z,$+4"),
            instruction(0x4006, "in a,(002h)"),
            instruction(0x4008, "ld c,000h"),
            instruction(0x400A, "bit 0,a"),
        )

        consumers = tuple(iter_port02_consumers(instructions))

        self.assertEqual([0x80, 0x01], [consumer.mask for consumer in consumers])
        self.assertEqual([7], list(consumers[0].bits))
        self.assertEqual((instructions[4],), consumers[1].intervening)
        self.assertEqual({0x80: 1, 0x01: 1}, summarize_port02_consumers(consumers))

    def test_port02_consumer_stops_at_a_clobber(self):
        instructions = (
            instruction(0x4000, "in a,(002h)"),
            instruction(0x4002, "xor a"),
            instruction(0x4003, "and 080h"),
        )

        consumer = port02_consumer(instructions, 0)

        self.assertEqual("unclassified", consumer.form)
        self.assertIsNone(consumer.mask)

    def test_port02_consumer_rejects_non_status_instruction(self):
        self.assertIsNone(
            port02_consumer((instruction(0x4000, "in a,(015h)"),), 0)
        )

    def test_generic_consumer_classifies_port21_mask(self):
        instructions = (
            instruction(0x4000, "in a,(021h)"),
            instruction(0x4002, "and 003h"),
        )

        consumers = tuple(iter_immediate_port_consumers(instructions, 0x21))

        self.assertEqual(1, len(consumers))
        self.assertEqual(0x21, consumers[0].port)
        self.assertEqual(0x03, consumers[0].mask)

    def test_raw_port02_read_scan_is_page_aware(self):
        data = bytearray(PAGE_SIZE * 2)
        data[0x123:0x125] = bytes.fromhex("DB02")
        data[PAGE_SIZE + 0x456 : PAGE_SIZE + 0x458] = bytes.fromhex("DB02")
        rom = RomImage(bytes(data))

        self.assertEqual(
            (RomLocation(0, 0x0123), RomLocation(1, 0x4456)),
            raw_port02_read_locations(rom),
        )
        self.assertEqual(
            (RomLocation(1, 0x4456),),
            raw_port02_read_locations(rom, (1,)),
        )

    def test_generic_raw_scan_reports_direction_and_port(self):
        data = bytearray(PAGE_SIZE)
        data[0x100:0x104] = bytes.fromhex("DB21D33A")
        rom = RomImage(bytes(data))

        candidates = raw_immediate_io_locations(rom, (0x21, 0x3A))

        self.assertEqual(
            [
                (RomLocation(0, 0x0100), "in", 0x21),
                (RomLocation(0, 0x0102), "out", 0x3A),
            ],
            [
                (candidate.location, candidate.direction, candidate.port)
                for candidate in candidates
            ],
        )

    def test_immediate_io_audit_separates_code_overlap_and_reviewed_data(self):
        data = bytearray(PAGE_SIZE)
        data[0x100:0x102] = bytes.fromhex("DB21")
        data[0x200:0x203] = bytes.fromhex("3EDB21")
        data[0x300:0x302] = bytes.fromhex("DB39")
        rom = RomImage(bytes(data))
        instructions = (
            instruction(0x0100, "in a,(021h)", bytes.fromhex("DB21"), page=0),
            instruction(0x0200, "ld a,0dbh", bytes.fromhex("3EDB"), page=0),
            instruction(0x0202, "ld hl,00000h", bytes.fromhex("210000"), page=0),
            instruction(0x0300, "in a,(039h)", bytes.fromhex("DB39"), page=0),
        )

        port21 = audit_immediate_io(rom, instructions, (0x21,))
        port39 = audit_immediate_io(
            rom,
            instructions,
            (0x39,),
            reviewed_data={RomLocation(0, 0x0300): "reviewed table"},
        )

        self.assertEqual(
            {"instruction": 1, "operand-overlap": 1},
            port21.classification_counts,
        )
        self.assertTrue(port21.complete)
        self.assertEqual({"reviewed-data": 1}, port39.classification_counts)
        self.assertTrue(port39.complete)

    def test_rejects_register_mismatch_and_non_gpio_ports(self):
        instructions = (
            instruction(0x4000, "in a,(03ah)"),
            instruction(0x4002, "or 080h"),
            instruction(0x4004, "out (039h),a"),
            instruction(0x4006, "in a,(002h)"),
            instruction(0x4008, "or 080h"),
            instruction(0x400A, "out (002h),a"),
        )

        self.assertEqual((), tuple(iter_gpio_read_modify_writes(instructions)))

    def test_register_values_must_be_bytes(self):
        with self.assertRaises(ValueError):
            decode_port02(0x100)

    def test_emulator_profiles_pin_mame_control_port_omissions(self):
        mame = asic_implementation("mame")

        self.assertEqual({0x02, 0x15, 0x21}, set(mame.mapped_ports))
        self.assertEqual(0xC3, mame.fixed_port02_locked)
        self.assertEqual(0x33, mame.fixed_port15)
        self.assertEqual({"tilem", "wabbitemu", "mame"}, set(ASIC_IMPLEMENTATIONS))

    def test_port21_readback_disagreements_are_executable(self):
        self.assertEqual(0x33, implementation_port21_readback("tilem", 0xFF))
        self.assertEqual(0x03, implementation_port21_readback("wabbitemu", 0xFF))
        self.assertEqual(0x0F, implementation_port21_readback("mame", 0xFF))


if __name__ == "__main__":
    unittest.main()
