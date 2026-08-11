"""Reusable oracle for the native Wabbitemu keypad and ON-edge probe."""

from __future__ import annotations

import json

from keypad_hardware import read_keypad_matrix
from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuKeypadReport


MATRIX_CASES = {
    "single": (0xFE, ((0, 0),)),
    "same_column": (0xFC, ((0, 0), (1, 0))),
    "rectangle": (0xFE, ((0, 0), (1, 0), (1, 1))),
    "transitive": (
        0xFE,
        ((0, 0), (1, 0), (1, 1), (2, 1), (2, 2)),
    ),
    "unwired": (0x7F, ((7, 0),)),
}


def expected_keypad_values() -> dict[str, int]:
    """Return the pinned source-model value for every native case."""

    expected: dict[str, int] = {}
    for name, (mask, keys) in MATRIX_CASES.items():
        expected[f"{name}_mask"] = mask
        expected[f"{name}_read"] = read_keypad_matrix(
            "Wabbitemu", mask, keys
        ).active_low_value
    expected.update(
        {
            "on_initial_status": 0x08,
            "on_enabled_status": 0x08,
            "on_press_before_eval": 0x00,
            "on_press_after_eval": 0x01,
            "on_held_after_ack": 0x00,
            "on_held_after_eval": 0x00,
            "on_release_before_eval": 0x08,
            "on_release_after_eval": 0x08,
            "on_second_press_before_eval": 0x00,
            "on_second_press_after_eval": 0x01,
            "tstates": 0,
        }
    )
    return expected


def validate_keypad_report(report: WabbitemuKeypadReport) -> dict[str, object]:
    """Check native matrix and ON observations against the source model."""

    expected = expected_keypad_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native keypad report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "matrix_groups": 7,
            "matrix_algorithm": "one pairwise-overlap pass per row",
            "group_write": "stored as the active-high complement",
            "on_level_bit": 3,
            "on_pending_bit": 0,
            "on_edge": "press sampled by standard-interrupt evaluation",
            "release_rearms_after_evaluation": True,
        },
        "native": observed,
    }
