#!/usr/bin/env python3
"""Regression tests for TI-84 Plus trace address resolution."""

import argparse
import os
import unittest
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


from ti84re.trace.resolve import (
    Banker,
    HEADER_FMT,
    INSTR_FMT,
    IDX_BC,
    IDX_CLOCK,
    IDX_AF,
    IDX_DE,
    IDX_HL,
    IDX_OPCODE,
    IDX_PC,
    IDX_WZ,
    decode_io_event,
    parse_clock_range,
    parse_port_set,
    resolve_instruction,
)
from ti84re.paths import TOOLS


def instruction(pc, opcode=0x00, wz=0x0000, af=0x0000, bc=0x0000,
                de=0x0000, hl=0x0000, clock=0):
    fields = [0] * 23
    fields[IDX_PC] = pc
    fields[IDX_OPCODE] = opcode
    fields[IDX_CLOCK] = clock
    fields[IDX_WZ] = wz
    fields[IDX_AF] = af
    fields[IDX_BC] = bc
    fields[IDX_DE] = de
    fields[IDX_HL] = hl
    return tuple(fields)


class BankerTests(unittest.TestCase):
    def test_out_instruction_uses_pre_write_mapping(self):
        banker = Banker(initial_port4=0, initial_port5=0,
                        initial_port6=2, initial_port7=3)
        fields = instruction(0x4123, opcode=0xD3, wz=0x0406)

        resolved, switch = resolve_instruction(banker, fields)

        self.assertEqual(("page_02", 0x4123, 0x8123, 2), resolved)
        self.assertEqual((6, 4), switch)
        self.assertEqual("page_04", banker.resolve(0x4123)[0])

    def test_ti84p_reset_mapping_is_paired(self):
        banker = Banker.ti84p_reset()

        self.assertEqual("page_3E", banker.resolve(0x4000)[0])
        self.assertEqual("page_3F", banker.resolve(0x8000)[0])
        self.assertEqual(("page_3F", 0x4000, 0xFC000, 0x3F),
                         banker.resolve(0xC000))
        self.assertTrue(banker.mapping_complete())

    def test_independent_mode_maps_high_window_from_port5(self):
        banker = Banker(initial_port4=0, initial_port5=3,
                        initial_port6=2, initial_port7=4,
                        initial_port27=0, initial_port28=0)

        self.assertEqual("page_02", banker.resolve(0x4000)[0])
        self.assertEqual("page_04", banker.resolve(0x8000)[0])
        self.assertEqual(("ram", 0xC123, None, None),
                         banker.resolve(0xC123))

    def test_unknown_initial_mapping_stays_explicit(self):
        banker = Banker()

        self.assertEqual("page_??", banker.resolve(0x4000)[0])
        self.assertEqual("page_??", banker.resolve(0x8000)[0])
        self.assertEqual("page_??", banker.resolve(0xC000)[0])
        self.assertFalse(banker.mapping_complete())

    def test_forced_ram_subranges_override_banked_flash(self):
        banker = Banker(initial_port4=1, initial_port5=0,
                        initial_port6=2, initial_port7=3,
                        initial_port27=1, initial_port28=1)

        self.assertEqual(("ram", 0x8000, None, None),
                         banker.resolve(0x8000))
        self.assertEqual("ram", banker.resolve(0x803F)[0])
        self.assertEqual("page_03", banker.resolve(0x8040)[0])
        self.assertEqual("page_03", banker.resolve(0xFFBF)[0])
        self.assertEqual(("ram", 0xFFC0, None, None),
                         banker.resolve(0xFFC0))

    def test_unknown_forced_range_port_is_conservative(self):
        banker = Banker(initial_port4=1, initial_port5=0,
                        initial_port6=2, initial_port7=3,
                        initial_port27=0, initial_port28=None)

        self.assertEqual("page_02", banker.resolve(0x4000)[0])
        self.assertEqual("page_??", banker.resolve(0x8000)[0])
        self.assertEqual("page_03", banker.resolve(0xC000)[0])

    def test_out_c_zero_updates_mapping(self):
        banker = Banker(initial_port4=0, initial_port5=0,
                        initial_port6=4, initial_port7=3,
                        initial_port27=0, initial_port28=0)

        resolved, switch = resolve_instruction(
            banker, instruction(0x4123, opcode=0xED71, bc=0x0006)
        )

        self.assertEqual("page_04", resolved[0])
        self.assertEqual((6, 0), switch)
        self.assertEqual("page_00", banker.resolve(0x4123)[0])

    def test_block_output_invalidates_mapping_port(self):
        banker = Banker(initial_port4=0, initial_port5=0,
                        initial_port6=4, initial_port7=3,
                        initial_port27=0, initial_port28=0)

        resolved, switch = resolve_instruction(
            banker, instruction(0x4123, opcode=0xEDB3, bc=0x0006)
        )

        self.assertEqual("page_04", resolved[0])
        self.assertEqual((6, None), switch)
        self.assertEqual("page_??", banker.resolve(0x4123)[0])

    def test_mapping_output_updates_forced_ram_extent(self):
        banker = Banker.ti84p_reset()

        resolved, switch = resolve_instruction(
            banker, instruction(0x1234, opcode=0xD3, wz=0x0127)
        )

        self.assertEqual("ram", resolved[0])
        self.assertEqual((0x27, 1), switch)
        self.assertEqual("ram", banker.resolve(0xFFC0)[0])

    def test_extended_flash_port_write_is_tracked(self):
        banker = Banker.ti84p_reset()

        resolved, switch = resolve_instruction(
            banker, instruction(0x1234, opcode=0xD3, wz=0x1F0E)
        )

        self.assertEqual("ram", resolved[0])
        self.assertEqual((0x0E, 0x1F), switch)
        self.assertEqual(3, banker.port0e)
        self.assertEqual("page_3E", banker.resolve(0x4000)[0])

    def test_block_output_invalidates_forced_ram_extent(self):
        banker = Banker.ti84p_reset()

        _, switch = resolve_instruction(
            banker, instruction(0x1234, opcode=0xEDAB, bc=0x0028)
        )

        self.assertEqual((0x28, None), switch)
        self.assertEqual("page_??", banker.resolve(0x8000)[0])


class IoDecodeTests(unittest.TestCase):
    def test_immediate_output_uses_wz_port_and_post_a(self):
        event = decode_io_event(
            instruction(0x1234, opcode=0xD3, wz=0xA510, af=0xA544)
        )

        self.assertEqual(("OUT", 0x10, 0xA5, "(n),A"), event)

    def test_immediate_input_returns_post_a(self):
        event = decode_io_event(
            instruction(0x1234, opcode=0xDB, wz=0xE311, af=0x7F44)
        )

        self.assertEqual(("IN", 0x11, 0x7F, "A,(n)"), event)

    def test_in_c_uses_pre_input_port_from_wz(self):
        event = decode_io_event(
            instruction(0x1234, opcode=0xED48, wz=0x1230, bc=0x12AB)
        )

        self.assertEqual(("IN", 0x30, 0xAB, "C,(C)"), event)

    def test_out_c_uses_post_register_and_unchanged_c_port(self):
        event = decode_io_event(
            instruction(0x1234, opcode=0xED51, bc=0x1211, de=0xA5E3)
        )

        self.assertEqual(("OUT", 0x11, 0xA5, "(C),D"), event)

    def test_block_output_has_unknown_value(self):
        event = decode_io_event(
            instruction(0x1234, opcode=0xEDB3, bc=0x0711)
        )

        self.assertEqual(("OUT", 0x11, None, "block"), event)

    def test_port_set_accepts_hex_ranges(self):
        self.assertEqual({0x10, 0x11, 0x12, 0x13, 0x2F},
                         parse_port_set("10-13,2f"))

    def test_clock_range_accepts_decimal_and_prefixed_hex(self):
        self.assertEqual((100, 0x100), parse_clock_range("100-0x100"))

    def test_clock_range_rejects_reverse_and_overflow(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_clock_range("200-100")
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_clock_range("0x100000000")


class CliSafetyTests(unittest.TestCase):
    def write_trace(self, pc, **instruction_args):
        temp = tempfile.NamedTemporaryFile(delete=False)
        path = Path(temp.name)
        with temp:
            temp.write(struct.pack(HEADER_FMT, b"TLMT", 2, 7, 0, 0xFFFF, 0))
            temp.write(b"\x01")
            temp.write(struct.pack(INSTR_FMT, *instruction(pc, **instruction_args)))
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def write_trace_with_key_event(self, pc, *, clock, key, pressed):
        path = self.write_trace(pc)
        with path.open("ab") as fp:
            fp.write(b"\x03")
            fp.write(struct.pack("<BBIH", pressed, key, clock, pc))
        return path

    def run_resolver(self, trace, *args):
        return subprocess.run(
            [sys.executable, "-m", "ti84re.trace.resolve", str(trace), *args],
            check=False, text=True, capture_output=True,
            env={**os.environ, "PYTHONPATH": str(TOOLS)},
        )

    def test_reset_preset_warns_when_first_pc_is_not_reset_entry(self):
        result = self.run_resolver(
            self.write_trace(0x1234), "--initial-mapping", "ti84p-reset"
        )

        self.assertEqual(0, result.returncode)
        self.assertIn("requires the first traced PC to be 0x8000", result.stderr)

    def test_ring_flag_warns_when_mapping_history_is_incomplete(self):
        result = self.run_resolver(self.write_trace(0x1234), "--ring")

        self.assertEqual(0, result.returncode)
        self.assertIn("lacks enough page-switch history", result.stderr)

    def test_key_event_output_names_on_and_honors_clock_filter(self):
        trace = self.write_trace_with_key_event(
            0x1234, clock=150, key=0x29, pressed=1
        )

        shown = self.run_resolver(
            trace, "--key-events", "--event-clock", "100-200"
        )
        hidden = self.run_resolver(
            trace, "--key-events", "--event-clock", "151-200"
        )

        self.assertEqual(0, shown.returncode)
        self.assertIn("KEY pressed  0x29 ON", shown.stdout)
        self.assertNotIn("KEY pressed", hidden.stdout)

    def test_io_event_honors_clock_filter(self):
        trace = self.write_trace(
            0x1234, opcode=0xD3, wz=0xAA01, af=0xAA00, clock=150
        )

        shown = self.run_resolver(
            trace, "--io-ports", "01", "--event-clock", "100-200"
        )
        hidden = self.run_resolver(
            trace, "--io-ports", "01", "--event-clock", "151-200"
        )

        self.assertEqual(0, shown.returncode)
        self.assertIn("OUT (0x01) <- 0xaa", shown.stdout)
        self.assertNotIn("OUT (0x01)", hidden.stdout)


if __name__ == "__main__":
    unittest.main()
