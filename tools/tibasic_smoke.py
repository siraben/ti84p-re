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
class VisualRegion:
    name: str
    crop: str
    min_dark_pixels: int
    max_dark_pixels: int | None = None


@dataclass(frozen=True)
class Case:
    programs: tuple[str, ...]
    screen: str
    anchors: tuple[str, ...]
    macro: Path = DEFAULT_MACRO
    min_dark_pixels: int = 0
    min_changed_pixels: int = 0
    min_distinct_frames: int = 0
    visual_regions: tuple[VisualRegion, ...] = ()


GRAPH_TOPOLOGY_REGIONS = (
    VisualRegion("node 1", "9x9+6+15", 15),
    VisualRegion("node 2", "9x9+31+5", 15),
    VisualRegion("node 3", "9x9+31+45", 15),
    VisualRegion("node 4", "9x9+51+30", 15),
    VisualRegion("edge 1-2", "22x12+12+7", 15),
    VisualRegion("edge 1-3", "22x28+12+21", 15),
    VisualRegion("edge 2-4", "22x25+37+11", 20),
)


CASES: dict[str, Case] = {
    "hello": Case(
        ("HELLO.8xp",),
        "HELLO, WORLD; Done",
        ("eval_stmt_entry", "_Disp"),
        visual_regions=(
            VisualRegion("HELLO line", "75x9+0+0", 120),
            VisualRegion("Done marker", "28x9+66+10", 30),
        ),
    ),
    "factorial": Case(
        ("FACTOR.8xp",),
        "N=5; 120; Done",
        ("eval_stmt_entry", "_FPMult", "_Disp"),
        FACTORIAL_MACRO,
        visual_regions=(
            VisualRegion("prompt echo", "28x9+0+10", 20),
            VisualRegion("result 120", "20x9+76+16", 5),
            VisualRegion("Done marker", "28x9+66+24", 30),
        ),
    ),
    "data": Case(
        ("DATA.8xp",),
        "sorted list, cumulative list, sum 14; Done",
        ("store_list_elem", "list_fold_dispatch", "_Disp"),
        visual_regions=(
            VisualRegion("sorted list", "55x9+40+8", 10),
            VisualRegion("cumulative list", "68x9+28+18", 70),
            VisualRegion("sum 14", "18x9+78+32", 15),
            VisualRegion("Done marker", "28x9+66+40", 40),
        ),
    ),
    "asmcall": Case(
        ("ASMCALL.8xp", "ASMRET.8xp"),
        "BEFORE; AFTER; Done",
        ("_ExecutePrgm", "ram:9d95"),
        visual_regions=(
            VisualRegion("BEFORE line", "36x9+0+9", 25),
            VisualRegion("AFTER line", "30x9+0+18", 60),
            VisualRegion("Done marker", "28x9+66+28", 25),
        ),
    ),
    "asmbridge": Case(
        ("ASMBRIDG.8xp", "ASMSIG.8xp", "ZZBASIC.8xp"),
        "BEFORE; CALLED; AFTER; Done",
        ("ram:9d95", "_OP1Set1", "_StoAns", "_AnsName", "eval_eqn_recursive"),
        visual_regions=(
            VisualRegion("BEFORE line", "36x9+0+9", 25),
            VisualRegion("CALLED line", "36x9+0+18", 70),
            VisualRegion("AFTER line", "30x9+0+27", 60),
            VisualRegion("Done marker", "28x9+66+36", 25),
        ),
    ),
    "asmreturn": Case(
        ("ASMRTN.8xp", "ASMVAL.8xp"),
        "ASM return value 2 through Ans; BASIC displays 5; Done",
        ("ram:9d95", "_OP1Set2", "_StoAns", "_AnsName", "_FPAdd", "_Disp"),
        visual_regions=(
            VisualRegion("result 5", "16x10+78+7", 4),
            VisualRegion("Done marker", "28x9+66+24", 40),
        ),
    ),
    "animtext": Case(
        ("ANIMTXT.8xp",),
        "row of X characters, DONE; Done",
        ("eval_stmt_entry", "_OutputExpr", "_Disp"),
        min_dark_pixels=100,
        min_changed_pixels=100,
        min_distinct_frames=5,
        visual_regions=(
            VisualRegion("home text row", "50x9+0+0", 80),
            VisualRegion("Done marker", "25x9+68+13", 10),
        ),
    ),
    "graphviz": Case(
        ("GRAPHV.8xp",),
        "graph screen with DFS, axes, circle, diagonal line",
        ("_GrBufClr", "_StoSysTok", "_ILine", "_IPoint", "_PDspGrph"),
        min_dark_pixels=100,
        min_changed_pixels=100,
        visual_regions=(
            VisualRegion("DFS label", "18x8+0+0", 15),
            VisualRegion("horizontal axis", "40x3+28+31", 30),
            VisualRegion("vertical axis", "3x40+47+12", 30),
            VisualRegion("circle top arc", "10x6+42+19", 8),
            VisualRegion("circle left arc", "7x14+36+24", 12),
        ),
    ),
    "graphdfs": Case(
        ("GRAPHDFS.8xp",),
        "graph screen with four labeled nodes and three edges",
        ("_StoSysTok", "_ILine", "_IPoint", "_PDspGrph"),
        min_dark_pixels=200,
        min_changed_pixels=200,
        visual_regions=GRAPH_TOPOLOGY_REGIONS,
    ),
    "graphlist": Case(
        ("GRAPHLST.8xp",),
        "list-driven graph screen with four labeled nodes and three edges",
        ("_StoSysTok", "list_var_index", "_GetLToOP1", "_ILine", "_IPoint", "_PDspGrph"),
        min_dark_pixels=200,
        min_changed_pixels=200,
        visual_regions=GRAPH_TOPOLOGY_REGIONS,
    ),
    "callsub": Case(
        ("CALLSUB.8xp", "SUBRT.8xp"),
        "SUB; 1; Done",
        ("_ParseInpLastEnt", "stmt_eval_body_entry", "call_eval_eqn_recursive", "eval_eqn_recursive"),
        visual_regions=(
            VisualRegion("SUB line", "18x9+0+9", 10),
            VisualRegion("result 1", "10x9+84+16", 1),
            VisualRegion("Done marker", "28x9+66+25", 10),
        ),
    ),
    "callabi": Case(
        ("ABICALL.8xp", "ABISUB.8xp"),
        "A=11, L1={2 4 9}, Ans=11; Done",
        ("stmt_eval_body_entry", "call_eval_eqn_recursive", "eval_eqn_recursive", "_AnsName", "store_list_elem"),
        visual_regions=(
            VisualRegion("scalar A", "18x9+76+10", 6),
            VisualRegion("mutated L1", "42x9+50+22", 40),
            VisualRegion("returned Ans", "18x9+76+33", 10),
            VisualRegion("Done marker", "28x9+66+44", 20),
        ),
    ),
    "callstop": Case(
        ("CALLSTOP.8xp", "STOPSUB.8xp"),
        "BEFORE; STOP; no AFTER; Done",
        ("stmt_eval_body_entry", "call_eval_eqn_recursive", "_Disp"),
        visual_regions=(
            VisualRegion("BEFORE line", "36x9+0+9", 25),
            VisualRegion("STOP line", "24x9+0+18", 35),
            VisualRegion("AFTER line absent", "30x9+5+27", 0, 30),
            VisualRegion("Done marker", "28x9+66+27", 10),
        ),
    ),
    "bigadd": Case(
        ("BIGADD.8xp",),
        "L3 digits and carry; Done",
        ("list_var_index", "_GetLToOP1", "_PutToL", "_FPMult"),
        visual_regions=(
            VisualRegion("digit list", "76x9+20+9", 20),
            VisualRegion("carry 1", "10x9+84+17", 10),
            VisualRegion("Done marker", "28x9+66+25", 10),
        ),
    ),
    "bigmul": Case(
        ("BIGMUL.8xp",),
        "L3 digits for 123*45 and high digit 5; Done",
        ("list_var_index", "_GetLToOP1", "_PutToL", "_FPMult"),
        visual_regions=(
            VisualRegion("digit list", "72x9+24+9", 25),
            VisualRegion("high digit 5", "10x9+84+17", 20),
            VisualRegion("Done marker", "28x9+66+25", 10),
        ),
    ),
    "dfs": Case(
        ("DFS.8xp",),
        "1, 3, 2, 4, visited list; Done",
        ("blockmatch_end_else", "parse_scan_tokens", "eval_stmt_entry"),
        visual_regions=(
            VisualRegion("traversal column", "10x36+84+0", 30),
            VisualRegion("visited list", "62x9+34+35", 40),
            VisualRegion("Done marker", "28x9+66+46", 35),
        ),
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


def extract_first_frame(gif: Path, png: Path) -> None:
    run([require_magick(), f"{gif}[0]", str(png)], cwd=ROOT)


def count_dark_pixels(png: Path, crop: str | None = None) -> int:
    cmd = [require_magick(), str(png)]
    if crop:
        cmd.extend(["-crop", crop, "+repage"])
    cmd.extend(["-colorspace", "Gray", "-threshold", "50%", "-format", "%c", "histogram:info:-"])
    output = run(cmd, cwd=ROOT)
    dark = 0
    for line in output.splitlines():
        if "gray(0)" not in line and "#000000" not in line:
            continue
        match = re.match(r"\s*(\d+):", line)
        if match:
            dark += int(match.group(1))
    return dark


def count_changed_pixels(before: Path, after: Path) -> int:
    completed = subprocess.run(
        [require_magick(), "compare", "-metric", "AE", str(before), str(after), "null:"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            completed.returncode,
            completed.args,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    match = re.match(r"\s*(\d+)", completed.stderr)
    if not match:
        raise SystemExit(f"could not parse ImageMagick compare output: {completed.stderr!r}")
    return int(match.group(1))


def count_distinct_frames(gif: Path) -> int:
    completed = subprocess.run(
        [require_magick(), str(gif), "-coalesce", "-format", "%#\n", "info:"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return len({line.strip() for line in completed.stdout.splitlines() if line.strip()})


def run_case(name: str, case: Case, tilem: Path, rom: Path, out_dir: Path, keep_trace: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    trace = out_dir / f"{name}.trace"
    gif = out_dir / f"{name}.gif"
    first_png = out_dir / f"{name}-first.png"
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

    if case.min_changed_pixels:
        extract_first_frame(gif, first_png)
        changed_pixels = count_changed_pixels(first_png, final_png)
        if changed_pixels < case.min_changed_pixels:
            raise SystemExit(
                f"{name}: final frame changed {changed_pixels} pixels from first frame, "
                f"expected at least {case.min_changed_pixels}"
            )
        print(f"{name}: first-to-final changed pixels: {changed_pixels}")

    if case.min_distinct_frames:
        distinct_frames = count_distinct_frames(gif)
        if distinct_frames < case.min_distinct_frames:
            raise SystemExit(
                f"{name}: captured {distinct_frames} distinct frames, "
                f"expected at least {case.min_distinct_frames}"
            )
        print(f"{name}: distinct frames: {distinct_frames}")

    for region in case.visual_regions:
        region_dark_pixels = count_dark_pixels(final_png, region.crop)
        if region_dark_pixels < region.min_dark_pixels:
            raise SystemExit(
                f"{name}: region {region.name!r} has {region_dark_pixels} dark pixels, "
                f"expected at least {region.min_dark_pixels}"
            )
        if region.max_dark_pixels is not None and region_dark_pixels > region.max_dark_pixels:
            raise SystemExit(
                f"{name}: region {region.name!r} has {region_dark_pixels} dark pixels, "
                f"expected at most {region.max_dark_pixels}"
            )
        print(f"{name}: region {region.name}: {region_dark_pixels} dark pixels")

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
