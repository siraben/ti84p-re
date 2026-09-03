#!/usr/bin/env python3
"""Compare prefixed-opcode fetch paths in pinned TilEm and Wabbitemu trees."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ti84re.emulators.prefix_fetch_models import PrefixFetchModelError, compare_prefix_fetch_models
from ti84re.emulators.tilem.core import TilemCoreError
from ti84re.emulators.wabbitemu.headless import WabbitemuHeadlessError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tilem-source", type=Path, required=True)
    parser.add_argument("--wabbitemu-source", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = compare_prefix_fetch_models(
            args.tilem_source,
            args.wabbitemu_source,
        )
    except (OSError, PrefixFetchModelError, TilemCoreError, WabbitemuHeadlessError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(report, indent=2))
        return
    disagreement = report["indexed_cb_disagreement"]
    print(
        "indexed CB: "
        f"TilEm={disagreement['tilem_m1_fetches']} M1 fetches, "
        f"Wabbitemu={disagreement['wabbitemu_m1_fetches']} M1 fetches"
    )
    print("physical result: pending")


if __name__ == "__main__":
    main()
