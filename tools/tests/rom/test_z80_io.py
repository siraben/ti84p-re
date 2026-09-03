#!/usr/bin/env python3
"""Regression tests for static Z80 I/O-access decoding."""

import unittest


from ti84re.rom.image import PAGE_SIZE, RomImage, RomLocation
from ti84re.rom.z80_disassembly import Z80Instruction
from ti84re.rom.z80_io import (
    direct_io_access,
    iter_direct_io_accesses,
    iter_resolved_io_accesses,
    parse_port_specs,
    raw_indirect_io_boundary_prefixes,
    raw_indirect_io_locations,
)


def instruction(address: int, text: str, data: bytes = b"\0") -> Z80Instruction:
    return Z80Instruction(RomLocation(0x35, address), data, text)


class Z80IOTests(unittest.TestCase):
    def test_decodes_immediate_input_port(self):
        access = direct_io_access(instruction(0x4000, "in a,(04dh)"))

        self.assertIsNotNone(access)
        self.assertEqual("in", access.direction)
        self.assertEqual(0x4D, access.port)

    def test_decodes_immediate_output_port(self):
        access = direct_io_access(instruction(0x4000, "out (0a2h),a"))

        self.assertIsNotNone(access)
        self.assertEqual("out", access.direction)
        self.assertEqual(0xA2, access.port)

    def test_rejects_register_indirect_port(self):
        self.assertIsNone(direct_io_access(instruction(0x4000, "outi")))
        self.assertIsNone(direct_io_access(instruction(0x4000, "in a,(c)")))

    def test_filters_selected_ports(self):
        instructions = (
            instruction(0x4000, "in a,(04dh)"),
            instruction(0x4002, "out (055h),a"),
        )

        accesses = tuple(iter_direct_io_accesses(instructions, (0x55,)))

        self.assertEqual(1, len(accesses))
        self.assertEqual(0x55, accesses[0].port)

    def test_resolves_c_loaded_directly(self):
        instructions = (
            instruction(0x4000, "ld c,015h"),
            instruction(0x4002, "in a,(c)"),
        )

        accesses = tuple(iter_resolved_io_accesses(instructions))

        self.assertEqual(1, len(accesses))
        self.assertEqual(0x15, accesses[0].port)
        self.assertEqual("register-c", accesses[0].source)

    def test_resolves_c_from_bc_low_byte(self):
        instructions = (
            instruction(0x4000, "ld bc,03a3ah"),
            instruction(0x4003, "out (c),a"),
        )

        accesses = tuple(iter_resolved_io_accesses(instructions, (0x3A,)))

        self.assertEqual(1, len(accesses))
        self.assertEqual("out", accesses[0].direction)

    def test_forgets_c_across_control_flow_and_writes(self):
        cases = (
            "call 05000h",
            "jr nz,$+4",
            "pop bc",
            "ld c,a",
            "ldir",
            "rl c",
        )
        for boundary in cases:
            with self.subTest(boundary=boundary):
                instructions = (
                    instruction(0x4000, "ld c,015h"),
                    instruction(0x4002, boundary),
                    instruction(0x4003, "in a,(c)"),
                )
                self.assertEqual((), tuple(iter_resolved_io_accesses(instructions)))

    def test_tracks_literal_c_through_increment_and_decrement(self):
        instructions = (
            instruction(0x4000, "ld c,049h"),
            instruction(0x4002, "dec c"),
            instruction(0x4003, "ini"),
            instruction(0x4005, "inc bc"),
            instruction(0x4006, "outi"),
        )

        accesses = tuple(iter_resolved_io_accesses(instructions))

        self.assertEqual([0x48, 0x49], [access.port for access in accesses])
        self.assertEqual(["in", "out"], [access.direction for access in accesses])

    def test_scans_raw_register_and_block_io_pairs(self):
        data = bytearray(PAGE_SIZE * 2)
        data[0x123:0x125] = bytes.fromhex("ED78")
        data[PAGE_SIZE + 0x456 : PAGE_SIZE + 0x458] = bytes.fromhex("EDA3")
        rom = RomImage(bytes(data))

        candidates = raw_indirect_io_locations(rom)

        self.assertEqual(
            [("00:0123", "in", "IN A,(C)"), ("01:4456", "out", "OUTI")],
            [
                (str(item.location), item.direction, item.form)
                for item in candidates
            ],
        )

    def test_reports_page_ending_indirect_prefix(self):
        data = bytearray(PAGE_SIZE * 2)
        data[PAGE_SIZE - 1] = 0xED
        rom = RomImage(bytes(data))

        self.assertEqual(
            (RomLocation(0, 0x3FFF),),
            raw_indirect_io_boundary_prefixes(rom),
        )

    def test_keeps_direct_access_source(self):
        access = next(
            iter_resolved_io_accesses((instruction(0x4000, "in a,(04dh)"),))
        )

        self.assertEqual("immediate", access.source)

    def test_in_c_overwrites_the_resolved_port_register(self):
        instructions = (
            instruction(0x4000, "ld c,015h"),
            instruction(0x4002, "in c,(c)"),
            instruction(0x4004, "in a,(c)"),
        )

        accesses = tuple(iter_resolved_io_accesses(instructions))

        self.assertEqual(1, len(accesses))
        self.assertEqual(0x15, accesses[0].port)

    def test_parses_ports_and_inclusive_ranges(self):
        self.assertEqual(
            frozenset((0x4D, 0x80, 0x81, 0x82)),
            parse_port_specs(("0x4d", "0x80-0x82")),
        )

    def test_parses_comma_separated_selectors(self):
        self.assertEqual(
            frozenset((0x55, 0x57, 0x58)), parse_port_specs(("0x55,0x57-0x58",))
        )

    def test_rejects_invalid_port_selectors(self):
        for spec in ("0x100", "0x82-0x80", "garbage", "0x80,"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                parse_port_specs((spec,))


if __name__ == "__main__":
    unittest.main()
