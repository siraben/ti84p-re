#!/usr/bin/env python3
"""Regression tests for TI-84 Plus trace address resolution."""

import unittest
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tilem_trace_resolve import (
    Banker,
    HEADER_FMT,
    INSTR_FMT,
    IDX_BC,
    IDX_OPCODE,
    IDX_PC,
    IDX_WZ,
    resolve_instruction,
)


def instruction(pc, opcode=0x00, wz=0x0000, bc=0x0000):
    fields = [0] * 23
    fields[IDX_PC] = pc
    fields[IDX_OPCODE] = opcode
    fields[IDX_WZ] = wz
    fields[IDX_BC] = bc
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

    def test_block_output_invalidates_forced_ram_extent(self):
        banker = Banker.ti84p_reset()

        _, switch = resolve_instruction(
            banker, instruction(0x1234, opcode=0xEDAB, bc=0x0028)
        )

        self.assertEqual((0x28, None), switch)
        self.assertEqual("page_??", banker.resolve(0x8000)[0])


class CliSafetyTests(unittest.TestCase):
    def write_trace(self, pc):
        temp = tempfile.NamedTemporaryFile(delete=False)
        path = Path(temp.name)
        with temp:
            temp.write(struct.pack(HEADER_FMT, b"TLMT", 2, 7, 0, 0xFFFF, 0))
            temp.write(b"\x01")
            temp.write(struct.pack(INSTR_FMT, *instruction(pc)))
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def run_resolver(self, trace, *args):
        return subprocess.run(
            [sys.executable, str(Path(__file__).with_name("tilem_trace_resolve.py")),
             str(trace), *args],
            check=False, text=True, capture_output=True,
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


if __name__ == "__main__":
    unittest.main()
