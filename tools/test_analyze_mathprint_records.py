#!/usr/bin/env python3
"""Tests for live MathPrint render-record decoding."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_mathprint_records import (
    HEADER_SIZE,
    DecodedRecord,
    DispatchSnapshot,
    decode_record_header,
    embedded_structural_records,
    graph_node_json,
    record_node_json,
    record,
    root_child_ids,
    select_entry_dispatch,
    word,
)


class MathPrintRecordTests(unittest.TestCase):
    def test_reads_little_endian_word(self):
        memory = bytearray(0x10000)
        memory[0x8DF2:0x8DF4] = bytes((0xE9, 0x9D))
        self.assertEqual(0x9DE9, word(memory, 0x8DF2))

    def test_snapshots_twenty_byte_header(self):
        memory = bytearray(0x10000)
        header = bytes(range(HEADER_SIZE))
        memory[0x9DE9:0x9DE9 + HEADER_SIZE] = header
        snapshot = record(memory, 0x9DE9)
        self.assertEqual(0x9DE9, snapshot.pointer)
        self.assertEqual(tuple(header), snapshot.header)

    def test_reads_root_child_id_table(self):
        memory = bytearray(0x10000)
        table = 0x9DE9 + HEADER_SIZE
        memory[table:table + 6] = bytes((0x0E, 0x00, 0x0F, 0x00, 0x07, 0x00))
        self.assertEqual((0x000E, 0x000F, 0x0007), root_child_ids(memory, 0x9DE9, 3))

    def test_decodes_unaligned_header_words(self):
        header = (
            0x10, 0x00, 0x27, 0x0F, 0x00, 0x01, 0x00, 0x0C, 0x00, 0x1B,
            0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0xEF,
        )
        self.assertEqual(
            DecodedRecord(0x10, 0x27, 0x0F, 1, 0x0C, 0x1B, 8, 0, 0, 1, 0xEF),
            decode_record_header(header),
        )

    def test_exports_an_executable_graph_node(self):
        header = (
            0x0F, 0x00, 0x24, 0x0E, 0x00, 0x02, 0x00, 0x0B, 0x00, 0x1A,
            0x00, 0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x33,
        )
        snapshot = DispatchSnapshot(
            instruction_index=12,
            clock=34,
            render_type=0x24,
            root=record(bytearray(0x10000), 0),
            current=record(bytearray(0x10000), 0),
            child_ids=(0x10, 0x11),
        )
        snapshot = DispatchSnapshot(
            **{**snapshot.__dict__, "root": type(snapshot.root)(0x9E65, header)}
        )
        self.assertEqual(
            {
                "record_id": 0x0F, "render_type": 0x24,
                "word03": 0x0E, "word05": 2, "word07": 0x0B,
                "word09": 0x1A, "word0B": 7, "word0D": 0,
                "word0F": 0, "word11": 1, "byte13": 0x33,
                "child_ids": [0x10, 0x11], "payload": [],
            },
            graph_node_json(snapshot),
        )

        self.assertEqual(
            graph_node_json(snapshot),
            record_node_json(snapshot.root, (0x10, 0x11)),
        )

    def test_selects_the_shallowest_final_redraw_dispatch(self):
        dispatches = [
            (100, 0x08, 0xFFBD, 0, 0),
            (140, 0x0D, 0xFF9B, 0x10, 5),
            (300, 0x13, 0xFFBB, 0, 0),
            (340, 0x18, 0xFF9B, 0x14, 6),
        ]
        self.assertEqual(
            (300, 0x13, 0xFFBB, 0, 0),
            select_entry_dispatch(dispatches, 250),
        )

    def test_finds_embedded_structural_records_in_program_order(self):
        payload = (
            0xEF, 0x29, 0x13, 0x00, 0xEF, 0x2D, 0x4E,
            0xEF, 0x2A, 0x18, 0x00, 0xEF, 0x2D,
        )
        self.assertEqual(
            ((0x29, 0x0013), (0x2A, 0x0018)),
            embedded_structural_records(payload),
        )

    def test_does_not_treat_an_extended_leaf_token_as_a_record(self):
        self.assertEqual((), embedded_structural_records((0xEF, 0x1E)))

    def test_captures_leaf_payload_from_offset_13(self):
        memory = bytearray(0x10000)
        pointer = 0x9000
        memory[pointer:pointer + 0x16] = bytes.fromhex(
            "11 00 00 0F 00 07 00 12 00 03 00 08 00 04 00 03 00 03 00 58 70 31"
        )
        snapshot = record(memory, pointer)
        self.assertEqual((0x58, 0x70, 0x31), snapshot.payload)
        self.assertEqual([0x58, 0x70, 0x31], record_node_json(snapshot)["payload"])

    def test_rejects_header_past_memory_end(self):
        with self.assertRaises(ValueError):
            record(bytearray(0x10000), 0xFFFF)


if __name__ == "__main__":
    unittest.main()
