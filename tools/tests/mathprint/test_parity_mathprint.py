"""Unit tests for calculator-side MathPrint bitmap normalization."""

from __future__ import annotations

import unittest

from ti84re.mathprint import parity as PARITY


class StripCursorTests(unittest.TestCase):
    def grid_with_cursor(self, height: int) -> list[list[int]]:
        grid = [[0] * 24 for _ in range(12)]
        grid[3][2] = 1
        grid[4][3] = 1
        for y in range(2, 2 + height):
            for x in range(17, 22):
                grid[y][x] = 1
        return grid

    def test_removes_five_row_cursor(self) -> None:
        self.assertEqual(
            PARITY.strip_cursor(self.grid_with_cursor(5)),
            [[1, 0], [0, 1]],
        )

    def test_removes_six_row_cursor(self) -> None:
        self.assertEqual(
            PARITY.strip_cursor(self.grid_with_cursor(6)),
            [[1, 0], [0, 1]],
        )

    def test_keeps_two_column_glyph(self) -> None:
        grid = [[0] * 12 for _ in range(10)]
        for y in range(2, 9):
            grid[y][8] = grid[y][9] = 1
        self.assertEqual(PARITY.strip_cursor(grid), grid)

    def test_removes_template_exit_cursor(self) -> None:
        grid = [[0] * 24 for _ in range(12)]
        grid[3][2] = 1
        grid[4][3] = 1
        for x in range(17, 22):
            grid[5][x] = grid[6][x] = 1
        for x in range(18, 22):
            grid[7][x] = 1
        self.assertEqual(PARITY.strip_cursor(grid), [[1, 0], [0, 1]])

    def test_keeps_template_shape_without_separator(self) -> None:
        grid = [[0] * 16 for _ in range(10)]
        grid[4][8] = 1
        for x in range(9, 14):
            grid[3][x] = grid[4][x] = 1
        for x in range(10, 14):
            grid[5][x] = 1
        self.assertEqual(PARITY.strip_cursor(grid), grid)


class HistoryCropTests(unittest.TestCase):
    def test_top_block_preserves_a_wide_internal_gap(self) -> None:
        grid = [[0] * 30 for _ in range(8)]
        grid[0][1] = grid[1][1] = 1
        grid[0][15] = grid[1][15] = 1
        grid[5][2] = 1
        self.assertEqual(PARITY.crop_echo(grid), [[1], [1]])
        self.assertEqual(PARITY.crop_top_block(grid), [
            [1] + [0] * 13 + [1],
            [1] + [0] * 13 + [1],
        ])

    def test_expected_extent_overrides_dense_history_heuristics(self) -> None:
        grid = [[0] * 30 for _ in range(12)]
        for y in range(6):
            for x in range(20):
                grid[y][x] = 1
        self.assertEqual(
            PARITY.crop_expected_history(grid, (20, 6)),
            [[1] * 20 for _ in range(6)],
        )

    def test_expected_extent_rejects_clipped_history(self) -> None:
        grid = [[0] * 20 for _ in range(8)]
        grid[0][0] = grid[5][19] = 1
        with self.assertRaisesRegex(RuntimeError, "clipped or incomplete"):
            PARITY.crop_expected_history(grid, (20, 7))


class SettledProgramTests(unittest.TestCase):
    @staticmethod
    def put_word(memory: bytearray, address: int, value: int) -> None:
        offset = address - 0x8000
        memory[offset:offset + 2] = value.to_bytes(2, "little")

    def test_decodes_final_arena_expression(self) -> None:
        memory = bytearray(0x8000)

        # Type-1Fh root wrapper: ID 6, child ID 7.
        root = bytearray(22)
        root[0:2] = (6).to_bytes(2, "little")
        root[2] = 0x1F
        root[20:22] = (7).to_bytes(2, "little")
        memory[0x1000:0x1016] = root
        # Leaf ID 7 with the native program 1 * 2.
        leaf = bytearray(19)
        leaf[0:2] = (7).to_bytes(2, "little")
        # The calculator leaves +11h zero for a top-level token-only leaf; the
        # live editor gap buffer supplies its payload.
        leaf[0x11:0x13] = (0).to_bytes(2, "little")
        memory[0x1016:0x1029] = leaf
        memory[0x1029:0x102C] = b"\x31\x82\x32"
        self.put_word(memory, 0x8DAF, 0x9000)
        self.put_word(memory, 0x8DBC, 0x9016)
        self.put_word(memory, 0x8DBE, 0x9029)
        self.put_word(memory, 0x8DB1, 0xFC45)
        self.put_word(memory, 0x8DC2, 0x9016)
        memory[0x89F1 - 0x8000] = 0x04
        self.put_word(memory, 0x96F4, 0x9029)
        self.put_word(memory, 0x96F6, 0x902C)
        self.put_word(memory, 0x96F8, 0xFC45)
        self.put_word(memory, 0x96FA, 0xFC45)

        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile() as stream:
            stream.write(memory)
            stream.flush()
            self.assertEqual(
                PARITY.calculator_settled_program(stream.name)["expression"],
                [0x31, 0x82, 0x32],
            )

    def test_matrix_size_includes_allocator_extra_slot(self) -> None:
        memory = bytearray(0x8000)
        pointer = 0x9000

        root = bytearray(22)
        root[0:2] = (6).to_bytes(2, "little")
        root[2] = 0x1F
        root[20:22] = (7).to_bytes(2, "little")
        memory[pointer - 0x8000:pointer - 0x8000 + len(root)] = root
        pointer += len(root)

        matrix = bytearray(24)
        matrix[0:2] = (8).to_bytes(2, "little")
        matrix[2] = 0x2B
        matrix[0x11:0x13] = (0x0101).to_bytes(2, "little")
        matrix[0x13] = 1
        matrix[0x14:0x16] = (9).to_bytes(2, "little")
        matrix[0x16:0x18] = b"\x00\x00"
        memory[pointer - 0x8000:pointer - 0x8000 + len(matrix)] = matrix
        pointer += len(matrix)

        entry_pointer = pointer
        entry = bytearray(25)
        entry[0:2] = (7).to_bytes(2, "little")
        entry[0x11:0x13] = (6).to_bytes(2, "little")
        entry[0x13:0x19] = b"\xEF\x2B\x08\x00\xEF\x2D"
        memory[pointer - 0x8000:pointer - 0x8000 + len(entry)] = entry
        pointer += len(entry)

        element = bytearray(20)
        element[0:2] = (9).to_bytes(2, "little")
        element[0x11:0x13] = (1).to_bytes(2, "little")
        element[0x13] = 0x31
        memory[pointer - 0x8000:pointer - 0x8000 + len(element)] = element
        pointer += len(element)

        self.put_word(memory, 0x8DAF, 0x9000)
        self.put_word(memory, 0x8DBC, entry_pointer)
        self.put_word(memory, 0x8DBE, pointer)

        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile() as stream:
            stream.write(memory)
            stream.flush()
            self.assertEqual(
                PARITY.calculator_settled_program(stream.name)["expression"],
                {"kind": "matrix", "rows": 1, "columns": 1,
                 "elements": [[0x31]]},
            )

    def test_rejects_entry_outside_arena(self) -> None:
        memory = bytearray(0x8000)
        self.put_word(memory, 0x8DAF, 0x9000)
        self.put_word(memory, 0x8DBC, 0x9020)
        self.put_word(memory, 0x8DBE, 0x9010)

        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile() as stream:
            stream.write(memory)
            stream.flush()
            with self.assertRaisesRegex(ValueError, "graph pointers"):
                PARITY.calculator_settled_program(stream.name)


if __name__ == "__main__":
    unittest.main()
