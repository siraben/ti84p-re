#!/usr/bin/env python3
"""Render MathPrint examples on the real calculator and beside the layout model.

For each example this drives headless TilEm to type the expression on the home
entry line, captures the rendered entry line (ground truth), and prints it next
to the JS layout model's output (web/mathprint/app.js) so the two can be
compared pixel-for-pixel. This is the parity check behind the interactive
renderer; the keystroke map below is what makes each layout reproducible.

Requires: tools/rom.bin, a TilEm build, Pillow, node.
Usage: python3 tools/parity-mathprint.py [name ...]   (default: all)
"""
import argparse
import json
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from analyze_mathprint_records import (
    decode_record_header,
    decode_settled_expression,
)
from hardware_trace import count_resolved_trace_points, trace_header
from rom_signatures import TI84_PLUS_OS_255MP_SHA256

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM = os.environ.get("TI84_ROM", os.path.join(ROOT, "tools", "rom.bin"))
TILEM = os.path.expanduser(os.environ.get(
    "TILEM", "~/Git/tilem-headless/result/bin/tilem2"))
TILEM_SOURCE = "https://github.com/siraben/tilem-headless"
TILEM_SOURCE_COMMIT = "d1bdc58dd321ae462a701e556fcb62bb925a78b1"
TRACE_LIMIT = 300_000_000
REPORT_FIXTURES = {
    "integral": "tools/macros/mathprint-fnint.macro",
    "integral_frac": "tools/macros/mathprint-integral-fraction.macro",
}

# Each example supplies an expression for the translated record renderer and
# calculator keys that produce the same layout on the home entry line (after CLEAR).
# RIGHT leaves a
# raised/template slot. Stacked fractions use the n/d template (ALPHA YEQU 1).
EXAMPLES = {
    "x_squared":   ("X^2",            ["GRAPHVAR", "POWER", "2"]),
    "linear_half": ("1/2",            ["1", "DIV", "2"]),
    "stacked_half":("1//2",           ["ALPHA", "YEQU", "WAIT", "1", "WAIT", "1", "DOWN", "2"]),
    "sum_powers":  ("X^2+2X+1",       ["GRAPHVAR", "POWER", "2", "RIGHT", "ADD", "2",
                                        "GRAPHVAR", "ADD", "1"]),
    "radical":     ("sqrt(X^2+1)",    ["2ND", "SQUARE", "GRAPHVAR", "POWER", "2",
                                        "RIGHT", "ADD", "1"]),
    "integral":    ("int(1,2,X^2,X)", ["MATH", "9", "1", "RIGHT", "2", "RIGHT",
                                        "GRAPHVAR", "POWER", "2", "RIGHT", "RIGHT",
                                        "GRAPHVAR"]),
    "integral_frac": ("int(1,2,(1//2)X,X)",
                      # After the n/d template (cursor in the denominator), a single
                      # RIGHT exits the fraction back into the integrand, so the X is
                      # typed INSIDE the integrand: ∫((1/2)X)dX. A third RIGHT used to
                      # walk the cursor out of the integrand entirely, leaving ∫(1/2)dX
                      # times a stray X (and an ERR on ENTER).
                      ["MATH", "9", "1", "RIGHT", "2", "RIGHT",
                       "ALPHA", "YEQU", "WAIT", "1", "WAIT", "1", "DOWN", "2",
                       "RIGHT", "GRAPHVAR", "RIGHT", "GRAPHVAR"]),
    # integral_frac wrapped in parens, plus 2: exercises paren handling around a
    # template, the integral-fraction body, and a trailing additive term.
    "int_frac_plus2": ("(int(1,2,(1//2)X,X))+2",
                       ["LPAREN", "MATH", "9", "1", "RIGHT", "2", "RIGHT",
                        "ALPHA", "YEQU", "WAIT", "1", "WAIT", "1", "DOWN", "2",
                        "RIGHT", "GRAPHVAR", "RIGHT", "GRAPHVAR",
                        "RIGHT", "RPAREN", "ADD", "2"]),
    "pow_half": ("X^(1/2)", ["GRAPHVAR", "POWER", "LPAREN", "1", "DIV", "2", "RPAREN"]),
    "int_pow_half": ("int(1,2,X^(1/2),X)",
                     # ∫ slots: lo, RIGHT, hi, RIGHT, integrand, RIGHT, var. The
                     # exponent template's own exit RIGHT (after the RPAREN) leaves
                     # the cursor in the integrand; ONE more RIGHT advances to the
                     # var slot. (A third RIGHT over-walks the cursor and the calc
                     # renders a spurious wider layout.)
                     ["MATH", "9", "1", "RIGHT", "2", "RIGHT",
                      "GRAPHVAR", "POWER", "LPAREN", "1", "DIV", "2", "RPAREN",
                      "RIGHT", "RIGHT", "GRAPHVAR"]),
    "absolute": ("abs(X-3)", ["MATH", "RIGHT", "WAIT", "1", "WAIT",
                                 "GRAPHVAR", "SUB", "3", "RIGHT"]),
    "nth_root": ("nthroot(3,X+1)", ["3", "MATH", "5", "GRAPHVAR",
                                         "ADD", "1", "RIGHT"]),
    "nested_radical_fraction": (
        "sqrt(sqrt(1//2))",
        ["2ND", "SQUARE", "2ND", "SQUARE",
         "ALPHA", "YEQU", "WAIT", "1", "WAIT", "1", "DOWN", "2",
         "RIGHT", "RIGHT", "RIGHT"],
    ),
    "structural_power_exponent": (
        "X^sqrt(1//2)",
        ["GRAPHVAR", "POWER", "2ND", "SQUARE",
         "ALPHA", "YEQU", "WAIT", "1", "WAIT", "1", "DOWN", "2",
         "RIGHT", "RIGHT", "RIGHT"],
    ),
    "summation": ("sum(N,1,3,N^2)",
                  ["MATH", "0", "WAIT", "ALPHA", "LOG", "1", "RIGHT", "3",
                   "RIGHT", "ALPHA", "LOG", "POWER", "2", "RIGHT", "RIGHT"]),
}

PRELUDE = ("set key_hold 0.18s\nset key_delay 0.1s\n"
           "wait 4s\nkey ON\nwait 3s\nkey ENTER\nwait 1.5s\nkey CLEAR\n")

# Template navigation keys are dropped at full key speed; settle after each.
NAV = {"RIGHT", "LEFT", "UP", "DOWN"}
SETTLED_STRUCTURAL_ROOT_POINTER = 0x8DAF
SETTLED_EDITOR_BOUNDARY_POINTER = 0x8DB1
SETTLED_ENTRY_POINTER = 0x8DBC
SETTLED_MAIN_TAIL_POINTER = 0x8DBE
SETTLED_GAP_RECORD_POINTER = 0x8DC2
MATHPRINT_EDITOR_FLAGS = 0x89F1
SETTLED_CHILD_COUNTS = {
    0x1F: 1, 0x20: 2, 0x21: 1, 0x22: 4, 0x23: 3, 0x24: 2,
    0x25: 1, 0x26: 1, 0x27: 1, 0x28: 2, 0x29: 4, 0x2A: 1,
}


def run_calc(
    keys,
    outdir,
    name,
    trace=False,
    trace_history=False,
    *,
    key_delay=0.1,
    inter_key_wait=0.0,
):
    if key_delay == 0.1:
        macro = PRELUDE
    else:
        macro = (
            "set key_hold 0.18s\n"
            f"set key_delay {key_delay}s\n"
            "wait 4s\nkey ON\nwait 3s\nkey ENTER\nwait 1.5s\nkey CLEAR\n"
        )
    previous_key = None
    for k in keys:
        if k == "WAIT":                 # settle for a menu/template to appear
            macro += "wait 0.8s\n"
            previous_key = None
            continue
        # The OS key scanner can coalesce two adjacent presses of the same key
        # at the normal macro cadence.  Keep each requested token observable;
        # this matters for repeated digits and nested closing parentheses.
        if k == previous_key:
            macro += "wait 0.35s\n"
        macro += f"key {k}\n"
        if k in NAV:
            macro += "wait 0.35s\n"
        elif inter_key_wait:
            macro += f"wait {inter_key_wait}s\n"
        previous_key = k
    ram = os.path.join(outdir, f"{name}.ram")
    shot = os.path.join(outdir, f"{name}.png")
    # Snapshot the settled entry-line render (2-D MathPrint layout) just before
    # ENTER, as a fallback ground truth (see calc_bitmap). The memdump captures the
    # same instant's RAM state.
    macro += f"wait 0.6s\nmemdump {ram} ram-logical\nscreenshot {shot}\n"
    # A normal trace run stops on the settled entry line, keeping its coverage
    # and LCD replay scoped to entry rendering. A history trace and every
    # screenshot-only run press ENTER so the cursor-free history echo can be
    # compared against the model in the same display state.
    if not trace or trace_history:
        macro += "key ENTER\nwait 1.4s\n"
    gif = os.path.join(outdir, f"{name}.gif")
    mac = os.path.join(outdir, f"{name}.macro")
    state = os.path.join(outdir, f"{name}.state")
    open(mac, "w").write(macro)
    cmd = [TILEM, "--headless", "--rom", ROM, "--model", "ti84p",
           "--state-file", state, "--normal-speed", "--reset", "--macro", mac,
           "--headless-record", gif]
    tr = os.path.join(outdir, f"{name}.trace")
    if trace:
        cmd += ["--trace", tr, "--trace-range", "all", "--trace-limit", str(TRACE_LIMIT)]
    try:
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True,
                                   timeout=180)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "no process output").strip()
        raise RuntimeError(f"TilEm failed: {detail}") from error
    if "trace limit" in completed.stderr.lower():
        raise RuntimeError("TilEm trace limit reached; refusing a partial replay")
    if trace and (not os.path.isfile(tr) or os.path.getsize(tr) == 0):
        raise RuntimeError("TilEm did not produce the requested trace")
    if trace:
        header = trace_header(Path(tr))
        if (header.version, header.range_start, header.range_end) != (
            2, 0, 0xFFFF
        ):
            raise RuntimeError(
                "TilEm trace is not a full-range TLMT v2 capture: "
                f"version={header.version} range={header.range_start:#x}-"
                f"{header.range_end:#x}"
            )
    return (gif, shot), ram, (tr if trace else None), mac


# Documented page-0x39 anchors: which path does each construct take?
ANCHORS = {
    "4a74": "dispatch_token", "4ca4": "emit_subexpr2",
    "4dca": "sum_arg_widths", "4de6": "emit_arglist",
    "4e8e": "emit_glyph", "4f1a": "map_token_glyph",
    "5167": "layout_multiarg", "5949": "arg_kind",
    "5b10": "emit_saved_operand", "5b1d": "emit_saved_variable",
    "69c8": "compute_dims", "68ae": "layout_token_geom",
    "683d": "descriptor_cell_to_pixel", "6abf": "focus_rectangle",
    "4ce9": "set_row_for_tok",
}
HANDLER_PATH = {"4ca4", "4dca", "4de6", "4e8e", "4f1a"}
DESCRIPTOR_PATH = {"69c8", "68ae", "683d", "6abf"}


def analyze_trace(trace):
    points = {("page_39", int(address, 16)) for address in ANCHORS}
    report = count_resolved_trace_points(
        Path(trace), points, initial_mapping="ti84p-reset"
    )
    fired = {
        f"{address:04x}": count
        for (space, address), count in report.counts.items()
        if space == "page_39" and count
    }
    return fired, report.processed_instructions


def read_state(ram):
    d = open(ram, "rb").read()
    g = lambda a: d[a - 0x8000]
    return {a: g(a) for a in (0x85DE, 0x85E1, 0x85E2, 0x85E8, 0x85EB, 0x85EE, 0x85EF)}


def strip_cursor(grid):
    """Remove a verified MathPrint cursor at the right edge and its gap.

    The editor exposes both five-/six-row solid blocks and a five-by-three
    template-exit shape. The short shape is matched exactly and requires two
    blank separator columns, so an ordinary rightmost glyph is retained.
    """
    if not grid or not grid[0]:
        return grid
    h, w = len(grid), len(grid[0])

    def run(x):                       # longest vertical run of 1s in column x
        best = cur = 0
        for y in range(h):
            cur = cur + 1 if grid[y][x] else 0
            best = max(best, cur)
        return best

    x = w - 1
    while x >= 0 and not any(grid[y][x] for y in range(h)):  # skip trailing blanks
        x -= 1
    cnt = 0
    xi = x
    while xi >= 0 and run(xi) >= 5:   # count the solid cursor block
        cnt += 1
        xi -= 1
    if cnt >= 3:
        while xi >= 0 and not any(grid[y][xi] for y in range(h)):
            xi -= 1
        return crop([row[:xi + 1] for row in grid]) if xi >= 0 else grid

    # A live logBASE template trace ends with this right-edge cursor:
    #
    #     #####
    #     #####
    #      ####
    #
    # Require its exact bounding box and two blank columns before it. This is
    # deliberately narrower than generic connected-component removal.
    left = x - 4
    if left < 2:
        return grid
    rows = [
        y for y in range(h)
        if any(grid[y][column] for column in range(left, x + 1))
    ]
    if len(rows) != 3 or rows != list(range(rows[0], rows[0] + 3)):
        return grid
    masks = [
        tuple(grid[y][column] for column in range(left, x + 1))
        for y in rows
    ]
    if masks != [(1, 1, 1, 1, 1), (1, 1, 1, 1, 1), (0, 1, 1, 1, 1)]:
        return grid
    if any(grid[y][column] for y in range(h) for column in (left - 2, left - 1)):
        return grid
    xi = left - 3
    while xi >= 0 and not any(grid[y][xi] for y in range(h)):
        xi -= 1
    return crop([row[:xi + 1] for row in grid]) if xi >= 0 else grid


def _frame_grid(g):
    w, h = g.size
    return [[1 if g.getpixel((x, y)) < 128 else 0 for x in range(w)] for y in range(h)]


def calc_bitmap(
    captures,
    *,
    preserve_internal_gaps=False,
    require_history=False,
    expected_size=None,
):
    """Return the cursor-free 2-D ground-truth render for the diff.

    `captures` is (gif, shot). Normally we read the post-ENTER history echo from
    the GIF: a valid input re-renders into the history as a cursor-free 2-D layout
    at the top-left, which is exactly what the JS model represents. But if the
    expression evaluates to an error (e.g. a fraction inside the integral body),
    pressing ENTER pops an ERR dialog instead of echoing, so the GIF's last frame
    is that dialog, not the layout. In that case fall back to the entry-line
    screenshot captured just before ENTER (the layout is identical there; for the
    erroring example the cursor has already left the templates, so it is clean)."""
    from PIL import Image, ImageSequence
    gif, shot = captures
    im = Image.open(gif)
    last = None
    for f in ImageSequence.Iterator(im):
        grid = _frame_grid(f.convert("L"))
        if sum(sum(r) for r in grid):
            last = grid
    # ERR dialog signature: the "1:Quit / 2:Goto" menu fills the bottom-left rows,
    # which a 1-3 line echo+result never does (>=40 vs <=25 px in rows 17-22).
    is_err = last and sum(last[y][x] for y in range(17, 23)
                          for x in range(45)) >= 40
    if last and preserve_internal_gaps and expected_size is not None:
        return crop_expected_history(last, expected_size)
    if last and not is_err:
        return crop_top_block(last) if preserve_internal_gaps else crop_echo(last)
    if require_history:
        raise RuntimeError("calculator did not produce a post-ENTER history render")
    grid = _frame_grid(Image.open(shot).convert("L"))
    if not sum(sum(r) for r in grid):
        return [[0]]
    grid = strip_cursor(grid)
    return crop_top_block(grid) if preserve_internal_gaps else crop_echo(grid)


def calc_entry_bitmap(captures):
    """Return the cursor-free entry line from the pre-ENTER screenshot."""
    from PIL import Image
    _gif, shot = captures
    grid = _frame_grid(Image.open(shot).convert("L"))
    if not sum(sum(row) for row in grid):
        return [[0]]
    return crop_echo(strip_cursor(grid))


def crop_echo(grid):
    """Isolate the top-left history echo: split at the wide column gap before the
    right-aligned result and the row gap before lower lines."""
    h, w = len(grid), len(grid[0])
    col_has = [any(grid[y][x] for y in range(h)) for x in range(w)]
    x0 = next((x for x in range(w) if col_has[x]), 0)
    xr = w
    blank = 0
    for x in range(x0, w):
        blank = blank + 1 if not col_has[x] else 0
        if blank >= 8:
            xr = x - blank + 1
            break
    left = [row[:xr] for row in grid]
    row_has = [any(left[y]) for y in range(h)]
    y0 = next((y for y in range(h) if row_has[y]), 0)
    yb = h
    blank = 0
    for y in range(y0, h):
        blank = blank + 1 if not row_has[y] else 0
        if blank >= 2:
            yb = y - blank + 1
            break
    return crop([row for row in left[:yb]])


def crop_top_block(grid):
    """Crop the first history block without splitting wide internal columns."""
    row_has = [any(row) for row in grid]
    y0 = next((y for y, occupied in enumerate(row_has) if occupied), 0)
    yb = len(grid)
    blank = 0
    for y in range(y0, len(grid)):
        blank = blank + 1 if not row_has[y] else 0
        if blank >= 2:
            yb = y - blank + 1
            break
    return crop(grid[:yb])


def crop_expected_history(grid, expected_size):
    """Return a history block only when its full expected extent is visible."""
    block = crop_top_block(grid)
    expected_width, expected_height = expected_size
    actual_size = (len(block[0]), len(block))
    if actual_size != expected_size:
        raise RuntimeError(
            "calculator history render is clipped or incomplete: "
            f"expected {expected_width}x{expected_height}, "
            f"observed {actual_size[0]}x{actual_size[1]}"
        )
    return block


def calc_from_trace(trace, *, preserve_internal_gaps=False, expected_size=None):
    """Replay the settled entry line from the trace and remove its cursor."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "tl", os.path.join(ROOT, "tools", "trace_lcd.py"))
    tl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tl)
    grid = strip_cursor(tl.reconstruct(trace))
    if preserve_internal_gaps and expected_size is not None:
        return crop_expected_history(grid, expected_size)
    return crop_top_block(grid) if preserve_internal_gaps else crop_echo(grid)


def crop(grid):
    rows = [r for r in grid if any(r)]
    if not rows:
        return [[0]]
    h = len(grid)
    ys = [y for y in range(h) if any(grid[y])]
    top, bot = ys[0], ys[-1] + 1
    w = len(grid[0])
    xs = [x for x in range(w) if any(grid[y][x] for y in range(top, bot))]
    left, right = xs[0], xs[-1] + 1
    return [row[left:right] for row in grid[top:bot]]


def js_bitmap(expr, *, generated=False):
    """Render either the preview compositor or translated settled-record path."""
    render = (
        "const result=mp.generatedForExpression(process.argv[2]);"
        "if(!result)throw new Error('expression has no translated record program');"
        "process.stdout.write(result.settledFinal.map(row=>"
        "Array.from(row,value=>Number(value)?'#':'.').join('')).join('\\n'));"
        if generated else
        "process.stdout.write(mp.toText(mp.parse(process.argv[2])));"
    )
    code = (
        "const fs=require('fs');const mp=require(process.argv[1]+'/web/mathprint/app.js');"
        "mp.setFont(JSON.parse(fs.readFileSync(process.argv[1]+'/web/mathprint/font.json')));" +
        render
    )
    out = subprocess.run(["node", "-e", code, ROOT, expr],
                         check=True, capture_output=True, text=True).stdout
    grid = [[1 if c == "#" else 0 for c in line] for line in out.splitlines()]
    return crop(grid)


def js_render_spec(spec):
    """Return a semantic AST's translated bitmap, native tokens, and graph AST."""
    code = (
        "const fs=require('fs');"
        "const root=process.argv[1];"
        "const mp=require(root+'/web/mathprint/app.js');"
        "const rom=require(root+'/web/mathprint/rom-engine.js');"
        "const font=JSON.parse(fs.readFileSync(root+'/web/mathprint/font.json'));"
        "mp.setFont(font);"
        "rom.setSettledTokenStrings(JSON.parse("
        "fs.readFileSync(root+'/web/mathprint/token-strings.json')));"
        "const spec=JSON.parse(process.argv[2]);"
        "const native=rom.encodeSettledExpressionTokens(spec);"
        "const program=rom.constructSettledProgramFromTokens(native,1,font);"
        "const result=mp.generateRecordProgram(program,{editor:true});"
        "const expression=rom.decodeSettledExpressionGraph("
        "program.nodes,program.entry_id);"
        "process.stdout.write(JSON.stringify({native,expression,final:result.settledFinal}));"
    )
    out = subprocess.run(
        ["node", "-e", code, ROOT, json.dumps(spec, separators=(",", ":"))],
        check=True, capture_output=True, text=True,
    ).stdout
    rendered = json.loads(out)
    grid = [[1 if int(value) else 0 for value in row]
            for row in rendered["final"]]
    return crop(grid), bytes(rendered["native"]), rendered["expression"]


def js_bitmap_spec(spec):
    """Render a semantic AST through native-byte encoding and record construction."""
    return js_render_spec(spec)[0]


def calculator_settled_program(ram_path):
    """Decode the calculator's final settled graph from a RAM dump.

    ``34:4ACE`` walks structural records from ``0x8DAF`` to ``0x8DBC``.
    ``34:4A83`` walks leaf/editor records from ``0x8DBC`` and substitutes the
    live edit gap when ``(IY+1).2`` is set. This mirrors both ROM walks instead
    of assuming the live graph is one contiguous settled-record array.
    """
    memory = Path(ram_path).read_bytes()
    if len(memory) < 0x8000:
        raise ValueError("RAM dump does not contain the logical 0x8000–0xFFFF window")
    logical = memory[:0x8000]

    def word(address):
        if not 0x8000 <= address <= 0xFFFE:
            raise ValueError(f"RAM word address 0x{address:04X} is outside the logical window")
        offset = address - 0x8000
        return logical[offset] | logical[offset + 1] << 8

    structural_start = word(SETTLED_STRUCTURAL_ROOT_POINTER)
    entry_pointer = word(SETTLED_ENTRY_POINTER)
    main_tail = word(SETTLED_MAIN_TAIL_POINTER)
    if not (0x8000 <= structural_start <= entry_pointer <= main_tail <= 0x10000):
        raise ValueError(
            "settled graph pointers are inconsistent: "
            f"structural=0x{structural_start:04X}, entry=0x{entry_pointer:04X}, "
            f"main-tail=0x{main_tail:04X}"
        )

    def active_edit_payload():
        edit_top, edit_cursor, edit_tail, edit_bottom = (
            word(address) for address in (0x96F4, 0x96F6, 0x96F8, 0x96FA)
        )
        if not (0x8000 <= edit_top <= edit_cursor <= 0x10000):
            raise ValueError("home editor left-segment pointers are inconsistent")
        if not (0x8000 <= edit_tail <= edit_bottom <= 0x10000):
            raise ValueError("home editor right-segment pointers are inconsistent")
        left = logical[edit_top - 0x8000:edit_cursor - 0x8000]
        right = logical[edit_tail - 0x8000:edit_bottom - 0x8000]
        return list(left + right)

    def node_from(decoded, pointer):
        return {
            "record_id": decoded.record_id,
            "render_type": decoded.render_type,
            "word03": decoded.word03,
            "word05": decoded.word05,
            "word07": decoded.word07,
            "word09": decoded.word09,
            "word0B": decoded.word0B,
            "word0D": decoded.word0D,
            "word0F": decoded.word0F,
            "word11": decoded.word11,
            "byte13": decoded.byte13,
            "child_ids": [],
            "payload": [],
            "pointer": pointer,
        }

    nodes = []
    pointer = structural_start
    while pointer < entry_pointer:
        offset = pointer - 0x8000
        if pointer + 0x14 > entry_pointer:
            raise ValueError(
                f"structural record at 0x{pointer:04X} has a truncated header"
            )
        decoded = decode_record_header(tuple(logical[offset:offset + 0x14]))
        node = node_from(decoded, pointer)
        if decoded.render_type < 0x1F:
            raise ValueError(
                f"record 0x{decoded.record_id:04X} before the entry boundary "
                f"has leaf type 0x{decoded.render_type:02X}"
            )
        if decoded.render_type == 0x2B:
            semantic_children = decoded.byte13 * (decoded.word11 >> 8)
            physical_children = semantic_children + 1
            if not semantic_children or semantic_children > 0xFF:
                raise ValueError(
                    f"settled matrix record 0x{decoded.record_id:04X} has "
                    f"invalid dimensions {decoded.byte13}x{decoded.word11 >> 8}"
                )
        else:
            try:
                semantic_children = SETTLED_CHILD_COUNTS[decoded.render_type]
            except KeyError as error:
                raise ValueError(
                    f"settled record 0x{decoded.record_id:04X} has unsupported "
                    f"type 0x{decoded.render_type:02X}"
                ) from error
            physical_children = semantic_children
        size = 0x14 + 2 * physical_children
        node["child_ids"] = [
            word(pointer + 0x14 + 2 * index)
            for index in range(semantic_children)
        ]
        if pointer + size > entry_pointer:
            raise ValueError(
                f"structural record 0x{decoded.record_id:04X} at 0x{pointer:04X} "
                f"extends past entry boundary 0x{entry_pointer:04X}"
            )
        nodes.append(node)
        pointer += size

    if pointer != entry_pointer:
        raise ValueError(
            f"structural record walk ended at 0x{pointer:04X}, "
            f"not entry 0x{entry_pointer:04X}"
        )
    gap_active = bool(logical[MATHPRINT_EDITOR_FLAGS - 0x8000] & 0x04)
    leaf_boundary = word(SETTLED_EDITOR_BOUNDARY_POINTER) \
        if gap_active else main_tail
    gap_record = word(SETTLED_GAP_RECORD_POINTER)
    if not (entry_pointer < leaf_boundary <= 0x10000):
        raise ValueError(
            f"editor record boundary 0x{leaf_boundary:04X} does not follow "
            f"entry 0x{entry_pointer:04X}"
        )

    pointer = entry_pointer
    visited_pointers = set()
    while pointer < leaf_boundary:
        if pointer in visited_pointers:
            raise ValueError(f"editor record walk cycles at 0x{pointer:04X}")
        visited_pointers.add(pointer)
        if not 0x8000 <= pointer <= 0xFFEC:
            raise ValueError(f"editor record pointer 0x{pointer:04X} is out of range")
        offset = pointer - 0x8000
        decoded = decode_record_header(tuple(logical[offset:offset + 0x14]))
        if decoded.render_type >= 0x1F:
            raise ValueError(
                f"editor record 0x{decoded.record_id:04X} has structural "
                f"type 0x{decoded.render_type:02X}"
            )
        node = node_from(decoded, pointer)
        if gap_active and pointer == gap_record:
            node["payload"] = active_edit_payload()
            next_pointer = word(0x96FA)
        else:
            payload_end = offset + 0x13 + decoded.word11
            node["payload"] = list(logical[offset + 0x13:payload_end])
            next_pointer = pointer + 0x13 + decoded.word11
        if not node["payload"]:
            raise ValueError(
                f"editor leaf record 0x{decoded.record_id:04X} has an empty payload"
            )
        node["byte13"] = node["payload"][0]
        if next_pointer <= pointer:
            raise ValueError(
                f"editor record 0x{decoded.record_id:04X} does not advance"
            )
        nodes.append(node)
        pointer = next_pointer

    by_pointer = {node["pointer"]: node for node in nodes}
    if len(by_pointer) != len(nodes):
        raise ValueError("settled graph contains duplicate record pointers")
    if entry_pointer not in by_pointer:
        raise ValueError(
            f"settled entry pointer 0x{entry_pointer:04X} is not a record boundary"
        )
    entry_id = by_pointer[entry_pointer]["record_id"]
    expression = decode_settled_expression(nodes, entry_id)
    return {
        "structural_start": structural_start,
        "main_tail": main_tail,
        "leaf_boundary": leaf_boundary,
        "gap_active": gap_active,
        "entry_pointer": entry_pointer,
        "entry_id": entry_id,
        "nodes": nodes,
        "expression": expression,
    }


def show(grid):
    return ["".join("█" if c else " " for c in r) for r in grid]


def diff_metric(a, b):
    """Overlay top-left aligned; return (match_pct, mismatched_pixels, dimstr)."""
    h = max(len(a), len(b))
    w = max(len(a[0]) if a else 0, len(b[0]) if b else 0)
    bad = same = 0
    for y in range(h):
        for x in range(w):
            va = a[y][x] if y < len(a) and x < len(a[y]) else 0
            vb = b[y][x] if y < len(b) and x < len(b[y]) else 0
            if va == vb:
                same += 1
            else:
                bad += 1
    tot = same + bad or 1
    dim = "dims match" if (len(a), len(a[0])) == (len(b), len(b[0])) else \
        f"dims {len(a[0])}x{len(a)} vs {len(b[0])}x{len(b)}"
    return 100.0 * same / tot, bad, dim


def side_by_side(a, b):
    sa, sb = show(a), show(b)
    wa = max((len(r) for r in sa), default=0)
    h = max(len(sa), len(sb))
    out = []
    for i in range(h):
        la = sa[i] if i < len(sa) else ""
        lb = sb[i] if i < len(sb) else ""
        out.append(f"{la:<{wa}}   |   {lb}")
    return "\n".join(out)


def classify(fired):
    h = [a for a in fired if a in HANDLER_PATH]
    d = [a for a in fired if a in DESCRIPTOR_PATH]
    parts = []
    if h:
        parts.append("handler-record/subexpression")
    if d:
        parts.append("descriptor/geometry")
    return " + ".join(parts) or "light entry-line"


def validate_inputs():
    if not os.path.isfile(TILEM):
        raise SystemExit(f"TilEm executable not found: {TILEM} (set TILEM)")
    if not os.path.isfile(ROM):
        raise SystemExit(f"ROM image not found: {ROM} (set TI84_ROM)")
    digest = hashlib.sha256(open(ROM, "rb").read()).hexdigest()
    if digest != TI84_PLUS_OS_255MP_SHA256:
        raise SystemExit(
            f"ROM SHA-256 mismatch: expected {TI84_PLUS_OS_255MP_SHA256}, got {digest}"
        )
    return digest, hashlib.sha256(open(TILEM, "rb").read()).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", choices=EXAMPLES)
    parser.add_argument("--no-trace", action="store_true")
    parser.add_argument(
        "--trace-history",
        action="store_true",
        help="press ENTER during trace capture and compare the history echo",
    )
    parser.add_argument(
        "--report",
        metavar="PATH",
        help="write a machine-readable report (requires trace capture)",
    )
    args = parser.parse_args()
    if args.report and args.no_trace:
        parser.error("--report requires trace capture")
    if args.trace_history and args.no_trace:
        parser.error("--trace-history cannot be combined with --no-trace")
    if args.trace_history and args.report:
        parser.error("--trace-history cannot update the entry-line trace report")
    return args


def main():
    args = parse_args()
    rom_digest, tilem_digest = validate_inputs()
    do_trace = not args.no_trace
    names = args.names or list(EXAMPLES)
    outdir = tempfile.mkdtemp(prefix="mp-parity-")
    print(f"ROM SHA-256: {rom_digest}")
    print(f"TilEm executable SHA-256: {tilem_digest}")
    print(f"artifacts in {outdir}\n")
    mismatches = 0
    scenarios = {}
    for name in names:
        expr, keys = EXAMPLES[name]
        shot, ram, trace, generated_macro = run_calc(
            keys,
            outdir,
            name,
            trace=do_trace,
            trace_history=args.trace_history,
        )
        calc = calc_from_trace(trace) if trace else calc_bitmap(shot)
        model = js_bitmap(expr, generated=True)
        print(f"===== {name}: {expr} =====")
        pct, bad, dim = diff_metric(calc, model)
        mismatches += bool(bad)
        print(f"calc {len(calc[0])}x{len(calc)}   model {len(model[0])}x{len(model)}"
              f"   match {pct:.1f}% ({bad} px off, {dim})")
        print(side_by_side(calc, model))
        st = read_state(ram)
        print("state: " + "  ".join(
            f"0x{a:04x}={st[a]:#04x}" for a in sorted(st)))
        if trace:
            fired, instructions = analyze_trace(trace)
            print("page-39 path: " + classify(fired))
            rendered_hits = ", ".join(
                f"{ANCHORS[a]}({fired[a]})" for a in sorted(fired)
            )
            print("  exact entry hits: " + (rendered_hits or "none"))
            fixture = REPORT_FIXTURES.get(name)
            scenarios[name] = {
                "expression": expr,
                "key_sequence": keys,
                "fixture": fixture,
                "fixture_sha256": (
                    sha256_file(os.path.join(ROOT, fixture)) if fixture else None
                ),
                "generated_macro_sha256": sha256_file(generated_macro),
                "trace_bytes": os.path.getsize(trace),
                "trace_sha256": sha256_file(trace),
                "instructions": instructions,
                "lcd_replay": {
                    "calculator_size": [len(calc[0]), len(calc)],
                    "model_size": [len(model[0]), len(model)],
                    "mismatched_pixels": bad,
                },
                "state": {f"0x{address:04X}": f"0x{value:02X}"
                          for address, value in sorted(st.items())},
                "exact_page_39_entry_hits": {
                    f"39:{address.upper()}": fired.get(address, 0)
                    for address in ANCHORS
                },
            }
        print()
    if mismatches:
        raise SystemExit(1)
    if args.report:
        report = {
            "schema": 2,
            "rom": {
                "model": "ti84p",
                "os": "2.55MP",
                "sha256": rom_digest,
            },
            "tilem": {
                "source": TILEM_SOURCE,
                "commit": TILEM_SOURCE_COMMIT,
                "executable_sha256": tilem_digest,
            },
            "capture": {
                "format": "TLMT v2",
                "range": "all",
                "trace_limit_bytes": TRACE_LIMIT,
                "initial_mapping": "ti84p-reset",
                "raw_traces": (
                    "generated outside the repository because each retained "
                    "scenario trace is larger than 150 MB"
                ),
                "reproduce": (
                    "TILEM=$PWD/result/bin/tilem2 TI84_ROM=$PWD/tools/rom.bin "
                    "python3 tools/parity-mathprint.py integral integral_frac "
                    "--report tools/mathprint-trace-report.json"
                ),
            },
            "scenarios": scenarios,
            "resolver_caution": (
                "Function rollups assign instructions to the nearest preceding "
                "symbol. Use exact_page_39_entry_hits for routine-entry claims."
            ),
        }
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(f"wrote report: {args.report}")


if __name__ == "__main__":
    main()
