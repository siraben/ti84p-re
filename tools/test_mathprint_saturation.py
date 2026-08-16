#!/usr/bin/env python3
"""Regression tests for the scoped MathPrint saturation audit."""

from __future__ import annotations

from collections import Counter
from itertools import product
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
    cached_report_traces,
    classify_outcome,
    deserialize_trace_summary,
    editor_action03_controller_path,
    editor_action04_controller_path,
    editor_horizontal_viewport_path,
    editor_vertical_viewport_path,
    editor_vertical_cue_path,
    editor_left_overflow_cue_path,
    editor_right_overflow_cue_path,
    editor_reverse_overflow_cue_path,
    editor_saved_operand_wrapper_path,
    embedded_viewport_path,
    record_allocation_capacity_terminal_counts,
    record_allocation_capacity_path,
    exact_cover_z3,
    find_alpha_candidate_path,
    find_alpha_endpoint_path,
    find_alpha_key_preparation_path,
    find_alpha_record_step_path,
    find_alpha_type_class_path,
    glyph_viewport_path,
    iter_oracle_cases,
    oracle_coverage,
    oracle_trace_features,
    predicate_state,
    raised_classifier_caller_states,
    raised_extended_token_path,
    raised_name_loop_path,
    source_lookup_domain,
    structural_depth_gate_path,
    structural_insertion_dispatch_path,
    indexed_table_domain,
    load_trace_cache,
    routine_path_terminal,
    serialize_trace_summary,
    scan_kind_path,
    minimize_trace_corpus,
    metric_marker_callers,
    metric_marker_path,
    minimize_trace_features,
    symbolic_metric_marker_paths,
    symbolic_editor_action03_paths,
    symbolic_editor_action04_paths,
    symbolic_editor_horizontal_viewport_paths,
    symbolic_editor_vertical_viewport_paths,
    symbolic_editor_vertical_cue_paths,
    symbolic_editor_left_overflow_cue_paths,
    symbolic_editor_right_overflow_cue_paths,
    symbolic_editor_reverse_overflow_cue_paths,
    symbolic_editor_saved_operand_wrapper_paths,
    symbolic_embedded_viewport_paths,
    symbolic_find_alpha_candidate_paths,
    symbolic_find_alpha_endpoint_paths,
    symbolic_find_alpha_key_preparation_paths,
    symbolic_find_alpha_record_step_paths,
    symbolic_find_alpha_type_class_paths,
    symbolic_glyph_viewport_paths,
    symbolic_record_allocation_capacity_paths,
    symbolic_model_corpus,
    symbolic_raised_extended_token_paths,
    symbolic_raised_name_loop_paths,
    symbolic_scan_kind_paths,
    symbolic_structural_depth_gate_paths,
    symbolic_structural_insertion_dispatch_paths,
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

    def test_modeled_routine_path_terminals_match_local_exits(self) -> None:
        self.assertTrue(routine_path_terminal("34:5678", 0x5680, "taken"))
        self.assertFalse(routine_path_terminal("34:5678", 0x5680, "fallthrough"))
        self.assertTrue(routine_path_terminal("34:583D", 0x5849, "taken"))
        self.assertTrue(routine_path_terminal("34:583D", 0x5853, "fallthrough"))
        self.assertTrue(routine_path_terminal("34:6143", 0x618E, "taken"))
        self.assertTrue(routine_path_terminal("34:759C", 0x75A5, "returned"))
        self.assertFalse(routine_path_terminal("34:759C", 0x75A5, "fallthrough"))

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
    def test_editor_action_controllers_partition_every_byte_state(self) -> None:
        action03 = symbolic_editor_action03_paths()
        action04 = symbolic_editor_action04_paths()

        self.assertEqual(0x20000, sum(
            row["projected_input_count"] for row in action03
        ))
        self.assertEqual(0x20000, sum(
            row["projected_input_count"] for row in action04
        ))
        self.assertEqual(11, len(action03))
        self.assertEqual(5, len(action04))
        zero_count = editor_action03_controller_path(0, 0, 0)
        self.assertEqual(256, zero_count["iterations"])
        self.assertEqual(
            255, zero_count["branch_outcomes"].count("39:50AB:taken")
        )
        self.assertEqual("39:50AB:fallthrough", zero_count["branch_outcomes"][-1])
        self.assertEqual(
            "wide_list", editor_action03_controller_path(0, 8, 0)["terminal"]
        )
        self.assertEqual(
            "advance_once_at_or_past_last",
            editor_action04_controller_path(9, 7, 0)["terminal"],
        )
        self.assertEqual(
            "layout_argument_zero",
            editor_action04_controller_path(6, 7, 0)["terminal"],
        )

    def test_symbolic_model_corpus_minimizes_each_finite_domain(self) -> None:
        report = symbolic_model_corpus()

        self.assertEqual(1343, report["path_equivalence_class_count"])
        self.assertEqual(1343, report["representative_path_corpus_count"])
        self.assertEqual(223, report["distinct_modeled_branch_outcomes"])
        self.assertEqual(
            115, report["per_domain_minimum_branch_outcome_corpus_count"]
        )
        self.assertEqual(25, len(report["domains"]))
        for domain in report["domains"]:
            minimum = domain["minimum_branch_outcome_corpus"]
            selected_outcomes = {
                outcome
                for row in minimum["selected_classes"]
                for outcome in row["branch_outcomes"]
            }
            self.assertEqual(
                set(minimum["covered_outcomes"]), selected_outcomes
            )
            self.assertTrue(minimum["proven_minimum"])

    def test_structural_depth_gate_partitions_every_byte(self) -> None:
        paths = symbolic_structural_depth_gate_paths()

        self.assertEqual(0x100, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual({
            "preserve_a": 5,
            "return_a_03": 251,
        }, {
            row["terminal"]: row["projected_input_count"] for row in paths
        })
        self.assertEqual(
            ["35:7B42:returned"],
            structural_depth_gate_path(3)["branch_outcomes"],
        )
        rejected = structural_depth_gate_path(4)
        self.assertEqual(5, rejected["incremented_depth"])
        self.assertTrue(rejected["carry"])
        self.assertEqual(
            ["35:7B42:fallthrough"], rejected["branch_outcomes"]
        )
        self.assertEqual("preserve_a", structural_depth_gate_path(0xFF)["terminal"])

    def test_structural_insertion_dispatch_partitions_every_a_e_pair(self) -> None:
        paths = symbolic_structural_insertion_dispatch_paths()

        self.assertEqual(0x10000, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual({
            "fraction_alternate": 0xFF,
            "fraction_standard": 1,
            "matrix_dispatch": 0x100,
            "nth_root_dispatch": 0x100,
            "power_dispatch": 0x100,
            "shared_marker_dispatch": 0xFC00,
        }, {
            row["terminal"]: row["projected_input_count"] for row in paths
        })
        self.assertEqual(
            "fraction_standard",
            structural_insertion_dispatch_path(0x20, 0x2E)["terminal"],
        )
        self.assertEqual(
            "fraction_alternate",
            structural_insertion_dispatch_path(0x20, 0x2F)["terminal"],
        )
        self.assertEqual(
            "shared_marker_dispatch",
            structural_insertion_dispatch_path(0x27, 0xBC)["terminal"],
        )

    def test_reverse_overflow_cue_partitions_every_byte_pair(self) -> None:
        paths = symbolic_editor_reverse_overflow_cue_paths()

        self.assertEqual(0x10000, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(2, len(paths))
        counts = {
            row["terminal"]: row["projected_input_count"] for row in paths
        }
        self.assertEqual({
            "return": 0x800,
            "emit_window_bottom_cue": 0xF800,
        }, counts)
        self.assertEqual(
            "return", editor_reverse_overflow_cue_path(5, 12)["terminal"]
        )
        wrapped = editor_reverse_overflow_cue_path(0xFF, 0)
        self.assertEqual(1, wrapped["remaining_arguments"])
        self.assertEqual("return", wrapped["terminal"])

    def test_horizontal_viewport_partitions_words_flags_and_callers(self) -> None:
        paths = symbolic_editor_horizontal_viewport_paths()

        self.assertEqual(0x10000 * 0x10000 * 2 * 2, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(8, len(paths))
        self.assertEqual({
            "return_before_right_bound", "store_horizontal_clip",
        }, {row["terminal"] for row in paths})
        reset = editor_horizontal_viewport_path(2, 100, 1, 0)
        self.assertTrue(reset["reset_previous_clip"])
        self.assertEqual(0, reset["x_clip"])
        wrapped = editor_horizontal_viewport_path(0xFFFF, 0, 1, 0)
        self.assertEqual(5, wrapped["comparison_coordinate"])
        self.assertEqual("return_before_right_bound", wrapped["terminal"])

    def test_vertical_viewport_partitions_words_flags_and_callers(self) -> None:
        paths = symbolic_editor_vertical_viewport_paths()

        self.assertEqual(0x10000 * 0x10000 * 2 * 2, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(8, len(paths))
        self.assertEqual({
            "return_before_bottom_bound", "store_vertical_clip",
        }, {row["terminal"] for row in paths})
        reset = editor_vertical_viewport_path(2, 100, 1, 0)
        self.assertTrue(reset["reset_previous_clip"])
        self.assertEqual(0, reset["y_clip"])
        wrapped = editor_vertical_viewport_path(0xFFFF, 0, 1, 0)
        self.assertEqual(6, wrapped["comparison_coordinate"])
        self.assertEqual("return_before_bottom_bound", wrapped["terminal"])

    def test_vertical_cues_partition_height_and_clip_words(self) -> None:
        paths = symbolic_editor_vertical_cue_paths()

        self.assertEqual(0xFFFF * 0x10000, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(5, len(paths))
        self.assertEqual({
            "return_without_cue", "draw_lower_cue",
            "draw_upper_cue", "draw_both_cues",
        }, {row["terminal"] for row in paths})
        self.assertEqual(
            "return_without_cue", editor_vertical_cue_path(62, 0)["terminal"]
        )
        self.assertEqual(
            "draw_lower_cue", editor_vertical_cue_path(63, 0)["terminal"]
        )
        self.assertEqual(
            "draw_upper_cue", editor_vertical_cue_path(5, 8)["terminal"]
        )
        self.assertEqual(
            "draw_both_cues", editor_vertical_cue_path(125, 8)["terminal"]
        )

    def test_left_cue_partitions_clips_heights_and_editor_modes(self) -> None:
        paths = symbolic_editor_left_overflow_cue_paths()

        self.assertEqual(0x10000 * 0xFFFF * 0x100, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(5, len(paths))
        self.assertEqual({
            "skip_left_cue", "use_bound_for_mode_49", "use_record_height",
            "clamp_low_byte", "clamp_high_byte",
        }, {row["terminal"] for row in paths})
        self.assertEqual(
            "skip_left_cue",
            editor_left_overflow_cue_path(0, 125, 0x40)["terminal"],
        )
        self.assertEqual(
            8, editor_left_overflow_cue_path(1, 23, 0x40)["cue_y"]
        )
        self.assertEqual(
            28, editor_left_overflow_cue_path(15, 125, 0x40)["cue_y"]
        )
        self.assertEqual(
            "use_bound_for_mode_49",
            editor_left_overflow_cue_path(1, 23, 0x49)["terminal"],
        )

    def test_right_cue_partitions_width_origins_and_clips(self) -> None:
        paths = symbolic_editor_right_overflow_cue_paths()

        self.assertEqual(0x10000**3, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(5, len(paths))
        self.assertEqual({
            "width_zero", "translated_left", "translated_zero",
            "within_bound", "draw_right_cue",
        }, {row["terminal"] for row in paths})
        self.assertEqual(
            "translated_left",
            editor_right_overflow_cue_path(10, 0, 10)["terminal"],
        )
        self.assertEqual(
            "translated_zero",
            editor_right_overflow_cue_path(11, 0, 10)["terminal"],
        )
        self.assertEqual(
            "within_bound",
            editor_right_overflow_cue_path(12, 0, 10)["terminal"],
        )
        self.assertEqual(
            "draw_right_cue",
            editor_right_overflow_cue_path(107, 0, 10)["terminal"],
        )

    def test_glyph_viewport_partitions_pen_clip_words_and_advances(self) -> None:
        paths = symbolic_glyph_viewport_paths()

        self.assertEqual(0x10000**2 * 7, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(3, len(paths))
        self.assertEqual({
            "skip_left", "draw", "skip_right",
        }, {row["terminal"] for row in paths})
        self.assertEqual({
            "skip_left": 15_032_156_160,
            "draw": 44_435_706,
            "skip_right": 14_988_179_206,
        }, {
            row["terminal"]: row["projected_input_count"] for row in paths
        })
        self.assertEqual(
            "skip_left", glyph_viewport_path(0, 4, 1)["terminal"]
        )
        self.assertEqual("draw", glyph_viewport_path(92, 4, 0)["terminal"])
        self.assertEqual(
            "skip_right", glyph_viewport_path(95, 4, 0)["terminal"]
        )
        wrapped = glyph_viewport_path(0xFFFF, 1, 0)
        self.assertEqual(0, wrapped["endpoint"])
        self.assertEqual("draw", wrapped["terminal"])

    def test_embedded_viewport_partitions_endpoint_and_clip_words(self) -> None:
        paths = symbolic_embedded_viewport_paths()

        self.assertEqual(0x10000**2, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual({
            "skip_left": 2_147_450_880,
            "draw": 2_147_516_416,
        }, {
            row["terminal"]: row["projected_input_count"] for row in paths
        })
        skipped = embedded_viewport_path(56,63)
        self.assertEqual("skip_left", skipped["terminal"])
        self.assertEqual(0xFFF9, skipped["translated_endpoint"])
        self.assertEqual("draw", embedded_viewport_path(63,63)["terminal"])

    def test_record_capacity_partitions_all_word_inputs_and_gate_bit(self) -> None:
        paths = symbolic_record_allocation_capacity_paths()

        self.assertEqual(2**65, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(6, len(paths))
        self.assertEqual({
            "return_range_carry",
            "return_request_carry",
            "continue_allocation",
        }, {row["terminal"] for row in paths})
        exact = record_allocation_capacity_path(1000, 200, 100, 700, 0)
        self.assertFalse(exact["carry"])
        self.assertEqual(0, exact["remaining_bytes"])
        request_carry = record_allocation_capacity_path(
            1000, 200, 100, 701, 0
        )
        self.assertTrue(request_carry["request_borrow"])
        self.assertEqual("return_request_carry", request_carry["terminal"])
        cleared_borrow = record_allocation_capacity_path(0, 0, 1, 0xFFFF, 0)
        self.assertEqual("continue_allocation", cleared_borrow["terminal"])
        range_carry = record_allocation_capacity_path(0, 1, 0, 0, 0)
        self.assertFalse(range_carry["request_compared"])
        self.assertEqual("return_range_carry", range_carry["terminal"])

    def test_record_capacity_closed_forms_match_small_word_rings(self) -> None:
        for word_count in range(1, 8):
            expected = record_allocation_capacity_terminal_counts(word_count)
            for gate_bit in (0, 1):
                observed: Counter[str] = Counter()
                for workspace, tail, reserve, request in product(
                    range(word_count), repeat=4
                ):
                    after_reserve = (
                        workspace
                        if gate_bit
                        else (workspace - reserve) % word_count
                    )
                    if after_reserve < tail:
                        terminal = "return_range_carry"
                    elif after_reserve - tail < request:
                        terminal = "return_request_carry"
                    else:
                        terminal = "continue_allocation"
                    observed[terminal] += 1
                self.assertEqual(
                    expected,
                    {terminal: observed[terminal] for terminal in expected},
                )

    def test_saved_operand_wrappers_partition_all_predicate_states(self) -> None:
        paths = symbolic_editor_saved_operand_wrapper_paths()

        self.assertEqual(16, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(12, len(paths))
        self.assertEqual(4, sum(
            row["terminal"] == "gated_return" for row in paths
        ))
        self.assertEqual(
            "writeback_F2",
            editor_saved_operand_wrapper_path(
                "saved-F2", "down", 1, 0
            )["terminal"],
        )
        self.assertEqual(
            "search_carry",
            editor_saved_operand_wrapper_path(
                "saved-E7", "up", 1, 1
            )["terminal"],
        )

    def test_find_alpha_type_normalization_partitions_all_classes(self) -> None:
        paths = symbolic_find_alpha_type_class_paths()

        self.assertEqual(0x20, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(0x01, find_alpha_type_class_path(0x0D)["normalized_type"])
        self.assertEqual(0x05, find_alpha_type_class_path(0x06)["normalized_type"])
        self.assertEqual(0x03, find_alpha_type_class_path(0x0B)["normalized_type"])
        self.assertEqual(0, find_alpha_type_class_path(0x19)["normalized_type"])

    def test_find_alpha_key_preparation_partitions_declared_forms(self) -> None:
        paths = symbolic_find_alpha_key_preparation_paths()

        self.assertEqual(0x20 * 6, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(
            "named/list",
            find_alpha_key_preparation_path(0x01, "list_ff")["region"],
        )
        self.assertEqual(
            "fixed-token",
            find_alpha_key_preparation_path(0x0D, "fixed_72")["region"],
        )
        self.assertEqual(
            [0x5D, 0, 0, 0, 0, 0, 0, 0],
            find_alpha_key_preparation_path(0, "list_5d")["prepared_name"],
        )

    def test_find_alpha_record_stepping_partitions_type_marker_bytes(self) -> None:
        paths = symbolic_find_alpha_record_step_paths()

        self.assertEqual(0x20 * 0x100, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(
            "fixed_three_byte_marker",
            find_alpha_record_step_path(0x0D, 0x3A)["terminal"],
        )
        self.assertEqual(
            "type_09_variable_step",
            find_alpha_record_step_path(0x09, 4)["terminal"],
        )
        self.assertEqual(
            "fixed_nine_byte",
            find_alpha_record_step_path(0, 4)["terminal"],
        )

    def test_find_alpha_candidate_reducer_partitions_predicate_states(self) -> None:
        paths = symbolic_find_alpha_candidate_paths()

        self.assertEqual(288, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual(
            "select_first",
            find_alpha_candidate_path(
                "up", 1, "accepted", 0, 1, "none"
            )["terminal"],
        )
        self.assertEqual(
            "reject_source_side",
            find_alpha_candidate_path(
                "down", 1, "accepted", 1, -1, "none"
            )["terminal"],
        )
        self.assertEqual(
            "replace_best",
            find_alpha_candidate_path(
                "down", 1, "accepted", 0, -1, "candidate_nearer"
            )["terminal"],
        )

    def test_find_alpha_endpoint_covers_success_and_failure(self) -> None:
        paths = symbolic_find_alpha_endpoint_paths()

        self.assertEqual(2, sum(
            row["projected_input_count"] for row in paths
        ))
        self.assertEqual("failure_carry", find_alpha_endpoint_path(0)["terminal"])
        self.assertTrue(find_alpha_endpoint_path(0)["carry"])
        self.assertEqual(0xFE, find_alpha_endpoint_path(0)["a"])
        self.assertEqual("success", find_alpha_endpoint_path(1)["terminal"])
        self.assertFalse(find_alpha_endpoint_path(1)["carry"])
        self.assertEqual(0, find_alpha_endpoint_path(1)["a"])

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

    def test_raised_classifier_partitions_every_caller_admitted_token(self) -> None:
        paths = symbolic_raised_extended_token_paths()

        self.assertEqual(
            len(tuple(raised_classifier_caller_states())),
            sum(row["projected_input_count"] for row in paths),
        )
        self.assertEqual(3047, sum(row["projected_input_count"] for row in paths))
        self.assertEqual(
            {"advance_one_token", "bounded_name_scan_5",
             "bounded_name_scan_8", "rejected"},
            {row["terminal"] for row in paths},
        )
        self.assertEqual(
            "advance_one_token", raised_extended_token_path(0xBB, 0x31)["terminal"]
        )
        self.assertEqual(
            "rejected", raised_extended_token_path(0xBB, 0x30)["terminal"]
        )

    def test_bounded_name_loop_models_every_branch_and_stop_class(self) -> None:
        for limit, expected_paths in ((5, 125), (8, 1021)):
            paths = symbolic_raised_name_loop_paths(limit)
            self.assertEqual(expected_paths, len(paths))
            self.assertEqual(
                {"source_boundary", "non_name_below_41h",
                 "non_name_at_or_above_5ch", "byte_limit"},
                {row["stop_class"] for row in paths},
            )
            outcomes = {
                outcome for row in paths for outcome in row["branch_outcomes"]
            }
            self.assertEqual(
                {
                    "34:5840:taken", "34:5840:fallthrough",
                    "34:5845:taken", "34:5845:fallthrough",
                    "34:5849:taken", "34:5849:fallthrough",
                    "34:584D:taken", "34:584D:fallthrough",
                    "34:5853:taken", "34:5853:fallthrough",
                },
                outcomes,
            )

    def test_bounded_name_loop_keeps_digit_and_letter_paths_distinct(self) -> None:
        digit = raised_name_loop_path(("digit",), "source_boundary", 5)
        letter = raised_name_loop_path(("letter",), "source_boundary", 5)

        self.assertIn("34:5845:taken", digit["branch_outcomes"])
        self.assertNotIn("34:5849:fallthrough", digit["branch_outcomes"])
        self.assertIn("34:5845:fallthrough", letter["branch_outcomes"])
        self.assertIn("34:584D:fallthrough", letter["branch_outcomes"])
        self.assertEqual(10, digit["projected_input_count"])
        self.assertEqual(27, letter["projected_input_count"])

    def test_source_lookup_reports_shadowed_duplicate_and_no_match(self) -> None:
        rows = [
            [0x06, 0x00, 0x2B],
            [0xF0, 0x00, 0x2A],
            [0x06, 0x00, 0x2C],
        ]
        report = source_lookup_domain(rows)

        self.assertEqual(2, report["first_match_classes"])
        self.assertEqual(0x10000 - 2, report["no_match_input_count"])
        self.assertEqual("shadowed_duplicate", report["rows"][2]["lookup_status"])
        self.assertEqual(0, report["shadowed_rows"][0]["shadowed_by"])

    def test_index_domain_separates_rows_from_adjacent_bytes(self) -> None:
        data = bytes(range(0x100)) * 0x4000
        report = indexed_table_domain(
            RomImage(data), name="test", page=0, address=0x100,
            row_count=2, row_width=3, index_bias=0x1F,
        )

        self.assertEqual(2, report["valid_row_inputs"])
        self.assertEqual(254, report["adjacent_byte_inputs"])
        row = next(item for item in report["rows"]
                   if item["incoming_value"] == "0x1F")
        overread = next(item for item in report["rows"]
                        if item["incoming_value"] == "0x21")
        self.assertEqual("table_row", row["status"])
        self.assertEqual("adjacent_rom_bytes", overread["status"])

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
    def test_trace_cache_discards_noncurrent_schema_without_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            for schema in (4, 5, 7):
                path.write_text(json.dumps({
                    "schema": schema,
                    "cfg_fingerprint": "cfg",
                    "entries": {"old": {"row": {}}},
                }))

                self.assertEqual(
                    {"schema": 6, "cfg_fingerprint": "cfg", "entries": {}},
                    load_trace_cache(path, "cfg"),
                )

    def test_trace_cache_keeps_only_matching_current_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            current = {
                "schema": 6,
                "cfg_fingerprint": "cfg",
                "entries": {"trace": {"entry_states": []}},
            }
            path.write_text(json.dumps(current))

            self.assertEqual(current, load_trace_cache(path, "cfg"))
            self.assertEqual(
                {"schema": 6, "cfg_fingerprint": "new", "entries": {}},
                load_trace_cache(path, "new"),
            )

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
            ("page_34", 0x5678): {(2, 0)},
            ("page_34", 0x580C): {(0xBB, 0xBB31)},
            ("page_34", 0x6143): {(0x25, 0)},
            ("page_34", 0x5935): {(0, 0xEF33)},
            ("page_34", 0x6105): {(0x29, 0)},
            ("page_33", 0x4F6D): {(0x0A, 0)},
            ("page_39", 0x4C31): {(0x13, 0)},
        }, {"34:759C": {(
            "34:75A5:fallthrough", "34:75A9:fallthrough",
            "34:75B0:taken", "34:75BB:taken",
        )}})

        self.assertIn("entry_state:34:5678:A=0x2", features)
        self.assertIn("entry_state:34:580C:A=0xBB,E=0x31", features)
        self.assertIn("entry_state:34:6143:A=0x25", features)
        self.assertTrue(any(feature.startswith(
            "modeled_path:34:5678:fraction_operand_scan:") for feature in features))
        self.assertTrue(any(feature.startswith(
            "modeled_path:34:580C:advance_one_token:") for feature in features))
        self.assertTrue(any(feature.startswith(
            "modeled_path:34:6143:glyph_DB_set_iy32_bit2:") for feature in features))
        self.assertTrue(any(feature.startswith(
            "observed_path:34:759C:") for feature in features))
        self.assertIn("dispatch_input:34:5935:DE=0xEF33", features)
        self.assertIn("dispatch_index:34:6105:type=0x29", features)
        self.assertIn("dispatch_index:33:4F6D:index=0x0A", features)
        self.assertIn("dispatch_index:39:4C31:class=0x13", features)

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

    def test_oracle_features_group_record_lcd_and_case_family(self) -> None:
        document = {
            "schema": 1,
            "power_cases": [{
                "expression": "X^2", "trace_sha256": "abc",
                "accepted_write_sha256": "def",
                "nodes": [{"render_type": 0}, {"render_type": 0x2A}],
            }],
            "viewport_cases": [{
                "expression": "1//1", "trace_sha256": "ghi",
                "final_lcd_sha256": "jkl",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mathprint-test-oracles.json"
            path.write_text(json.dumps(document))
            features = oracle_trace_features((path,))

        self.assertEqual({
            "oracle_case:mathprint-test-oracles:power_cases:def",
            "record_oracle:type=0x00", "record_oracle:type=0x2A",
            "lcd_oracle:type=0x00", "lcd_oracle:type=0x2A",
        }, features["abc"])
        self.assertEqual({
            "oracle_case:mathprint-test-oracles:viewport_cases:jkl",
        }, features["ghi"])

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
            serialize_trace_summary(
                row, Counter({outcome: 3}), Counter({hit: 4}), witness,
                {hit: {(0x25, 0x1234)}},
                {"34:5678": {("34:5680:taken",)}},
            ),
        )

        self.assertEqual("new", restored[0]["label"])
        self.assertEqual(3, restored[1][outcome])
        self.assertEqual(4, restored[2][hit])
        self.assertEqual("new", restored[3][outcome]["trace"])
        self.assertEqual({(0x25, 0x1234)}, restored[4][hit])
        self.assertEqual({("34:5680:taken",)}, restored[5]["34:5678"])

    def test_restores_prior_report_trace_identities_without_trace_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps({"traces": [
                {
                    "label": "natural",
                    "sha256": "a" * 64,
                    "provenance": TRACE_PROVENANCE_NATURAL,
                },
                {
                    "label": "synthetic",
                    "sha256": "b" * 64,
                    "provenance": TRACE_PROVENANCE_SYNTHETIC,
                },
            ]}))

            self.assertEqual([
                ("synthetic", "b" * 64, TRACE_PROVENANCE_SYNTHETIC),
            ], cached_report_traces(path, excluded_labels={"natural"}))


class CheckedReportTests(unittest.TestCase):
    def test_checked_report_contains_current_symbolic_and_trace_evidence(self) -> None:
        report = json.loads(
            Path(__file__).with_name("mathprint-saturation.json").read_text()
        )

        self.assertEqual(2, report["schema"])
        self.assertEqual(235, len(report["traces"]))
        self.assertEqual(
            234,
            sum(
                row["provenance"] == TRACE_PROVENANCE_NATURAL
                for row in report["traces"]
            ),
        )
        self.assertEqual(1008, report["summary"]["branch_outcomes_observed"])
        self.assertEqual(
            1005, report["summary"]["natural_branch_outcomes_observed"]
        )
        self.assertEqual(
            1343,
            report["symbolic_model_corpus"]["path_equivalence_class_count"],
        )
        integral = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_integral_boundary_insert"
        )
        self.assertEqual(
            "328b8f52ebe939b35f79e676076984aa85ee59e05c06862647c4fc615069bb3c",
            integral["sha256"],
        )
        nested = next(
            row for row in report["traces"]
            if row["label"] == "nested_tall_nderiv"
        )
        self.assertEqual(
            "e11c011b74df79165c55f7f64b699e3aa393bf8087f45ec89a73d616b73cdbb5",
            nested["sha256"],
        )
        radical = next(
            row for row in report["traces"]
            if row["label"] == "radical_left_clip"
        )
        self.assertEqual(
            "45ad4ff889771fd9317d89e266977e5fa42f417a291ca0b2543e24d09386bd09",
            radical["sha256"],
        )
        list_flat = next(
            row for row in report["traces"] if row["label"] == "list-flat"
        )
        self.assertEqual(
            "e62ba429764da46bb639decbca3ad2cf5460311771055d58f6b17641ffc57600",
            list_flat["sha256"],
        )
        list_radical = next(
            row for row in report["traces"] if row["label"] == "list-radical"
        )
        self.assertEqual(
            "7635aa5c7747a41132ab527b826b79d5dfeb87a5a472e404f3c332732b738203",
            list_radical["sha256"],
        )
        vertical = next(
            row for row in report["traces"]
            if row["label"] == "nested-fraction-vclip"
        )
        self.assertEqual(
            "14550292df84b68282500c4e19ccfd9f4ee160e6428585600ba2e1f37f699b3c",
            vertical["sha256"],
        )
        combined = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_combined_viewport"
        )
        self.assertEqual(
            "55326c941eac8edf12139fe9a83701dc1aa91099e2238c71d01d1c147ac08132",
            combined["sha256"],
        )
        structural_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_construct"
        )
        self.assertEqual(
            "098358a93632fba0766427d7b47e389686b5ee6d51c00553f3dceb597183ada2",
            structural_insert["sha256"],
        )
        populated_structural_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_after_token"
        )
        self.assertEqual(
            "3971dc69beadcd09e9d2b1fd38a92e824593319b67da1ab6fd386cce7a900ea5",
            populated_structural_insert["sha256"],
        )
        mid_leaf_structural_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_mid_leaf"
        )
        self.assertEqual(
            "fc8b6eb9a9f79624d39f91f42f9bab7555b70d96edb11ce04ea88bca3e08311b",
            mid_leaf_structural_insert["sha256"],
        )
        nested_structural_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_nested_numerator"
        )
        self.assertEqual(
            "cf3521d2d260459f6cc1ab71293ea27985aac167b1333b2a80356680fb7ebea1",
            nested_structural_insert["sha256"],
        )
        leading_structural_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_before_token"
        )
        self.assertEqual(
            "7b5e4c15c352796ef2e3836a8c8ec38c08d7381cba9987719752a8c5d23c5dbc",
            leading_structural_insert["sha256"],
        )
        nested_blank_structural_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_nested_blank"
        )
        self.assertEqual(
            "315429db57ba03e32ab8671b27c81cf3df75f10e14723b7ae688677c5f6cdf59",
            nested_blank_structural_insert["sha256"],
        )
        nested_mid_leaf_structural_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_nested_mid_leaf"
        )
        self.assertEqual(
            "946fc72c860bb09f2dd8d194a8096b1169fe292c89ef684fdb88ac778cb887a7",
            nested_mid_leaf_structural_insert["sha256"],
        )
        nested_leading_structural_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_nested_leading"
        )
        self.assertEqual(
            "955d63db229f190c09ed3cfefbe1c1d3a9ccbf143a51791976f9a41a0ca24643",
            nested_leading_structural_insert["sha256"],
        )
        denominator_blank_structural_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_denominator_blank"
        )
        self.assertEqual(
            "575d0cf77415127c91f6422f865750fb1833c112fb55d80c449cb533816b29ad",
            denominator_blank_structural_insert["sha256"],
        )
        denominator_end_structural_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_denominator_end"
        )
        self.assertEqual(
            "4cda557c3a0dfcd8e014ef96fcfe01fca3c23d53bde78d4572350857dfab9f1e",
            denominator_end_structural_insert["sha256"],
        )
        denominator_leading_structural_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_denominator_leading"
        )
        self.assertEqual(
            "1e7545fdab675ab151d97db291d71b5ab6665a9ad375b5927f72ffff7512b839",
            denominator_leading_structural_insert["sha256"],
        )
        denominator_mid_leaf_structural_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_denominator_mid_leaf"
        )
        self.assertEqual(
            "7e52bade21b0d1b5b5453265abc7dc7059d1b22a9badff33778748d8fbb2926e",
            denominator_mid_leaf_structural_insert["sha256"],
        )
        radicand_fraction_insert = next(
            row for row in report["traces"]
            if row["label"] == "mathprint_editor_fraction_radicand_blank"
        )
        self.assertEqual(
            "746454979929d3017137f167f608c25502e7b3c21cdacd05b287e02c3e9a0817",
            radicand_fraction_insert["sha256"],
        )
        radical_insertions = {
            row["label"]: row["sha256"]
            for row in report["traces"]
            if row["label"].startswith("mathprint_editor_radical_")
        }
        self.assertEqual(
            {
                "mathprint_editor_radical_blank":
                    "da415dc671b9a6ab7e4b413e01a6e07015f826e9ceb4f392f1ba2c88115fe9d9",
                "mathprint_editor_radical_end":
                    "4c603013205afb2bbee12d971fdd21d24ad6a6c998fe5b56163419ef5007befb",
                "mathprint_editor_radical_mid_leaf":
                    "efd6871b50c0547a6b6beaafdf50f137281ec20208ebac8f1af53f22dd9e50cb",
                "mathprint_editor_radical_leading":
                    "ec4f811fd7d2bb5cb064e3a3509a38a0e53e4766fa2c8776087125a9e42248df",
                "mathprint_editor_radical_two_byte_replace":
                    "1447a6ec76bd23ca5901a9b81249a4b000179b7829e496fc90cf1368918ef228",
                "mathprint_editor_radical_numerator_blank":
                    "4501024f1aa4a50760872b536a8b494b8c18f74407b0eed2f72b38e88894aa4c",
                "mathprint_editor_radical_numerator_end":
                    "c421b5d59418bc87c3af072b9d7d625017023058681ac003f2f8684aef04d248",
                "mathprint_editor_radical_numerator_leading":
                    "46d27e465d5b85cc9e55cda62715837f251fe88638450897cfed4e0909bdb147",
                "mathprint_editor_radical_numerator_mid_leaf":
                    "0b1be1a6d7949b4fa11096c7b5b1b18b6797a347445b37f53e5c58d5dd557555",
                "mathprint_editor_radical_denominator_blank":
                    "ca34c735010590a2e54da9569837ee6b19c283aee6876ac0d34e310267f16f22",
                "mathprint_editor_radical_denominator_end":
                    "15aa3a3be88aa0d46c9a7ac1e4a71de7d70336d02c843888b88ed76ba35035c6",
                "mathprint_editor_radical_denominator_leading":
                    "65b368f1f6c11e504c454d5fe5d4f8e340d9bc2c53763143f4eabfa437f89aee",
                "mathprint_editor_radical_denominator_mid_leaf":
                    "7a73d8b6aeb5c86f0b526ffe945fb66e0518eb31f9c165890e88991408658732",
                "mathprint_editor_radical_radicand_blank":
                    "fa0f6d47773012ad3205f667daad763c720676a131da6d40934c4b1a57b76166",
                "mathprint_editor_radical_radicand_end":
                    "a9cd7e3d34231f9211c61e5690bd823092866af859292196ccf70f4835a8fa33",
                "mathprint_editor_radical_radicand_leading":
                    "1b57a7fe41762413ef73d08db71bcadd577ccf2605bbb5fc0decebd1ce86a66b",
                "mathprint_editor_radical_radicand_mid_leaf":
                    "acda65cfe0484740e7d51a3f180161e982f74e10efb072b078cde6482e915829",
            },
            radical_insertions,
        )
        one_child_insertions = {
            row["label"]: row["sha256"]
            for row in report["traces"]
            if row["label"] in {
                "mathprint_editor_absolute_blank",
                "mathprint_editor_epower_blank",
                "mathprint_editor_epower_end",
                "mathprint_editor_epower_leading",
                "mathprint_editor_epower_mid_leaf",
                "mathprint_editor_tenpower_blank",
            }
        }
        self.assertEqual({
            "mathprint_editor_absolute_blank":
                "9cfc96a214324b420c7a2132e63f33366b695c576eb38ac2dcc08cb98e5deab8",
            "mathprint_editor_epower_blank":
                "6d7b10adea1a590d07c9fe5cee711f91561919ed9da1ab9197656188c14a7100",
            "mathprint_editor_epower_end":
                "a3d70dbd89e965005aef8464e5ffa3c592e80ed251be98012ae310ad40760c00",
            "mathprint_editor_epower_leading":
                "e80e7ae77af8d6fc04111f707c8e4bfc71e7fb322132a4bf42fa1091e8597841",
            "mathprint_editor_epower_mid_leaf":
                "ac7d77cc3c22710a258e3b08244479a3d1bda8083b748f0e1df5059222b33ec1",
            "mathprint_editor_tenpower_blank":
                "dfe59bfc4215926720393963af7805c33f6f8e1e424f1e364e0e2e2427ecc5ce",
        }, one_child_insertions)
        nth_root_insertions = {
            row["label"]: row["sha256"]
            for row in report["traces"]
            if row["label"] in {
                "mathprint_editor_nthroot_blank",
                "mathprint_editor_nthroot_end",
                "mathprint_editor_nthroot_leading",
                "mathprint_editor_nthroot_mid_leaf",
            }
        }
        self.assertEqual({
            "mathprint_editor_nthroot_blank":
                "260a5717b3023667518d6c9359d33b3cc8fce3366ad7f5cda91d010d3c012f47",
            "mathprint_editor_nthroot_end":
                "774d552d27510f3a0cd53bb52429e8f8a6285005a25a9934e8672413d2c89992",
            "mathprint_editor_nthroot_leading":
                "0c6fc62cd38128920e62478b2be96ca894bd6a4d0538cbd4ce5ab968127b46a3",
            "mathprint_editor_nthroot_mid_leaf":
                "b64878e61eea3aa5d5cca5b7b4d820e90f2184f455982b56dd47df11528aa2b2",
        }, nth_root_insertions)
        power_insertions = {
            row["label"]: row["sha256"]
            for row in report["traces"]
            if row["label"] in {
                "mathprint_editor_power_blank",
                "mathprint_editor_power_end",
                "mathprint_editor_power_leading",
                "mathprint_editor_power_mid_leaf",
            }
        }
        self.assertEqual({
            "mathprint_editor_power_blank":
                "782ea7f64783623cef0fe38e45f53c9614c18052b98e59ae6dcdee942ca8be4f",
            "mathprint_editor_power_end":
                "9d316b4fc448c3d202be3a0496eb81a6cc8573b5a2223a74b811ad1ce4ef6173",
            "mathprint_editor_power_leading":
                "30b8a7970cf0d1905281bc7ac1130c1a0d60eae847775b9936f6a7474b59ab70",
            "mathprint_editor_power_mid_leaf":
                "efe22ba4ff41bd29e327c2d86f8af6e092005a78594e3a414c89ace21ed65c82",
        }, power_insertions)
        self.assertEqual(
            114, report["record_oracles"]["cases"]
        )
        self.assertEqual(
            1317,
            report["minimized_dynamic_feature_corpus"]["covered_features"],
        )
        self.assertEqual(
            173,
            report["minimized_dynamic_feature_corpus"]["selected_trace_count"],
        )
        self.assertEqual(
            1314,
            report["minimized_natural_dynamic_feature_corpus"][
                "covered_features"
            ],
        )
        self.assertEqual(
            172,
            report["minimized_natural_dynamic_feature_corpus"][
                "selected_trace_count"
            ],
        )


if __name__ == "__main__":
    unittest.main()
