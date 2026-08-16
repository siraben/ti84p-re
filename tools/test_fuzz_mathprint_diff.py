"""Unit tests for MathPrint differential-fuzzer input construction."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import random
import unittest


MODULE = Path(__file__).with_name("fuzz-mathprint-diff.py")
SPEC = importlib.util.spec_from_file_location("fuzz_mathprint_diff", MODULE)
assert SPEC is not None and SPEC.loader is not None
FUZZ = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FUZZ)
DEPTH_ORACLE = json.loads(
    Path(__file__).with_name("mathprint-depth-limit-oracle.json").read_text())


class InputEmitterTests(unittest.TestCase):
    def test_structural_depth_counts_records_not_token_groups(self) -> None:
        ast = (
            "add",
            ("paren", ("mul", ("num", "1"), ("var", "X"))),
            ("sqrt", ("abs", ("pow", ("var", "A"), ("num", "2")))),
        )
        self.assertEqual(FUZZ.calculator_structural_depth(ast), 3)

    def test_every_entry_boundary_pair_straddles_the_rom_limit(self) -> None:
        cases = FUZZ.structural_depth_boundary_cases()
        self.assertEqual(len(cases), 11)
        self.assertEqual(len({name for name, _accepted, _rejected in cases}), 11)
        self.assertEqual(
            [name for name, _accepted, _rejected in cases],
            DEPTH_ORACLE["constructor_matrix"]["constructors"],
        )
        for name, accepted, rejected in cases:
            with self.subTest(name=name):
                self.assertEqual(FUZZ.calculator_structural_depth(accepted), 4)
                self.assertEqual(FUZZ.calculator_structural_depth(rejected), 5)

    def test_comparable_generator_filters_only_calculator_entry_depth(self) -> None:
        asts, rejected = FUZZ.gen_comparable_asts(
            random.Random(606), 5, 20, max_structural_depth=4)
        self.assertEqual(len(asts), 20)
        self.assertTrue(all(
            FUZZ.calculator_structural_depth(ast) <= 4 for ast in asts))
        self.assertGreater(rejected, 0)

    def test_input_retries_include_the_observed_very_slow_cadence(self) -> None:
        self.assertEqual(FUZZ.CALCULATOR_INPUT_CADENCES, (
            (0.1, 0.0), (0.16, 0.03), (0.24, 0.12),
        ))

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

    def test_nderiv_reorders_the_variable_slot_for_calculator_entry(self) -> None:
        ast = (
            "nderiv", ("pow", ("var", "X"), ("num", "2")),
            ("var", "A"), ("add", ("num", "1"), ("num", "2")),
        )
        self.assertEqual(FUZZ.to_expr(ast), "nDeriv(X^2,A,1+2)")
        spec = FUZZ.to_spec(ast)
        self.assertEqual(spec["kind"], "nDeriv")
        self.assertEqual(spec["variable"], [0x41])
        keys = FUZZ.emit(ast)
        self.assertEqual(keys[:3], ["MATH", "8", "WAIT"])
        self.assertEqual(keys[3:6], ["ALPHA", "MATH", "WAIT"])
        self.assertEqual(keys[-2:], ["RIGHT", "WAIT"])

    def test_exponential_and_logbase_templates_map_to_structural_specs(self) -> None:
        epow = ("epow", ("var", "X"))
        tenpow = ("tenpow", ("num", "2"))
        logbase = ("logbase", ("num", "3"), ("var", "N"))
        self.assertEqual(FUZZ.to_spec(epow), {
            "kind": "ePower", "exponent": [0x58],
        })
        self.assertEqual(FUZZ.to_spec(tenpow), {
            "kind": "tenPower", "exponent": [0x32],
        })
        self.assertEqual(FUZZ.to_spec(logbase), {
            "kind": "logBase", "base": [0x33], "argument": [0x4E],
        })
        self.assertEqual(FUZZ.emit(epow)[:3], ["2ND", "LN", "WAIT"])
        self.assertEqual(FUZZ.emit(tenpow)[:3], ["2ND", "LOG", "WAIT"])
        self.assertEqual(
            FUZZ.emit(logbase)[:4], ["MATH", "ALPHA", "MATH", "WAIT"])


if __name__ == "__main__":
    unittest.main()
