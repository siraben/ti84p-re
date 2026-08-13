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
    decode_settled_expression,
    decode_record_header,
    embedded_structural_records,
    graph_node_json,
    attribute_record_writes,
    record_field_name,
    record_locations,
    record_node_json,
    record_storage_size,
    record,
    root_child_ids,
    select_entry_dispatch,
    word,
)
from hardware_trace import ResolvedMemoryWrite


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

    def test_decodes_nested_multi_argument_expression_without_pixels(self):
        nodes = [
            {"record_id": 20, "render_type": 0, "child_ids": [],
             "payload": [0xEF, 0x20, 27, 0, 0xEF, 0x2D]},
            {"record_id": 27, "render_type": 0x20, "child_ids": [28, 29],
             "payload": []},
            {"record_id": 28, "render_type": 0, "child_ids": [],
             "payload": [0xEF, 0x23, 21, 0, 0xEF, 0x2D]},
            {"record_id": 21, "render_type": 0x23, "child_ids": [22, 23, 24],
             "payload": []},
            {"record_id": 22, "render_type": 1, "child_ids": [],
             "payload": [0x58]},
            {"record_id": 23, "render_type": 0, "child_ids": [],
             "payload": [0x58, 0xEF, 0x2A, 25, 0, 0xEF, 0x2D]},
            {"record_id": 25, "render_type": 0x2A, "child_ids": [26],
             "payload": []},
            {"record_id": 26, "render_type": 0, "child_ids": [],
             "payload": [0x33]},
            {"record_id": 24, "render_type": 0, "child_ids": [],
             "payload": [0x31]},
            {"record_id": 29, "render_type": 0, "child_ids": [],
             "payload": [0x32]},
        ]
        self.assertEqual(
            {
                "kind": "fraction",
                "numerator": {
                    "kind": "nDeriv", "variable": [0x58],
                    "body": {"kind": "power", "base": [0x58],
                             "exponent": [0x33]},
                    "value": [0x31],
                },
                "denominator": [0x32],
            },
            decode_settled_expression(nodes, 20),
        )

    def test_exposes_an_extra_token_after_a_power(self):
        nodes = [
            {"record_id": 10, "render_type": 0, "child_ids": [],
             "payload": [0xEF, 0x23, 11, 0, 0xEF, 0x2D]},
            {"record_id": 11, "render_type": 0x23, "child_ids": [12, 1, 13],
             "payload": []},
            {"record_id": 12, "render_type": 1, "child_ids": [],
             "payload": [0x58]},
            {"record_id": 1, "render_type": 0, "child_ids": [],
             "payload": [0x58, 0xEF, 0x2A, 2, 0, 0xEF, 0x2D, 0x58]},
            {"record_id": 2, "render_type": 0x2A, "child_ids": [3],
             "payload": []},
            {"record_id": 3, "render_type": 0, "child_ids": [],
             "payload": [0x32]},
            {"record_id": 13, "render_type": 0, "child_ids": [],
             "payload": [0x31]},
        ]
        self.assertEqual(
            {
                "kind": "nDeriv", "variable": [0x58],
                "body": {
                    "kind": "sequence",
                    "parts": [
                        {"kind": "power", "base": [0x58],
                         "exponent": [0x32]},
                        [0x58],
                    ],
                },
                "value": [0x31],
            },
            decode_settled_expression(nodes, 10),
        )

    def test_retains_ef1e_as_a_placeholder_outside_nderiv_body(self):
        self.assertEqual(
            {"kind": "extendedToken", "tokens": [0xEF, 0x1E]},
            decode_settled_expression([
                {"record_id": 1, "render_type": 0, "child_ids": [],
                 "payload": [0xEF, 0x1E]},
            ], 1),
        )

    def test_retains_ef1e_as_a_placeholder_inside_nderiv_body(self):
        self.assertEqual(
            {
                "kind": "nDeriv", "variable": [0x58],
                "body": {"kind": "extendedToken", "tokens": [0xEF, 0x1E]},
                "value": [0x31],
            },
            decode_settled_expression([
                {"record_id": 1, "render_type": 0, "child_ids": [],
                 "payload": [0xEF, 0x23, 2, 0, 0xEF, 0x2D]},
                {"record_id": 2, "render_type": 0x23,
                 "child_ids": [3, 4, 5], "payload": []},
                {"record_id": 3, "render_type": 1, "child_ids": [],
                 "payload": [0x58]},
                {"record_id": 4, "render_type": 0, "child_ids": [],
                 "payload": [0xEF, 0x1E]},
                {"record_id": 5, "render_type": 0, "child_ids": [],
                 "payload": [0x31]},
            ], 1),
        )

    def test_captures_leaf_payload_from_offset_13(self):
        memory = bytearray(0x10000)
        pointer = 0x9000
        memory[pointer:pointer + 0x16] = bytes.fromhex(
            "11 00 00 0F 00 07 00 12 00 03 00 08 00 04 00 03 00 03 00 58 70 31"
        )
        snapshot = record(memory, pointer)
        self.assertEqual((0x58, 0x70, 0x31), snapshot.payload)
        self.assertEqual([0x58, 0x70, 0x31], record_node_json(snapshot)["payload"])

    def test_sizes_leaf_and_structural_arena_records(self):
        memory = bytearray(0x10000)
        memory[0x9000:0x9016] = bytes.fromhex(
            "11 00 00 0F 00 07 00 12 00 03 00 08 00 04 00 03 00 03 00 58 70 31"
        )
        self.assertEqual(0x16, record_storage_size(record(memory, 0x9000)))
        memory[0x9100:0x9114] = bytes.fromhex(
            "12 00 21 11 00 01 00 07 00 12 00 03 00 00 00 00 00 01 00 EF"
        )
        self.assertEqual(
            0x18, record_storage_size(record(memory, 0x9100), (0x13, 0x14))
        )

    def test_names_header_payload_and_child_bytes(self):
        self.assertEqual("word09.hi", record_field_name(0, 0x0A, 3))
        self.assertEqual("payload[0]/byte13", record_field_name(0, 0x13, 3))
        self.assertEqual("payload[2]", record_field_name(0, 0x15, 3))
        self.assertEqual("child[2].hi", record_field_name(0x21, 0x17))

    def test_attributes_writes_to_final_record_ids(self):
        nodes = [
            {
                "record_id": 13, "render_type": 0, "pointer": 0x9E79,
                "storage_size": 0x16, "payload": [0x58, 0x71, 0x33],
            },
            {
                "record_id": 14, "render_type": 0x21, "pointer": 0x9E63,
                "storage_size": 0x16, "payload": [],
            },
        ]
        locations = record_locations(nodes)
        writes = [ResolvedMemoryWrite(
            instruction_index=12, clock=34, logical_pc=0x4856,
            pc_space="page_34", pc_address=0x4856,
            logical_address=0x9E68, value=1, target_kind="ram",
            target_page=1, page_offset=0x1E68, flat_address=None,
            unresolved=False,
        )]
        self.assertEqual(
            [(14, "word05.lo", 1)],
            [(item.final_record_id, item.field, item.value)
             for item in attribute_record_writes(writes, locations, nodes)],
        )

    def test_rejects_overlapping_record_ranges(self):
        with self.assertRaisesRegex(ValueError, "overlaps"):
            record_locations([
                {"record_id": 1, "pointer": 0x9000, "storage_size": 0x16},
                {"record_id": 2, "pointer": 0x9010, "storage_size": 0x16},
            ])

    def test_rejects_header_past_memory_end(self):
        with self.assertRaises(ValueError):
            record(bytearray(0x10000), 0xFFFF)


if __name__ == "__main__":
    unittest.main()
