#!/usr/bin/env python3
"""Cold-boot and wake a TI-84 Plus image under pinned headless Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from wabbitemu_headless import WabbitemuHeadlessError, file_sha256, run_headless


def positive_count(value: str) -> int:
    count = int(value, 0)
    if count <= 0:
        raise argparse.ArgumentTypeError("count must be positive")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-input-sha256")
    parser.add_argument("--max-steps", type=positive_count, default=200_000_000)
    parser.add_argument("--min-steps", type=positive_count, default=20_000_000)
    parser.add_argument("--sample-interval", type=positive_count, default=1_000_000)
    parser.add_argument("--settle-samples", type=positive_count, default=10)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        parser.error(f"refusing to overwrite existing output {args.output}; use --force")
    if args.input.resolve() == args.output.resolve():
        parser.error("input and output images must be different paths")
    if args.min_steps > args.max_steps:
        parser.error("--min-steps cannot exceed --max-steps")
    try:
        if args.expected_input_sha256:
            actual = file_sha256(args.input)
            expected = args.expected_input_sha256.casefold()
            if actual != expected:
                raise WabbitemuHeadlessError(
                    f"input SHA-256 is {actual}; expected {expected}"
                )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report = run_headless(
            args.binary,
            args.input,
            args.output,
            max_steps=args.max_steps,
            min_steps=args.min_steps,
            sample_interval=args.sample_interval,
            settle_samples=args.settle_samples,
        )
    except WabbitemuHeadlessError as error:
        parser.error(str(error))
    payload = {
        "input": str(args.input),
        "output": str(args.output),
        **report.to_dict(),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"steps={report.steps} pc=0x{report.pc:04X} "
            f"changed={report.changed_bytes} settled={'yes' if report.settled else 'no'}"
        )
        print(f"output SHA-256: {report.output_sha256}")
    if not report.settled:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
