"""Unit tests for MathPrint differential-fuzzer input construction."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).with_name("fuzz-mathprint-diff.py")
SPEC = importlib.util.spec_from_file_location("fuzz_mathprint_diff", MODULE)
assert SPEC is not None and SPEC.loader is not None
FUZZ = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FUZZ)


class InputEmitterTests(unittest.TestCase):
    def test_integral_waits_for_template_completion(self) -> None:
        ast = (
            "sub",
            ("int", ("num", "1"), ("num", "3"),
             ("var", "X"), ("var", "A")),
            ("var", "N"),
        )
        keys = FUZZ.emit(ast)
        self.assertIn(["ALPHA", "MATH", "WAIT", "SUB"], [
            keys[index:index + 4] for index in range(len(keys) - 3)
        ])


if __name__ == "__main__":
    unittest.main()
