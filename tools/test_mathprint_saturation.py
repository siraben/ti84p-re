#!/usr/bin/env python3
"""Regression tests for the scoped MathPrint saturation audit."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from analyze_mathprint_saturation import (
    Branch,
    OUTCOME_CLASSIFICATIONS,
    branch_json,
    branch_for,
    classify_outcome,
    deserialize_trace_summary,
    exact_cover_z3,
    iter_oracle_cases,
    oracle_coverage,
    predicate_state,
    serialize_trace_summary,
    scan_kind_path,
    minimize_trace_corpus,
    metric_marker_callers,
    metric_marker_path,
    minimize_trace_features,
    symbolic_metric_marker_paths,
    symbolic_scan_kind_paths,
    symbolic_type1f_paths,
    type1f_entry_abis,
    type1f_path,
    type1f_terminal,
    trace_dynamic_features,
    validate_trace_provenance,
    TRACE_PROVENANCE_NATURAL,
    TRACE_PROVENANCE_SYNTHETIC,
)
from rom_image import RomImage, RomLocation
from z80_disassembly import Z80Instruction


class StaticBranchTests(unittest.TestCase):
    def test_decodes_signed_relative_target(self) -> None:
        branch = branch_for(
            Z80Instruction(RomLocation(0x34, 0x5000), b"\x20\xFC", "jr nz,$-2")
        )

        self.assertIsNotNone(branch)
        assert branch is not None
        self.assertEqual(RomLocation(0x34, 0x4FFE), branch.target)
        self.assertEqual(RomLocation(0x34, 0x5002), branch.fallthrough)

    def test_classifies_taken_and_fallthrough_next_pcs(self) -> None:
        branch = Branch(
            RomLocation(0x34, 0x5000), "jr z,$+4", "jr",
            RomLocation(0x34, 0x5006), RomLocation(0x34, 0x5002),
        )

        self.assertEqual("taken", classify_outcome(branch, ("page_34", 0x5006)))
        self.assertEqual(
            "fallthrough", classify_outcome(branch, ("page_34", 0x5002))
        )
        self.assertIsNone(classify_outcome(branch, ("page_01", 0x6297)))

    def test_interrupt_entry_uses_preserved_branch_predicate(self) -> None:
        branch = Branch(
            RomLocation(0x34, 0x5000), "jr nz,$+4", "jr",
            RomLocation(0x34, 0x5006), RomLocation(0x34, 0x5002),
        )

        self.assertEqual(
            "taken",
            classify_outcome(
                branch, ("ram", 0x0038),
                {"F": 0x00, "BC": 0}, {"F": 0x00, "BC": 0},
            ),
        )
        self.assertEqual(
            "fallthrough",
            classify_outcome(
                branch, ("ram", 0x0038),
                {"F": 0x40, "BC": 0}, {"F": 0x40, "BC": 0},
            ),
        )

    def test_conditional_return_uses_post_instruction_flags(self) -> None:
        branch = Branch(
            RomLocation(0x34, 0x5000), "ret z", "ret", None,
            RomLocation(0x34, 0x5001),
        )

        self.assertEqual(
            "returned",
            classify_outcome(
                branch, ("page_34", 0x6000),
                {"F": 0x40, "SP": 0x9002}, {"F": 0x40, "SP": 0x9002},
            ),
        )
        self.assertIsNone(
            classify_outcome(
                branch, ("page_01", 0x6297),
                {"F": 0x00, "SP": 0x9000}, {"F": 0x00, "SP": 0x9000},
            )
        )

    def test_projects_flag_and_djnz_predicate_state(self) -> None:
        flag_branch = Branch(
            RomLocation(0x34, 0x5000), "jr z,0x5006", "jr",
            RomLocation(0x34, 0x5006), RomLocation(0x34, 0x5002),
        )
        loop_branch = Branch(
            RomLocation(0x34, 0x5010), "djnz 0x5010", "djnz",
            RomLocation(0x34, 0x5010), RomLocation(0x34, 0x5012),
        )

        self.assertEqual(
            {"Z": 1, "predicate": True},
            predicate_state(flag_branch, {"F": 0x40, "BC": 0}),
        )
        self.assertEqual(
            {"B_before": 1, "B_after": 0, "predicate": False},
            predicate_state(loop_branch, {"F": 0, "BC": 0x0000}),
        )

    def test_branch_report_keeps_unobserved_status_explicit(self) -> None:
        branch = Branch(
            RomLocation(0x33, 0x4F4E), "jr nz,0x4f51", "jr",
            RomLocation(0x33, 0x4F51), RomLocation(0x33, 0x4F50),
        )
        report = branch_json(
            branch,
            Counter({("page_33", 0x4F4E, "taken"): 1}),
            {},
            OUTCOME_CLASSIFICATIONS,
        )

        self.assertEqual(
            ["exercised", "infeasible_under_entry_invariant"],
            [row["status"] for row in report["outcomes"]],
        )

    def test_calculator_abi_classifies_seeded_b_outcomes(self) -> None:
        call = Branch(
            RomLocation(0x34, 0x73CD), "call z,0x7547", "call",
            RomLocation(0x34, 0x7547), RomLocation(0x34, 0x73D0),
        )
        ret = Branch(
            RomLocation(0x34, 0x765D), "ret nz", "ret", None,
            RomLocation(0x34, 0x765E),
        )

        call_report = branch_json(
            call, Counter({("page_34", 0x73CD, "taken"): 1}), {},
            OUTCOME_CLASSIFICATIONS,
        )
        ret_report = branch_json(
            ret, Counter({("page_34", 0x765D, "fallthrough"): 1}), {},
            OUTCOME_CLASSIFICATIONS,
        )

        self.assertEqual(
            "infeasible_under_calculator_abi", call_report["outcomes"][1]["status"]
        )
        self.assertEqual(
            "infeasible_under_calculator_abi", ret_report["outcomes"][0]["status"]
        )


class SymbolicHandlerTests(unittest.TestCase):
    def test_scan_kind_partition_covers_every_byte(self) -> None:
        paths = symbolic_scan_kind_paths()

        self.assertEqual(0x100, sum(row["projected_input_count"] for row in paths))
        self.assertEqual(
            {
                "generic_scan", "raised_operand_scan", "fraction_operand_scan",
                "single_argument_scan", "multi_argument_scan",
                "kind_5_scan", "kind_6_or_greater_scan",
            },
            {row["terminal"] for row in paths},
        )
        self.assertEqual("fraction_operand_scan", scan_kind_path(2)["terminal"])
        self.assertIn("34:5680:taken", scan_kind_path(2)["branch_outcomes"])

    def test_type1f_word_boundaries_partition_both_iy_states(self) -> None:
        self.assertEqual(
            "bitmap_61C7_clear_iy_minus1_bit0", type1f_terminal(0x2B, 0, 5)
        )
        self.assertEqual(
            "glyph_7C_set_iy32_bit2", type1f_terminal(0x2B, 0, 6)
        )
        self.assertEqual("glyph_C1", type1f_terminal(0x2B, 1, 7))
        self.assertEqual(
            "glyph_7C_set_iy32_bit2", type1f_terminal(0x2B, 1, 8)
        )

    def test_type1f_symbolic_classes_keep_every_terminal(self) -> None:
        terminals = {row["terminal"] for row in symbolic_type1f_paths()}
        self.assertEqual(
            {
                "bitmap_61BE", "bitmap_61C7_clear_iy_minus1_bit0",
                "bitmap_6304", "bitmap_630C", "glyph_1D_set_iy32_bit2",
                "glyph_6C", "glyph_7C_set_iy32_bit2", "glyph_C1",
                "glyph_C6", "glyph_DB_set_iy32_bit2",
            },
            terminals,
        )

    def test_type1f_partition_preserves_distinct_branch_paths(self) -> None:
        radical = type1f_path(0x27, 1, 0)
        default = type1f_path(0x43, 0, 0)

        self.assertEqual("bitmap_630C", radical["terminal"])
        self.assertEqual(
            ["34:6145:fallthrough", "34:614E:taken"],
            radical["branch_outcomes"],
        )
        self.assertEqual("bitmap_61BE", default["terminal"])
        self.assertIn("34:61AB:fallthrough", default["branch_outcomes"])

    def test_type1f_entry_abis_separate_table_and_editor_origins(self) -> None:
        data = bytearray(0x35 * 0x4000)
        data[0x0033:0x0038] = bytes.fromhex("7E23666FC9")
        data[0x30BD:0x30C3] = bytes.fromhex("CD092B436174")
        page_06 = 0x06 * 0x4000
        data[page_06 + 0x3F29:page_06 + 0x3F31] = bytes.fromhex(
            "2AF896237ECD"
        ) + b"\x00\x00"
        page_34 = 0x34 * 0x4000
        data[page_34 + 0x2119:page_34 + 0x211B] = bytes.fromhex("4361")
        rom = RomImage(bytes(data))
        witnesses = {
            ("page_34", 0x6145, "fallthrough"): {
                "trace": "radical", "instruction_index": 10,
                "state": {"A": 0x27},
            },
            ("page_34", 0x614E, "taken"): {
                "trace": "radical", "instruction_index": 13,
                "state": {"A": 0x27},
            },
            ("page_34", 0x6145, "taken"): {
                "trace": "integral", "instruction_index": 20,
                "state": {"A": 0x22},
            },
            ("page_34", 0x6157, "fallthrough"): {
                "trace": "integral", "instruction_index": 22,
                "state": {"A": 0x22},
            },
            ("page_34", 0x6166, "taken"): {
                "trace": "absolute", "instruction_index": 30,
                "state": {"A": 0x21},
            },
        }

        table, editor = type1f_entry_abis(rom, Counter(), witnesses)
        self.assertEqual("0x43", table["incoming_A"])
        self.assertEqual("bitmap_61BE", table["terminal"])
        self.assertEqual([], table["state_dependencies"])
        self.assertEqual("byte at editTail + 1", editor["incoming_A"])
        self.assertEqual(
            [0x27, 0x22, 0x21],
            [row["A"] for row in editor["observed_entry_states"]],
        )
        self.assertEqual(
            3,
            sum(row["dynamic_path_observed"] for row in editor["path_classes"]),
        )
        self.assertTrue(all(
            row["entry_path_status"] == "rom_fixed"
            for row in table["path_classes"]
        ))

    def test_type1f_partition_counts_the_complete_projected_domain(self) -> None:
        paths = symbolic_type1f_paths()

        self.assertEqual(
            0x100 * 2 * 0x10000,
            sum(row["projected_input_count"] for row in paths),
        )

    def test_symbolic_paths_report_dynamic_outcome_gaps(self) -> None:
        observed = Counter({
            ("page_34", 0x6145, "fallthrough"): 1,
            ("page_34", 0x614E, "taken"): 1,
        })
        radical = next(
            row for row in symbolic_type1f_paths((0x27,), observed)
            if row["terminal"] == "bitmap_630C"
        )

        self.assertEqual(
            "all_outcomes_observed",
            radical["branch_outcome_coverage"]["status"],
        )
        self.assertEqual(
            [], radical["branch_outcome_coverage"]["unresolved_outcomes"]
        )

    def test_metric_marker_gate_distinguishes_all_local_outcomes(self) -> None:
        self.assertEqual(
            "return_nz_pointer_mismatch",
            metric_marker_path(0, 0, "other", 0)["terminal"],
        )
        self.assertEqual(
            "return_nz_yequ_table",
            metric_marker_path(1, 1, "fraction_nthroot_power", 0)["terminal"],
        )
        self.assertEqual(
            "return_nz_other_marker",
            metric_marker_path(1, 0, "other", 0)["terminal"],
        )
        nested = metric_marker_path(1, 0, "fraction_nthroot_power", 1)
        self.assertEqual("return_z_special_marker_nested", nested["terminal"])
        self.assertIn("34:75BB:fallthrough", nested["branch_outcomes"])

    def test_metric_marker_partition_contains_every_branch_outcome(self) -> None:
        outcomes = {
            outcome
            for row in symbolic_metric_marker_paths()
            for outcome in row["branch_outcomes"]
        }
        self.assertEqual(
            {
                "34:75A5:returned", "34:75A5:fallthrough",
                "34:75A9:taken", "34:75A9:fallthrough",
                "34:75B0:taken", "34:75B0:fallthrough",
                "34:75BB:taken", "34:75BB:fallthrough",
            },
            outcomes,
        )
        self.assertEqual(
            16,
            sum(row["predicate_valuation_count"] for row in symbolic_metric_marker_paths()),
        )

    def test_metric_callee_paths_exclude_caller_continuations(self) -> None:
        for row in symbolic_metric_marker_paths():
            self.assertFalse(any(
                outcome.startswith("34:755F:") or outcome.startswith("34:6FC9:")
                for outcome in row["branch_outcomes"]
            ))

        callers = metric_marker_callers(Counter({
            ("page_34", 0x755F, "taken"): 1,
            ("page_34", 0x6FC9, "fallthrough"): 1,
        }))
        self.assertEqual(["taken"], callers[0]["observed_continuation_outcomes"])
        self.assertEqual(["fallthrough"], callers[1]["observed_continuation_outcomes"])

    def test_editor_helper_domain_includes_exceptional_marker(self) -> None:
        data = bytearray(0x35 * 0x4000)
        data[0x0033:0x0038] = bytes.fromhex("7E23666FC9")
        data[0x30BD:0x30C3] = bytes.fromhex("CD092B436174")
        page_06 = 0x06 * 0x4000
        data[page_06 + 0x3F29:page_06 + 0x3F31] = bytes.fromhex(
            "2AF896237ECD"
        ) + b"\x00\x00"
        page_34 = 0x34 * 0x4000
        data[page_34 + 0x2119:page_34 + 0x211B] = bytes.fromhex("4361")
        _table, editor = type1f_entry_abis(RomImage(bytes(data)), Counter(), {})

        self.assertIn("0x2C", editor["entry_domain"]["incoming_A"])
        self.assertEqual(
            14 * 2 * 0x10000,
            editor["entry_domain"]["projected_input_domain"],
        )

    def test_metric_path_witnesses_use_exclusive_outcomes(self) -> None:
        observed = Counter({
            ("page_34", 0x75A5, "returned"): 1,
            ("page_34", 0x75BB, "taken"): 1,
        })
        paths = symbolic_metric_marker_paths(observed)

        self.assertEqual(
            {"return_nz_pointer_mismatch", "return_z_special_marker_top_level"},
            {row["terminal"] for row in paths if row["dynamic_path_observed"]},
        )


class OracleCoverageTests(unittest.TestCase):
    def test_feature_minimum_preserves_tagged_state_and_path_features(self) -> None:
        report = minimize_trace_features(
            {
                "alpha": {"branch_outcome:34:5000:taken", "entry_state:A=1"},
                "beta": {"branch_outcome:34:5000:taken"},
                "gamma": {"entry_state:A=1"},
            },
            {"alpha": 30, "beta": 10, "gamma": 10},
        )

        self.assertEqual(1, report["selected_trace_count"])
        self.assertEqual(["alpha"], [row["label"] for row in report["selected"]])
        self.assertEqual(
            {"branch_outcome": 1, "entry_state": 1},
            report["feature_kind_counts"],
        )

    def test_trace_features_keep_modeled_scan_and_helper_states(self) -> None:
        outcomes = {
            ("page_34", 0x5680, "taken"),
            ("page_34", 0x616C, "taken"),
        }
        features = trace_dynamic_features(outcomes, {
            ("page_34", 0x616C, "taken"): {"state": {"A": 0x25}},
        })

        self.assertIn("modeled_path:34:5678:fraction_operand_scan", features)
        self.assertIn("entry_state:34:6143:A=0x25", features)
        self.assertIn(
            "modeled_path:34:6143:A=0x25:bit3=0:glyph_DB_set_iy32_bit2",
            features,
        )

    def test_finds_nested_case_lists_and_counts_record_types(self) -> None:
        document = {
            "schema": 1,
            "first_cases": [
                {"expression": "X", "nodes": [{"render_type": 0}]},
                {"expression": "X^2", "nodes": [
                    {"render_type": 0}, {"render_type": 0x2A},
                ]},
            ],
            "metadata": [1, 2, 3],
        }
        self.assertEqual(2, len(tuple(iter_oracle_cases(document))))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oracles.json"
            path.write_text(json.dumps(document))
            report = oracle_coverage((path,))

        self.assertEqual(2, report["cases"])
        self.assertEqual(2, report["unique_expressions"])
        self.assertEqual({"0x00": 2, "0x2A": 1}, report["record_types"])

    def test_minimizes_trace_outcomes_deterministically(self) -> None:
        a = ("page_34", 0x5000, "taken")
        b = ("page_34", 0x5000, "fallthrough")
        c = ("page_34", 0x5010, "taken")
        report = minimize_trace_corpus(
            {"alpha": {a, b}, "beta": {b, c}, "gamma": {a}},
            {"alpha": 30, "beta": 20, "gamma": 10},
        )

        self.assertEqual(2, report["selected_trace_count"])
        self.assertEqual(
            ["beta", "gamma"], [row["label"] for row in report["selected"]]
        )
        self.assertEqual(["alpha"], report["omitted"])
        self.assertEqual(30, report["selected_trace_bytes"])
        self.assertEqual(
            ["34:5000:fallthrough", "34:5010:taken"],
            report["selected"][0]["exclusive_outcome_ids"],
        )
        self.assertTrue(report["proven_minimum"])

    def test_exact_cover_beats_greedy_choice(self) -> None:
        # A largest-first greedy choice starts with alpha and needs three
        # traces.  Beta plus gamma is the unique two-trace cover.
        a = ("page_34", 0x5000, "taken")
        b = ("page_34", 0x5000, "fallthrough")
        c = ("page_34", 0x5010, "taken")
        d = ("page_34", 0x5010, "fallthrough")
        e = ("page_34", 0x5020, "taken")
        f = ("page_34", 0x5020, "fallthrough")
        report = minimize_trace_corpus({
            "alpha": {a, b, c, d},
            "beta": {a, b, e},
            "gamma": {c, d, f},
            "delta": {e},
            "epsilon": {f},
        })

        self.assertEqual(
            ["beta", "gamma"], [row["label"] for row in report["selected"]]
        )

    def test_equal_cardinality_cover_minimizes_bytes(self) -> None:
        a = ("page_34", 0x5000, "taken")
        b = ("page_34", 0x5000, "fallthrough")
        report = minimize_trace_corpus(
            {"large_a": {a}, "large_b": {b}, "small_a": {a}, "small_b": {b}},
            {"large_a": 100, "large_b": 100, "small_a": 10, "small_b": 10},
        )

        self.assertEqual(
            ["small_a", "small_b"],
            [row["label"] for row in report["selected"]],
        )

    def test_minimized_corpus_preserves_trace_provenance(self) -> None:
        natural = ("page_34", 0x5000, "taken")
        synthetic = ("page_34", 0x5000, "fallthrough")
        report = minimize_trace_corpus(
            {"keys": {natural}, "injected": {synthetic}},
            trace_provenance={
                "keys": TRACE_PROVENANCE_NATURAL,
                "injected": TRACE_PROVENANCE_SYNTHETIC,
            },
        )

        self.assertEqual(
            {
                TRACE_PROVENANCE_NATURAL: 1,
                TRACE_PROVENANCE_SYNTHETIC: 1,
            },
            report["source_trace_provenance_counts"],
        )
        self.assertEqual(
            [TRACE_PROVENANCE_SYNTHETIC, TRACE_PROVENANCE_NATURAL],
            [row["provenance"] for row in report["selected"]],
        )

    def test_memwrite_macro_cannot_default_to_natural_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "probe.trace"
            trace.touch()
            trace.with_suffix(".macro").write_text(
                "key CLEAR\nmemwrite 0x8515 01\n"
            )

            with self.assertRaisesRegex(ValueError, "classify it as"):
                validate_trace_provenance(
                    "probe", trace, TRACE_PROVENANCE_NATURAL
                )
            validate_trace_provenance(
                "probe", trace, TRACE_PROVENANCE_SYNTHETIC
            )

    @unittest.skipUnless(shutil.which("z3"), "z3 is required")
    def test_z3_cover_matches_exact_objectives(self) -> None:
        a = ("page_34", 0x5000, "taken")
        b = ("page_34", 0x5000, "fallthrough")
        c = ("page_34", 0x5010, "taken")
        outcomes = {
            "alpha": {a, b}, "beta": {b, c}, "gamma": {a}, "delta": {c},
        }

        self.assertEqual(
            ("alpha", "delta"),
            exact_cover_z3(
                sorted(outcomes), outcomes, {a, b, c},
                {"alpha": 10, "beta": 30, "gamma": 5, "delta": 5},
            ),
        )

    @unittest.skipUnless(shutil.which("z3"), "z3 is required")
    def test_z3_cover_uses_lexicographic_label_tie_break(self) -> None:
        a = ("page_34", 0x5000, "taken")
        b = ("page_34", 0x5000, "fallthrough")
        c = ("page_34", 0x5010, "taken")
        outcomes = {
            "alpha": {a}, "beta": {a, b}, "gamma": {c}, "omega": {b, c},
        }

        self.assertEqual(
            ("alpha", "omega"),
            exact_cover_z3(
                sorted(outcomes), outcomes, {a, b, c},
                {label: 1 for label in outcomes},
            ),
        )

    def test_trace_summary_round_trip_rebinds_label(self) -> None:
        outcome = ("page_34", 0x5000, "taken")
        hit = ("page_34", 0x5000)
        row = {"label": "old", "sha256": "abc", "bytes": 100}
        witness = {outcome: {
            "trace": "old", "instruction_index": 2,
            "state": {"A": 1}, "predicate_state": {"Z": 0},
        }}

        restored = deserialize_trace_summary(
            "new",
            serialize_trace_summary(row, Counter({outcome: 3}), Counter({hit: 4}), witness),
        )

        self.assertEqual("new", restored[0]["label"])
        self.assertEqual(3, restored[1][outcome])
        self.assertEqual(4, restored[2][hit])
        self.assertEqual("new", restored[3][outcome]["trace"])


if __name__ == "__main__":
    unittest.main()
