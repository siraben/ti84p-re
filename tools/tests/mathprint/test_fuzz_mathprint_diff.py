"""Unit tests for MathPrint differential-fuzzer input construction."""

from __future__ import annotations

import json
import random
import unittest

from ti84re.mathprint import fuzz_diff as FUZZ
from ti84re.paths import ORACLES


DEPTH_ORACLE = json.loads(
    (ORACLES / "mathprint/mathprint-depth-limit-oracle.json").read_text())


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

    def test_vertical_viewport_case_is_tall_but_entry_valid(self) -> None:
        ast = FUZZ.CURATED["vertical_viewport"]

        self.assertEqual(FUZZ.calculator_structural_depth(ast), 4)
        self.assertEqual(
            FUZZ.to_expr(ast),
            "1//1//1//1//1//1//1//1//1//1//1//1//1//1//1//1",
        )
        self.assertEqual(FUZZ.show_ast(ast).count("sdiv("), 15)
        self.assertEqual(FUZZ.emit(ast).count("ALPHA"), 15)
        self.assertEqual(FUZZ.emit(ast).count("YEQU"), 15)

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

    def test_generic_function_frame_maps_tokens_and_keys(self) -> None:
        ast = ("sin", ("sqrt", ("var", "X")))
        self.assertEqual(FUZZ.to_expr(ast), "sin(sqrt(X))")
        self.assertEqual(FUZZ.to_spec(ast), {
            "kind": "sequence",
            "parts": [
                [0xC2],
                {"kind": "radical", "radicand": [0x58]},
                [0x11],
            ],
        })
        self.assertEqual(
            FUZZ.emit(ast),
            ["SIN", "2ND", "SQUARE", "GRAPHVAR", "RIGHT", "RPAREN"],
        )
        self.assertEqual(FUZZ.calculator_structural_depth(ast), 1)

    def test_function_only_generator_keeps_function_at_root(self) -> None:
        previous = FUZZ.FUNCTION_ONLY
        FUZZ.FUNCTION_ONLY = True
        try:
            asts, _rejected = FUZZ.gen_comparable_asts(
                random.Random(917), 4, 30)
        finally:
            FUZZ.FUNCTION_ONLY = previous
        self.assertTrue(all(ast[0] in FUZZ.FUNCTION_KINDS for ast in asts))

    def test_matrix_literal_maps_ast_tokens_and_keys(self) -> None:
        ast = (
            "matrix2x2",
            ("sqrt", ("num", "2")),
            ("pow", ("num", "2"), ("num", "2")),
            ("num", "3"), ("num", "1"),
        )
        self.assertEqual(
            FUZZ.to_expr(ast), "matrix(2,2,sqrt(2),2^2,3,1)")
        self.assertEqual(FUZZ.to_spec(ast), {
            "kind": "matrix", "rows": 2, "columns": 2,
            "elements": [
                {"kind": "radical", "radicand": [0x32]},
                {"kind": "power", "base": [0x32],
                 "exponent": [0x32]},
                [0x33], [0x31],
            ],
        })
        self.assertEqual(FUZZ.calculator_structural_depth(ast), 1)
        self.assertEqual(FUZZ.emit(ast), [
            "2ND", "MUL", "2ND", "MUL",
            "2ND", "SQUARE", "2", "RIGHT", "COMMA",
            "2", "POWER", "2", "RIGHT",
            "2ND", "SUB", "2ND", "MUL",
            "3", "COMMA", "1",
            "2ND", "SUB", "2ND", "SUB",
        ])

    def test_list_literal_maps_ast_tokens_and_keys(self) -> None:
        ast = (
            "list", ("sqrt", ("num", "2")),
            ("sub", ("var", "A"), ("num", "1")),
        )
        self.assertEqual(FUZZ.to_expr(ast), "{sqrt(2),A-1}")
        self.assertEqual(FUZZ.to_spec(ast), {
            "kind": "list",
            "elements": [
                {"kind": "radical", "radicand": [0x32]},
                {"kind": "sequence", "parts": [
                    [0x41], [0x71], [0x31],
                ]},
            ],
        })
        self.assertEqual(FUZZ.emit(ast), [
            "2ND", "LPAREN", "2ND", "SQUARE", "2", "RIGHT",
            "COMMA", "ALPHA", "MATH", "SUB", "1", "2ND", "RPAREN",
        ])
        self.assertEqual(FUZZ.calculator_structural_depth(ast), 1)

    def test_list_only_generator_keeps_literals_at_the_root(self) -> None:
        previous = FUZZ.LIST_ONLY
        FUZZ.LIST_ONLY = True
        try:
            asts, _rejected = FUZZ.gen_comparable_asts(
                random.Random(13), 3, 20)
        finally:
            FUZZ.LIST_ONLY = previous
        self.assertTrue(all(ast[0] == "list" for ast in asts))

    def test_matrix_generator_keeps_cells_evaluable(self) -> None:
        for seed in range(30):
            cell = FUZZ.gen_matrix_element(random.Random(seed), 3)
            self.assertNotIn("var(", FUZZ.show_ast(cell))
            self.assertNotIn("matrix", FUZZ.show_ast(cell))

    def test_matrix_only_generator_keeps_literals_at_the_root(self) -> None:
        previous = FUZZ.MATRIX_ONLY
        FUZZ.MATRIX_ONLY = True
        try:
            asts, _rejected = FUZZ.gen_comparable_asts(
                random.Random(814), 3, 20)
        finally:
            FUZZ.MATRIX_ONLY = previous
        self.assertTrue(all(ast[0] in FUZZ.MATRIX_SHAPES for ast in asts))


if __name__ == "__main__":
    unittest.main()
