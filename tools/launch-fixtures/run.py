#!/usr/bin/env python3
"""Run and check compiled-program launch-boundary fixtures in TilEm."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tilem_trace_resolve import IDX_PC, iter_records, read_header  # noqa: E402


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESOLVER = ROOT / "tools" / "tilem_trace_resolve.py"
NAMES = ROOT / "tools" / "names.txt"
DEFAULT_ROM = ROOT / "tools" / "rom.bin"
CASES = {
    "1FFF": True,
    "2000": True,
    "2001": False,
}


def run(cmd: list[str], *, stdout: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    if stdout is None:
        subprocess.run(cmd, cwd=ROOT, check=True)
        return
    with stdout.open("w", encoding="utf-8") as stream:
        subprocess.run(cmd, cwd=ROOT, check=True, stdout=stream)


def logical_pcs(trace: Path) -> set[int]:
    """Return raw PCs without depending on reconstructed bank selectors."""
    pcs: set[int] = set()
    with trace.open("rb") as stream:
        read_header(stream)
        for record_type, payload in iter_records(stream):
            if record_type == 0x01:
                pcs.add(payload[IDX_PC])
    return pcs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tilem", default=os.environ.get("TILEM"))
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--fixtures", type=Path, default=HERE / "generated")
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp/launch-boundaries"))
    parser.add_argument("--case", action="append", choices=CASES)
    parser.add_argument("--keep-trace", action="store_true")
    args = parser.parse_args()

    tilem = Path(args.tilem) if args.tilem else None
    if tilem is None:
        found = shutil.which("tilem2")
        tilem = Path(found) if found else None
    if tilem is None or not tilem.exists():
        raise SystemExit("TilEm not found; pass --tilem or set TILEM")
    if not args.rom.exists():
        raise SystemExit(f"ROM not found: {args.rom}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    selected = args.case or CASES
    for suffix in selected:
        accepted = CASES[suffix]
        fixtures = [
            args.fixtures / f"A{suffix}.8xp",
            args.fixtures / f"B{suffix}.8xp",
        ]
        missing = [str(path) for path in fixtures if not path.exists()]
        if missing:
            raise SystemExit(f"fixtures not found: {', '.join(missing)}; run build.py first")
        trace = args.out_dir / f"{suffix}.trace"
        coverage = args.out_dir / f"{suffix}.coverage.txt"
        gif = args.out_dir / f"{suffix}.gif"
        run(
            [
                str(tilem),
                "--headless",
                "--rom", str(args.rom),
                "--model", "ti84p",
                "--normal-speed",
                "--reset",
                "--macro", str(HERE / "run-first.macro"),
                "--trace", str(trace),
                "--trace-range", "all",
                "--headless-record", str(gif),
                *map(str, fixtures),
            ]
        )
        run(
            [
                sys.executable,
                str(RESOLVER),
                str(trace),
                "--initial-mapping", "ti84p-reset",
                "--coverage",
                "--sort", "addr",
                "--names", str(NAMES),
            ],
            stdout=coverage,
        )
        pcs = logical_pcs(trace)

        common = {0x5758, 0x577B}
        missing_common = common - pcs
        if missing_common:
            rendered = [f"0x{pc:04X}" for pc in sorted(missing_common)]
            raise SystemExit(f"{suffix}: launch trace misses {rendered}")

        copied = 0x578D in pcs
        handed_off = 0x57B4 in pcs
        executed = 0x9D95 in pcs
        rejected = 0x2729 in pcs
        if accepted and not (copied and handed_off and executed and not rejected):
            raise SystemExit(
                f"{suffix}: expected acceptance, got copy={copied} "
                f"handoff={handed_off} execute={executed} reject={rejected}"
            )
        if not accepted and not (rejected and not copied and not handed_off and not executed):
            raise SystemExit(
                f"{suffix}: expected rejection, got copy={copied} "
                f"handoff={handed_off} execute={executed} reject={rejected}"
            )
        result = "accepted" if accepted else "rejected"
        print(
            f"{suffix}: {result}; copy={copied} handoff={handed_off} "
            f"execute={executed} memory_error={rejected}"
        )
        if not args.keep_trace:
            trace.unlink()


if __name__ == "__main__":
    main()
