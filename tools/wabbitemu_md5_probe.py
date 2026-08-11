"""Reusable oracle for the native Wabbitemu MD5 edge probe."""

from __future__ import annotations

import json

from md5_hardware import md5_edge_values
from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuMd5EdgeReport


def expected_md5_edge_values() -> dict[str, object]:
    """Return the pinned source-model result for every native edge case."""

    return md5_edge_values()


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
