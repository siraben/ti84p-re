#!/usr/bin/env python3
"""Tests for the page-3B circle schedule and point-pair translation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

from graph_circle import (
    COEFFICIENT_TABLE,
    CONSUMED_COEFFICIENT_INDICES,
    DEFAULT_ROM,
    OP1,
    OP2,
    OP3,
    OP4,
    PAIR_HELPER_END,
    PAIR_HELPER_ENTRY,
    RECURRENCE_CALL_SITES,
    TAIL_CALL_SITES,
    TAIL_FRAME_OFFSETS,
    TIFLOAT_SIZE,
    analyze_trace,
    decode_tifloat_real,
    inspect_rom,
    translate_pair_helper,
)
from rom_image import RomImage


ROOT = Path(__file__).resolve().parents[1]
CHECKED_REPORT = ROOT / "tools" / "graph-circle.json"
TRACE_ENV = "TI84_GRAPH_CIRCLE_TRACE"


def seeded_record(seed: int, lane: int) -> bytes:
    """Expand a 16-bit state into one deterministic nine-byte record."""

    return bytes(
        (seed * (2 * index + 1) + (seed >> 8) + 37 * lane + 13 * index) & 0xFF
        for index in range(TIFLOAT_SIZE)
    )


def interpret_pair_helper(code: bytes, old_pair: tuple[bytes, bytes],
                          new_pair: tuple[bytes, bytes], pointer: int) -> dict[str, object]:
    """Execute the pinned 3B:72F3 bytes with three call boundaries modeled."""

    memory: dict[int, int] = {}

    def put(address: int, value: bytes) -> None:
        for offset, byte in enumerate(value):
            memory[address + offset] = byte

    def get(address: int) -> bytes:
        return bytes(memory.get(address + offset, 0) for offset in range(TIFLOAT_SIZE))

    put(pointer, old_pair[0])
    put(pointer + TIFLOAT_SIZE, old_pair[1])
    put(OP1, new_pair[0])
    put(OP2, new_pair[1])
    pc = PAIR_HELPER_ENTRY
    hl, de = pointer, 0
    stack: list[int] = []
    line_registers = None

    def mov9() -> None:
        nonlocal hl, de
        value = get(hl)
        put(de, value)
        hl += TIFLOAT_SIZE
        de += TIFLOAT_SIZE

    while True:
        offset = pc - PAIR_HELPER_ENTRY
        opcode = code[offset]
        if opcode == 0xE5:  # PUSH HL
            stack.append(hl)
            pc += 1
        elif opcode == 0xD5:  # PUSH DE
            stack.append(de)
            pc += 1
        elif opcode == 0xE1:  # POP HL
            hl = stack.pop()
            pc += 1
        elif opcode == 0xD1:  # POP DE
            de = stack.pop()
            pc += 1
        elif opcode == 0x11:  # LD DE,nn
            de = code[offset + 1] | code[offset + 2] << 8
            pc += 3
        elif opcode == 0x23:  # INC HL
            hl = (hl + 1) & 0xFFFF
            pc += 1
        elif opcode == 0x13:  # INC DE
            de = (de + 1) & 0xFFFF
            pc += 1
        elif opcode == 0xCD:  # CALL nn
            target = code[offset + 1] | code[offset + 2] << 8
            if target == 0x1A92:
                mov9()
            elif target == 0x1B0C:
                hl = OP1
                mov9()
            elif target == 0x3453:
                line_registers = (get(OP1), get(OP2), get(OP3), get(OP4))
            else:
                raise AssertionError(f"unexpected helper call 0x{target:04X}")
            pc += 3
        elif opcode == 0xC9:  # RET
            break
        else:
            raise AssertionError(f"unexpected opcode 0x{opcode:02X} at 3B:{pc:04X}")

    return {
        "frame": (get(pointer), get(pointer + TIFLOAT_SIZE)),
        "op3_op4": (get(OP3), get(OP4)),
        "line_registers": line_registers,
        "hl": hl,
        "stack": tuple(stack),
    }


@unittest.skipUnless(DEFAULT_ROM.is_file(), "pinned ROM not present")
class GraphCircleRomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rom = RomImage.from_path(DEFAULT_ROM)
        cls.report = inspect_rom(cls.rom)

    def test_draw_circ2_finite_schedule(self) -> None:
        self.assertEqual(self.report["allocation_bytes"], 0xA2)
        self.assertEqual(self.report["allocation_tifloats"], 18)
        self.assertEqual(self.report["loop_iterations"], 7)
        self.assertEqual(self.report["recurrence_call_sites"], RECURRENCE_CALL_SITES)
        self.assertEqual(self.report["tail_call_sites"], TAIL_CALL_SITES)
        self.assertEqual(self.report["tail_frame_offsets"], TAIL_FRAME_OFFSETS)
        self.assertEqual(self.report["total_coordinate_lines"], 8 * 7 + 4)

    def test_consumed_coefficients_and_adjacent_entry(self) -> None:
        self.assertEqual(self.report["coefficient_indices"], CONSUMED_COEFFICIENT_INDICES)
        self.assertEqual(
            self.report["coefficients"],
            (
                "0.10452846326765",
                "0.99452189536827",
                "0.20791169081776",
                "0.97814760073381",
                "0.30901699437495",
                "0.95105651629515",
                "0.40673664307580",
            ),
        )
        self.assertEqual(self.report["adjacent_coefficient"], "0.91354545764260")

    def test_coefficient_decoder_rejects_non_bcd(self) -> None:
        raw = bytearray(self.rom.bytes_at(0x35, COEFFICIENT_TABLE, TIFLOAT_SIZE))
        raw[-1] = 0xFA
        with self.assertRaisesRegex(ValueError, "non-BCD"):
            decode_tifloat_real(bytes(raw))

    def test_pair_helper_matches_raw_bytes_for_every_16_bit_seed(self) -> None:
        code = self.rom.bytes_at(
            0x3B, PAIR_HELPER_ENTRY, PAIR_HELPER_END - PAIR_HELPER_ENTRY
        )
        pointer = 0x9300
        for seed in range(0x10000):
            old_pair = seeded_record(seed, 0), seeded_record(seed, 1)
            new_pair = seeded_record(seed, 2), seeded_record(seed, 3)
            translated = translate_pair_helper(*old_pair, *new_pair, pointer=pointer)
            interpreted = interpret_pair_helper(code, old_pair, new_pair, pointer)
            self.assertEqual(interpreted["frame"], new_pair)
            self.assertEqual(interpreted["op3_op4"], old_pair)
            self.assertEqual(interpreted["line_registers"], translated.line_registers)
            self.assertEqual(interpreted["hl"], translated.returned_pointer)
            self.assertEqual(interpreted["stack"], ())

    def test_cline_bjump_descriptor(self) -> None:
        # 00:3453 calls the bjump trampoline with target 33:6028.  The raw page
        # byte is 73h and masks to physical page 33h on this 64-page ROM.
        self.assertEqual(self.report["cline_bjump_descriptor"], "cd092b286073")


class GraphCircleCheckedEvidenceTests(unittest.TestCase):
    def test_checked_report(self) -> None:
        report = json.loads(CHECKED_REPORT.read_text(encoding="utf-8"))
        static = report["static"]
        trace = report["natural_trace"]
        self.assertEqual(report["rom"]["path"], "tools/rom.bin")
        self.assertEqual(
            report["tilem"]["commit"],
            "d1bdc58dd321ae462a701e556fcb62bb925a78b1",
        )
        self.assertEqual(
            report["tilem"]["binary_sha256"],
            "cdd257c57b918b8f0b05df6e49f249d4f0461a7c1ed2d9b87fe76fc3d2b0e1ee",
        )
        self.assertEqual(static["total_coordinate_lines"], 60)
        self.assertEqual(trace["coordinate_lines"], 60)
        self.assertEqual(trace["continuous_adjacent_lines"], 59)
        self.assertEqual(trace["caller_state"], "page_33_alternate")
        self.assertEqual(
            trace["sha256"],
            "24195a9630a1f06d1a83f96bc8d1e3cecb51729df97e2a14c1e01bf50096e17d",
        )
        self.assertEqual(trace["point_visits"]["draw_circ2"], 0)
        self.assertEqual(trace["point_visits"]["grph_circ"], 0)
        self.assertEqual(trace["point_visits"]["draw_circ2_coefficient_lookup"], 0)
        self.assertEqual(trace["point_visits"]["circ_cmd"], 1)
        self.assertEqual(trace["point_visits"]["alternate_generator"], 1)
        self.assertEqual(trace["point_visits"]["alternate_loop"], 61)
        self.assertEqual(trace["point_visits"]["alternate_line_emit"], 60)
        self.assertEqual(
            trace["generator_branch_states"],
            [{
                "iy": 0x89F0,
                "flag_address": 0x8A2C,
                "flag_byte": 0,
                "tested_bit": 4,
                "tested_bit_set": 0,
            }],
        )
        self.assertEqual(
            trace["generator_selection"],
            {
                "branch": "33:74DF",
                "tested_flag": "(IY+3C).4",
                "selected_when": "clear",
                "entry": "33:74E9",
                "loop": "33:7506",
                "line_emit": "33:7561",
                "end": "33:7580",
                "page_35_79e9_visits": 0,
            },
        )
        self.assertEqual(
            trace["plot_sscreen_sha256"],
            "7c4191a9b28ddd6526b391dec69b34367975a58f39c72daa8eb4fb1afed09868",
        )
        self.assertEqual(trace["plot_sscreen_dark_pixels"], 306)
        first = trace["first_segments"][0]
        self.assertEqual((first["old_x"], first["old_y"]), ("5.0000000000000", "0E-13"))
        self.assertEqual(
            (first["new_x"], first["new_y"]),
            ("4.9726094768414", "0.52264231633825"),
        )


class GraphCircleOptionalTraceTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get(TRACE_ENV), f"set {TRACE_ENV} to a TLMT v2 trace")
    def test_external_natural_trace_matches_checked_evidence(self) -> None:
        actual = analyze_trace(Path(os.environ[TRACE_ENV]))
        checked = json.loads(CHECKED_REPORT.read_text(encoding="utf-8"))["natural_trace"]
        self.assertEqual(actual, checked)


if __name__ == "__main__":
    unittest.main()
