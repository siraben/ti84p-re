#!/usr/bin/env python3
"""Verify and describe a pinned deployed jsTIfied artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jstified_hardware import describe_artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        result = describe_artifact(args.artifact)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(
        f"jsTIfied: {result['artifact_size']} bytes, "
        f"SHA-256 {result['artifact_sha256']}"
    )
    print(f"verified source fingerprints: {len(result['verified_fingerprints'])}")


if __name__ == "__main__":
    main()
