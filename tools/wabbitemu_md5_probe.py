"""Reusable oracle for the native Wabbitemu MD5 edge probe."""

from __future__ import annotations

import json

from md5_hardware import md5_assist_value
from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuMd5EdgeReport


ABC_FIRST_STEP = (
    0x67452301,
    0xEFCDAB89,
    0x98BADCFE,
    0x10325476,
    0x80636261,
    0xD76AA478,
)


def expected_md5_edge_values() -> dict[str, object]:
    """Return the pinned source-model result for every native edge case."""

    before_mutation = md5_assist_value(0, *ABC_FIRST_STEP, 7)
    after_mutation = md5_assist_value(
        0,
        0xFFFFFFFF,
        *ABC_FIRST_STEP[1:],
        7,
    )
    return {
        "reset_operand_reads": (0, 0, 0, 0),
        "reset_result": 0,
        "one_write_result": 0x11000000,
        "three_write_result": 0x33221100,
        "four_write_result": 0x44332211,
        "five_write_result": 0x55443322,
        "raw_shift": 0xFF,
        "raw_mode": 0xFF,
        "masked_control_result": md5_assist_value(3, 1, 2, 3, 4, 5, 6, 31),
        "loaded_operand_reads": (0, 0, 0, 0),
        "before_mutation_result": before_mutation,
        "after_mutation_result": after_mutation,
        "mixed_result": (before_mutation & 0xFF) | (after_mutation & 0xFFFFFF00),
        "tstates": 0,
    }


def validate_md5_edge_report(
    report: WabbitemuMd5EdgeReport,
) -> dict[str, object]:
    """Check a native MD5 report against the independent arithmetic model."""

    expected = expected_md5_edge_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native MD5 edge report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "operand_register": "(old >> 8) | (byte << 24)",
            "shift_mask": 0x1F,
            "mode_mask": 0x03,
            "recompute_on_each_result_read": True,
            "operand_read_value": 0,
        },
        "native": observed,
    }
