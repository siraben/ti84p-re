#!/usr/bin/env python3
"""Run generated TI-BASIC fixtures under headless TilEm and check trace anchors."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "tools" / "tibasic-samples"
DEFAULT_MACRO = ROOT / "tools" / "macros" / "run-first-program.macro"
FACTORIAL_MACRO = ROOT / "tools" / "macros" / "run-first-program-factorial5.macro"
NAMES = ROOT / "tools" / "names.txt"
TRACE_RESOLVE = ROOT / "tools" / "tilem_trace_resolve.py"
DEFAULT_ROM = ROOT / "tools" / "rom.bin"


@dataclass(frozen=True)
class Case:
    programs: tuple[str, ...]
    screen: str
    anchors: tuple[str, ...]
    macro: Path = DEFAULT_MACRO
    min_dark_pixels: int = 0


CASES: dict[str, Case] = {
    "hello": Case(
        ("HELLO.8xp",),
        "HELLO, WORLD; Done",
        ("eval_stmt_entry", "_Disp"),
    ),
    "factorial": Case(
        ("FACTOR.8xp",),
        "N=5; 120; Done",
        ("eval_stmt_entry", "_FPMult", "_Disp"),
        FACTORIAL_MACRO,
    ),
    "data": Case(
        ("DATA.8xp",),
        "sorted list, cumulative list, sum 14; Done",
        ("store_list_elem", "list_fold_dispatch", "_Disp"),
    ),
    "asmcall": Case(
        ("ASMCALL.8xp", "ASMRET.8xp"),
        "BEFORE; AFTER; Done",
        ("_ExecutePrgm", "ram:9d95"),
    ),
    "asmbridge": Case(
        ("ASMBRIDG.8xp", "ASMSIG.8xp", "ZZBASIC.8xp"),
        "BEFORE; CALLED; AFTER; Done",
        ("ram:9d95", "_OP1Set1", "_StoAns", "_AnsName", "eval_eqn_recursive"),
    ),
    "animtext": Case(
        ("ANIMTXT.8xp",),
        "row of X characters, DONE; Done",
        ("eval_stmt_entry", "_OutputExpr", "_Disp"),
        min_dark_pixels=100,
    ),
    "graphviz": Case(
        ("GRAPHV.8xp",),
        "graph screen with DFS, axes, circle, diagonal line",
        ("_GrBufClr", "_ILine", "_IPoint", "_PDspGrph"),
        min_dark_pixels=100,
    ),
    "graphdfs": Case(
        ("GRAPHDFS.8xp",),
        "graph screen with four labeled nodes and three edges",
        ("_StoSysTok", "_ILine", "_IPoint", "_PDspGrph"),
        min_dark_pixels=200,
    ),
    "callsub": Case(
        ("CALLSUB.8xp", "SUBRT.8xp"),
        "SUB; 1; Done",
        ("_ParseInpLastEnt", "stmt_eval_body_entry", "call_eval_eqn_recursive", "eval_eqn_recursive"),
    ),
    "bigadd": Case(
        ("BIGADD.8xp",),
        "L3 digits and carry; Done",
        ("list_var_index", "_GetLToOP1", "_PutToL", "_FPMult"),
    ),
    "dfs": Case(
        ("DFS.8xp",),
        "1, 3, 2, 4, visited list; Done",
        ("blockmatch_end_else", "parse_scan_tokens", "if_isg_stmt_handler"),
    ),
}


def run(cmd: list[str], *, cwd: Path, stdout: Path | None = None) -> str:
    print("+", " ".join(cmd))
    if stdout is None:
        completed = subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        return completed.stdout

    with stdout.open("w", encoding="utf-8") as f:
        subprocess.run(cmd, cwd=cwd, check=True, stdout=f)
    return ""


def require_path(value: str | Path, what: str) -> Path:
    path = Path(value).expanduser()
    if not path.exists():
        raise SystemExit(f"{what} not found: {path}")
    return path


def require_tilem(value: str | None) -> Path:
    if value:
        return require_path(value, "TilEm binary")
    found = shutil.which("tilem2")
    if not found:
        raise SystemExit("Set --tilem or TILEM to a headless-capable tilem2 binary")
    return Path(found)


def resolve_trace(trace: Path, coverage: Path) -> str:
    cmd = [
        sys.executable,
        str(TRACE_RESOLVE),
        str(trace),
        "--coverage",
        "--sort",
        "addr",
        "--names",
        str(NAMES),
    ]
    run(cmd, cwd=ROOT, stdout=coverage)
    return coverage.read_text(encoding="utf-8", errors="replace")


def require_magick() -> str:
    magick = shutil.which("magick")
    if not magick:
        raise SystemExit("ImageMagick `magick` is required for final-frame visual checks")
    return magick


def extract_final_frame(gif: Path, png: Path) -> None:
    run([require_magick(), f"{gif}[-1]", str(png)], cwd=ROOT)


def count_dark_pixels(png: Path) -> int:
    output = run(
        [
            require_magick(),
            str(png),
            "-colorspace",
            "Gray",
            "-threshold",
            "50%",
            "-format",
            "%c",
            "histogram:info:-",
        ],
        cwd=ROOT,
    )
    dark = 0
    for line in output.splitlines():
        if "gray(0)" not in line and "#000000" not in line:
            continue
        match = re.match(r"\s*(\d+):", line)
        if match:
            dark += int(match.group(1))
    return dark


def run_case(name: str, case: Case, tilem: Path, rom: Path, out_dir: Path, keep_trace: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    trace = out_dir / f"{name}.trace"
    gif = out_dir / f"{name}.gif"
    final_png = out_dir / f"{name}-final.png"
    coverage = out_dir / f"{name}.coverage.txt"

    cmd = [
        str(tilem),
        "--headless",
        "--rom",
        str(rom),
        "--model",
        "ti84p",
        "--normal-speed",
        "--reset",
        "--macro",
        str(case.macro),
        "--trace",
        str(trace),
        "--trace-range",
        "all",
        "--headless-record",
        str(gif),
        *[str(SAMPLES / program) for program in case.programs],
    ]
    run(cmd, cwd=ROOT)
    extract_final_frame(gif, final_png)
    coverage_text = resolve_trace(trace, coverage)

    missing = [anchor for anchor in case.anchors if anchor not in coverage_text]
    if missing:
        raise SystemExit(f"{name}: missing trace anchors: {', '.join(missing)}")

    if case.min_dark_pixels:
        dark_pixels = count_dark_pixels(final_png)
        if dark_pixels < case.min_dark_pixels:
            raise SystemExit(
                f"{name}: final frame has {dark_pixels} dark pixels, expected at least {case.min_dark_pixels}"
            )
        print(f"{name}: final frame dark pixels: {dark_pixels}")

    print(f"{name}: expected screen: {case.screen}")
    print(f"{name}: anchors ok: {', '.join(case.anchors)}")
    if not keep_trace:
        trace.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tilem", default=None, help="path to patched headless tilem2; defaults to TILEM or PATH")
    parser.add_argument("--rom", default=None, help="path to ROM image; defaults to TI84_ROM or tools/rom.bin")
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp/tibasic-smoke"))
    parser.add_argument("--case", action="append", choices=sorted(CASES), help="case to run; repeatable")
    parser.add_argument("--list", action="store_true", help="list cases and exit")
    parser.add_argument("--keep-trace", action="store_true", help="keep large binary trace files")
    args = parser.parse_args()

    if args.list:
        for name, case in CASES.items():
            print(f"{name}: {' '.join(case.programs)} -> {case.screen}")
        return

    tilem = require_tilem(args.tilem or os.environ.get("TILEM"))
    rom = require_path(args.rom or os.environ.get("TI84_ROM") or DEFAULT_ROM, "ROM image")
    selected = args.case or list(CASES)
    for name in selected:
        run_case(name, CASES[name], tilem, rom, args.out_dir, args.keep_trace)


if __name__ == "__main__":
    main()
