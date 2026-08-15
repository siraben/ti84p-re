"""Unit tests for calculator-side MathPrint bitmap normalization."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).with_name("parity-mathprint.py")
SPEC = importlib.util.spec_from_file_location("parity_mathprint", MODULE)
assert SPEC is not None and SPEC.loader is not None
PARITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARITY)


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


if __name__ == "__main__":
    unittest.main()
