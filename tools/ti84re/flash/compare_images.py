#!/usr/bin/env python3
"""Compare complete Flash images with hashes, ranges, and page counts."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from ti84re.flash.image_compare import compare_flash_images


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--expected-left-sha256")
    parser.add_argument("--expected-right-sha256")
    parser.add_argument("--expect-equal", action="store_true")
    parser.add_argument("--limit-ranges", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.limit_ranges < 0:
        parser.error("--limit-ranges must be nonnegative")
    try:
        comparison = compare_flash_images(
            args.left.read_bytes(),
            args.right.read_bytes(),
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    for label, actual, expected in (
        ("left", comparison.left_sha256, args.expected_left_sha256),
        ("right", comparison.right_sha256, args.expected_right_sha256),
    ):
        if expected is not None and actual != expected.casefold():
            parser.error(f"{label} SHA-256 is {actual}; expected {expected.casefold()}")

    report = {
        "left": str(args.left),
        "right": str(args.right),
        "size": comparison.size,
        "left_sha256": comparison.left_sha256,
        "right_sha256": comparison.right_sha256,
        "equal": comparison.equal,
        "differing_bytes": comparison.differing_bytes,
        "difference_ranges": [
            asdict(item) for item in comparison.ranges[: args.limit_ranges]
        ],
        "difference_ranges_total": len(comparison.ranges),
        "page_counts": [
            {"page": page, "count": count}
            for page, count in comparison.page_counts
        ],
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        relation = "equal" if comparison.equal else "different"
        print(
            f"{relation}: size=0x{comparison.size:X} "
            f"differing_bytes={comparison.differing_bytes}"
        )
        print(f"left SHA-256:  {comparison.left_sha256}")
        print(f"right SHA-256: {comparison.right_sha256}")
        for item in comparison.ranges[: args.limit_ranges]:
            print(f"range 0x{item.start:05X}–0x{item.end - 1:05X}")
        for page, count in comparison.page_counts:
            print(f"page {page:02X}: {count} differing byte(s)")
    if args.expect_equal and not comparison.equal:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
