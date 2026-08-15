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

    def test_multi_argument_templates_wait_at_slot_transitions(self) -> None:
        integral = FUZZ.emit((
            "int", ("num", "1"), ("num", "2"),
            ("var", "X"), ("var", "A"),
        ))
        self.assertEqual(integral[:3], ["MATH", "9", "WAIT"])
        self.assertEqual(integral.count("WAIT"), 5)
        summation = FUZZ.emit((
            "sum", ("var", "N"), ("num", "1"),
            ("num", "3"), ("var", "N"),
        ))
        self.assertEqual(summation[:3], ["MATH", "0", "WAIT"])
        self.assertEqual(summation.count("WAIT"), 5)

    def test_nested_power_base_retains_explicit_group(self) -> None:
        ast = (
            "pow", ("pow", ("var", "X"), ("num", "2")),
            ("var", "N"),
        )
        self.assertEqual(FUZZ.to_expr(ast), "(X^2)^N")
        self.assertEqual(FUZZ.to_spec(ast)["base"]["kind"], "group")
        self.assertEqual(FUZZ.emit(ast)[:1], ["LPAREN"])


if __name__ == "__main__":
    unittest.main()
