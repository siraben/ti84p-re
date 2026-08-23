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

from hardware_debug import MemoryExpectation, MemoryMismatch, check_memory_expectation


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "tools" / "tibasic-samples"
DEFAULT_MACRO = ROOT / "tools" / "macros" / "run-first-program.macro"
# Legacy macros in tools/macros/run-first-program*.macro relied on positional
# .8xp arguments, which the current tilem-headless build ignores; cases now
# generate loadvar-based macros instead (see generate_loadvar_macro).
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
    expected: str
    anchors: tuple[str, ...]
    macro: Path | None = DEFAULT_MACRO
    min_dark_pixels: int = 0
    min_changed_pixels: int = 0
    min_distinct_frames: int = 0
    visual_regions: tuple[VisualRegion, ...] = ()
    memory_expectations: tuple[MemoryExpectation, ...] = ()
    # When set (the default), ignore `macro` and generate a macro that loads
    # every fixture through the LINK->RECEIVE `loadvar` transfer command (the
    # current tilem-headless build ignores positional .8xp arguments), then
    # runs the alphabetically-first program via PRGM > EXEC.
    use_loadvar: bool = True
    # Raw macro lines inserted after PRGM EXEC starts (program input keys,
    # delayed prompts, extra waits). Each line is responsible for its own waits.
    exec_lines: tuple[str, ...] = ()


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
        macro=None,
        use_loadvar=True,
        visual_regions=(
            VisualRegion("HELLO line", "75x9+0+0", 120),
            VisualRegion("Done marker", "28x9+66+10", 30),
        ),
    ),
    "factorial": Case(
        ("FACTOR.8xp",),
        "N=5; 120; Done",
        ("eval_stmt_entry", "_FPMult", "_Disp"),
        macro=None,
        use_loadvar=True,
        # answer FACTOR's N? prompt with 5
        exec_lines=("wait 1s", "key 5", "key ENTER"),
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
    "gcflash": Case(
        ("GCFLASH.8xp",),
        "BEFORE; Garbage collecting; GC DONE; Done",
        (
            "page_3C:71f8",
            "page_3C:7219",
            "page_3C:7733",
            "page_3C:7cfb",
            "page_3C:7e0d",
            "page_3F:4c2a",
        ),
        macro=None,
        # accept the GarbageCollect confirmation prompt
        exec_lines=("wait 9s", "key 2", "key ENTER"),
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
    "asmmd5": Case(
        ("ASMMD5.8xp", "MD5TEST.8xp"),
        "BEFORE; MD5 DONE; Done; MD5Hash contains MD5(\"abc\")",
        ("_MD5Init", "_MD5Update", "_MD5Final", "md5_assist_step"),
        macro=None,  # memdump for MD5Hash is emitted automatically
        visual_regions=(
            VisualRegion("BEFORE line", "36x9+0+9", 25),
            VisualRegion("MD5 DONE line", "48x9+0+18", 50),
            VisualRegion("Done marker", "28x9+66+28", 25),
        ),
        memory_expectations=(
            MemoryExpectation(
                "MD5Hash",
                Path("/tmp/md5-abc.ram"),
                0x0292,
                bytes.fromhex("900150983cd24fb0d6963f7d28e17f72"),
            ),
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
    "asmfind": Case(
        ("ASMFIND.8xp", "ZZFIND.8xp", "ZZBASIC.8xp"),
        "ASM finds prgmZZBASIC in the VAT, returns, does not execute it",
        ("ram:9d95", "findsym_scan", "_Disp"),
        visual_regions=(
            VisualRegion("BEFORE line", "36x9+0+9", 25),
            VisualRegion("AFTER line", "30x9+0+18", 60),
            VisualRegion("unexpected third text line absent", "24x8+8+28", 0, 25),
            VisualRegion("Done marker", "28x9+66+28", 25),
        ),
    ),
    "asmparse": Case(
        ("ASMPARSE.8xp", "ZZPARSE.8xp", "ZZBASIC.8xp"),
        "ASM parser-entry probe reaches ERR:INVALID instead of executing ZZBASIC",
        ("ram:9d95", "_ParseInpLastEnt", "_ParseInp", "parseinp_find_setup", "findsym_scan", "eval_stmt_entry"),
        visual_regions=(
            VisualRegion("ERR INVALID line", "76x9+0+0", 150),
            VisualRegion("Quit line", "42x9+0+9", 80),
            VisualRegion("Goto line", "42x9+0+18", 40),
        ),
    ),
    "asmformula": Case(
        ("ASMFORM.8xp", "ZZFORM.8xp", "ZZBASIC.8xp"),
        "ASM formula-parser probe reaches ERR:UNDEFINED instead of executing ZZBASIC",
        ("ram:9d95", "_Find_Parse_Formula", "parse_init_findsym", "findsym_scan", "eval_stmt_entry"),
        visual_regions=(
            VisualRegion("ERR UNDEFINED line", "90x9+0+0", 200),
            VisualRegion("Quit line", "42x9+0+9", 80),
            VisualRegion("Goto line", "42x9+0+18", 40),
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
    "branchmatrix": Case(
        ("BRANCHES.8xp", "ZPASS.8xp"),
        "BRANCH; Done",
        ("blockmatch_end_else", "parse_scan_tokens", "_Disp"),
        macro=None,  # memdump emitted automatically from memory_expectations
        memory_expectations=(
            MemoryExpectation(
                "selected Else-body marker",
                Path("/tmp/tibasic-branchmatrix.ram"),
                0x1340,
                b"\xA5",
            ),
        ),
    ),
    "forparen": Case(
        ("FORPAREN.8xp", "ZMARK.8xp", "ZPASS.8xp"),
        "I reaches 26 and sets a RAM marker",
        ("ram:9d95",),
        macro=None,  # memdump emitted automatically from memory_expectations
        memory_expectations=(
            MemoryExpectation(
                "For( explicit-close completion marker",
                Path("/tmp/tibasic-branchmatrix.ram"),
                0x1340,
                b"\xA5",
            ),
        ),
    ),
    "forimplicit": Case(
        ("FORIMPL.8xp", "ZMARK.8xp", "ZPASS.8xp"),
        "I reaches 26 and sets a RAM marker",
        ("ram:9d95",),
        macro=None,  # memdump emitted automatically from memory_expectations
        memory_expectations=(
            MemoryExpectation(
                "For( implicit-close completion marker",
                Path("/tmp/tibasic-branchmatrix.ram"),
                0x1340,
                b"\xA5",
            ),
        ),
    ),
    "cflowlow": Case(
        ("CFLOWLO.8xp", "ZCFLOWL.8xp"),
        "OS error from below-range control-flow bcall input",
        ("page_33:435f",),
    ),
    "cflowhigh": Case(
        ("CFLOWHI.8xp", "ZCFLOWH.8xp"),
        "OS error from above-range control-flow bcall input",
        ("page_33:435f",),
    ),
    "cflowvalid": Case(
        ("CFLOWOK.8xp", "ZCFLOWV.8xp"),
        "valid control-flow table row executes",
        ("page_33:435f",),
    ),
    "cmdclose": Case(
        ("CMDCLOS.8xp", "ZCMDCLOS.8xp"),
        "command finalization explicit-close outcome",
        ("page_02:5676",),
    ),
    "cmdopen": Case(
        ("CMDOPEN.8xp", "ZCMDOPEN.8xp"),
        "command finalization open-form outcome",
        ("page_02:5676",),
    ),
    "cmdunit": Case(
        ("CMDUNIT.8xp", "ZCMDUNIT.8xp"),
        "command finalization unit-form outcome",
        ("page_02:5676",),
    ),
    "cmdbad": Case(
        ("CMDBAD.8xp", "ZCMDBAD.8xp"),
        "command finalization implicit-end and invalid-form outcomes",
        ("page_02:5676",),
    ),
    "missingend": Case(
        ("MISSEND.8xp",),
        "end-of-program cleanup with a missing End",
        ("blockmatch_end_else",),
    ),
    "terminalif": Case(
        ("TERMIF.8xp",),
        "end-of-program cleanup with a terminal nested If",
        ("blockmatch_end_else",),
    ),
    "syntaxerr": Case(
        ("SYNERR.8xp",),
        "natural ERR:SYNTAX",
        ("ram:2700",),
    ),
    "divzero": Case(
        ("DIVZERO.8xp",),
        "natural ERR:DIVIDE BY 0",
        ("ram:254b", "ram:26ec"),
    ),
    "overflow": Case(
        ("OVRFLOW.8xp",),
        "natural ERR:OVERFLOW from the 10^x input-exponent gate",
        ("page_02:7059", "ram:26e8"),
    ),
    "lndomain": Case(
        ("LNDOM.8xp",),
        "natural ERR:DOMAIN from the ln(0) zero guard",
        ("ram:212d", "ram:2131", "ram:26f4"),
    ),
    "muloverflow": Case(
        ("MULOVR.8xp",),
        "natural ERR:OVERFLOW from floating-point exponent addition",
        ("ram:251d", "ram:26e8"),
    ),
    "increment": Case(
        ("INCERR.8xp",),
        "natural ERR:INCREMENT from a zero For( step",
        ("ram:26f8",),
    ),
    "asindomain": Case(
        ("ASINDOM.8xp",),
        "natural ERR:DOMAIN from inverse sine outside [-1,1]",
        ("page_02:76f5", "ram:26f4"),
    ),
    "sqrtnonreal": Case(
        ("SQRTNEG.8xp",),
        "natural ERR:NONREAL ANSWERS from sqrt(-1) in Real mode",
        ("ram:1b93", "ram:26fc"),
    ),
    "singular": Case(
        ("SINGULAR.8xp",),
        "natural ERR:SINGULAR MAT from a rank-deficient matrix inverse",
        ("page_02:43a5", "ram:26f0"),
    ),
    "lateincrement": Case(
        ("LATEINC.8xp",),
        "natural ERR:INCREMENT when adding the default For( step makes no progress",
        ("page_38:5876", "ram:26f8"),
    ),
    "acosdomain": Case(
        ("ACOSDOM.8xp",),
        "natural ERR:DOMAIN from inverse cosine outside [-1,1]",
        ("page_02:76e2", "ram:26f4"),
    ),
    "negfactdomain": Case(
        ("NEGFACT.8xp",),
        "natural ERR:DOMAIN from a negative factorial operand",
        ("page_35:79d2", "ram:26f4"),
    ),
    "ncrdomain": Case(
        ("NCRDOM.8xp",),
        "natural ERR:DOMAIN from an invalid combination operand",
        ("page_02:4fc8", "ram:211d", "ram:26f4"),
    ),
    "gramlow": Case(
        ("GRAMLOW.8xp", "ZGRAMLOW.8xp"),
        "grammar fold below F2h",
        ("page_38:6fbc",),
    ),
    "gramhigh": Case(
        ("GRAMHIGH.8xp", "ZGRAMHI.8xp"),
        "grammar fold at F2h",
        ("page_38:6fbc",),
    ),
    "gramflag": Case(
        ("GRAMFLAG.8xp", "ZGRAMFLG.8xp"),
        "grammar flag-hook internal-entry outcome",
        ("page_38:702f",),
    ),
    "gramnonzero": Case(
        ("GRAMNZ.8xp", "ZGRAMNZ.8xp"),
        "grammar nonzero continuation internal-entry outcome",
        ("page_38:7032",),
    ),
}


def generate_loadvar_macro(dest: Path, programs: tuple[str, ...], exec_lines: tuple[str, ...] = ()) -> Path:
    """Write a macro that transfers fixtures via `loadvar` and runs the first
    PRGM > EXEC entry (fixtures sort so the driver program is first), then any
    per-case exec lines (input keys / delayed prompts)."""
    lines = [
        "# Generated by tibasic_smoke.py: load fixtures via LINK->RECEIVE",
        "# loadvar transfer, then run the first EXEC-list program.",
        "set key_hold 0.18s",
        "set key_delay 0.3s",
        "wait 4s",
        "key ON",
        "wait 3s",
        "key ENTER",
        "wait 1.6s",
        "key CLEAR",
    ]
    for program in programs:
        fixture = SAMPLES / program
        if not fixture.exists():
            raise SystemExit(f"fixture not found: {fixture}")
        lines += [
            "key 2ND",
            "wait 0.5s",
            "key GRAPHVAR",
            "wait 1.4s",
            "key RIGHT",
            "wait 0.8s",
            "key ENTER",
            "wait 2s",
            f"loadvar {fixture}",
            "wait 1s",
            "key CLEAR",
        ]
    lines += [
        "wait 0.5s",
        "key PRGM",
        "wait 1s",
        "key ENTER",
        "wait 0.8s",
        "key ENTER",
    ]
    lines.extend(exec_lines)
    lines.append("wait 8s")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def run(
    cmd: list[str], *, cwd: Path, stdout: Path | None = None,
    timeout: float | None = None,
) -> str:
    print("+", " ".join(cmd), flush=True)
    if stdout is None:
        completed = subprocess.run(
            cmd, cwd=cwd, check=True, text=True, capture_output=True,
            timeout=timeout,
        )
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        return completed.stdout

    with stdout.open("w", encoding="utf-8") as f:
        subprocess.run(cmd, cwd=cwd, check=True, stdout=f, timeout=timeout)
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
        "--initial-mapping",
        "ti84p-reset",
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


def run_case(
    name: str, case: Case, tilem: Path, rom: Path, out_dir: Path,
    keep_trace: bool, emulator_timeout: float | None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    trace = out_dir / f"{name}.trace"
    gif = out_dir / f"{name}.gif"
    first_png = out_dir / f"{name}-first.png"
    final_png = out_dir / f"{name}-final.png"
    coverage = out_dir / f"{name}.coverage.txt"

    for expectation in case.memory_expectations:
        expectation.dump.unlink(missing_ok=True)

    needs_visual = bool(
        case.min_dark_pixels
        or case.min_changed_pixels
        or case.min_distinct_frames
        or case.visual_regions
    )
    if case.use_loadvar:
        exec_lines = list(case.exec_lines)
        for expectation in case.memory_expectations:
            exec_lines.append(f"memdump {expectation.dump} ram-logical")
        macro = generate_loadvar_macro(out_dir / f"{name}.macro", case.programs, tuple(exec_lines))
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
            str(macro),
            "--trace",
            str(trace),
            "--trace-range",
            "all",
        ]
        if needs_visual:
            cmd.extend(["--headless-record", str(gif)])
        run(cmd, cwd=ROOT, timeout=emulator_timeout)
    else:
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
        ]
        if needs_visual:
            cmd.extend(["--headless-record", str(gif)])
        # Positional .8xp arguments are ignored by the current tilem-headless
        # build; legacy macros relied on them. Keep passing them for older
        # builds that still honor the loading path.
        cmd.extend(str(SAMPLES / program) for program in case.programs)
        run(cmd, cwd=ROOT, timeout=emulator_timeout)

    for expectation in case.memory_expectations:
        try:
            actual = check_memory_expectation(expectation)
        except MemoryMismatch as error:
            raise SystemExit(f"{name}: {error}") from error
        print(
            f"{name}: {expectation.name} at dump offset 0x{expectation.offset:X}: "
            f"{actual.hex()}"
        )

    if needs_visual:
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

    print(f"{name}: expected result: {case.expected}")
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
    parser.add_argument(
        "--emulator-timeout", type=float, default=300.0,
        help="wall-clock timeout per TilEm case in seconds; 0 disables it",
    )
    args = parser.parse_args()

    if args.list:
        for name, case in CASES.items():
            print(f"{name}: {' '.join(case.programs)} -> {case.expected}")
        return

    tilem = require_tilem(args.tilem or os.environ.get("TILEM"))
    rom = require_path(args.rom or os.environ.get("TI84_ROM") or DEFAULT_ROM, "ROM image")
    emulator_timeout = args.emulator_timeout or None
    selected = args.case or list(CASES)
    for name in selected:
        try:
            run_case(
                name, CASES[name], tilem, rom, args.out_dir, args.keep_trace,
                emulator_timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise SystemExit(
                f"{name}: TilEm exceeded the {args.emulator_timeout:g}s timeout"
            ) from error


if __name__ == "__main__":
    main()
