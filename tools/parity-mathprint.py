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
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM = os.path.join(ROOT, "tools", "rom.bin")
TILEM = os.path.expanduser("~/Git/tilem-headless/result/bin/tilem2")

# Each example: js expression for the model, and the calculator keystrokes that
# produce the same layout on the home entry line (after CLEAR). RIGHT leaves a
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
}

PRELUDE = ("set key_hold 0.18s\nset key_delay 0.1s\n"
           "wait 4s\nkey ON\nwait 3s\nkey ENTER\nwait 1.5s\nkey CLEAR\n")

# Template navigation keys are dropped at full key speed; settle after each.
NAV = {"RIGHT", "LEFT", "UP", "DOWN"}


def run_calc(keys, outdir, name, trace=False):
    macro = PRELUDE
    for k in keys:
        if k == "WAIT":                 # settle for a menu/template to appear
            macro += "wait 0.8s\n"
            continue
        macro += f"key {k}\n"
        if k in NAV:
            macro += "wait 0.35s\n"
    ram = os.path.join(outdir, f"{name}.ram")
    shot = os.path.join(outdir, f"{name}.png")
    # Snapshot the settled entry-line render (2-D MathPrint layout) just before
    # ENTER, as a fallback ground truth (see calc_bitmap). The memdump captures the
    # same instant's RAM state.
    macro += f"wait 0.6s\nmemdump {ram} ram-logical\nscreenshot {shot}\n"
    # press ENTER: a valid input echoes into the history as a cursor-free 2-D render
    macro += "key ENTER\nwait 1.4s\n"
    gif = os.path.join(outdir, f"{name}.gif")
    mac = os.path.join(outdir, f"{name}.macro")
    open(mac, "w").write(macro)
    cmd = [TILEM, "--headless", "--rom", ROM, "--model", "ti84p",
           "--normal-speed", "--reset", "--macro", mac, "--headless-record", gif]
    tr = os.path.join(outdir, f"{name}.trace")
    if trace:
        cmd += ["--trace", tr, "--trace-range", "all", "--trace-limit", "300000000"]
    subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    return (gif, shot), ram, (tr if trace else None)


# Documented page-0x39 anchors: which path does each construct take?
ANCHORS = {
    "4a74": "dispatch_token", "4dca": "sum_arg_widths", "4de6": "emit_arglist",
    "4e8e": "emit_glyph", "4f1a": "map_token_glyph", "5167": "layout_multiarg",
    "69c8": "compute_dims", "68ae": "layout_token_geom", "683d": "cell_to_pixel(683d)",
    "6abf": "draw_fraction_bar", "4ce9": "set_row_for_tok",
}
HANDLER_PATH = {"4dca", "4de6", "4e8e", "4f1a", "5167"}
DESCRIPTOR_PATH = {"69c8", "68ae", "683d", "6abf"}


def analyze_trace(trace):
    resolver = os.path.join(ROOT, "tools", "tilem_trace_resolve.py")
    names = os.path.join(ROOT, "tools", "names.txt")
    out = subprocess.run(["python3", resolver, trace, "--funcs",
                          "--only-space", "page_39", "--sort", "count",
                          "--names", names],
                         check=True, capture_output=True, text=True).stdout
    fired = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].startswith("page_39:"):
            addr = parts[1].split(":")[1]
            if addr in ANCHORS:
                fired[addr] = int(parts[0])
    return fired


def read_state(ram):
    d = open(ram, "rb").read()
    g = lambda a: d[a - 0x8000]
    return {a: g(a) for a in (0x85DE, 0x85E1, 0x85E2, 0x85E8, 0x85EB, 0x85EE, 0x85EF)}


def strip_cursor(grid):
    """Remove the entry-line cursor: a solid filled block (>=3 columns, each with
    a >=6-px contiguous vertical run) at the right edge, plus any blank gap before
    it. The cursor parks at the baseline, so it is not full height. No-op if
    absent (cursor off)."""
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
    while xi >= 0 and run(xi) >= 6:   # count the solid cursor block
        cnt += 1
        xi -= 1
    if cnt < 3:                       # not a cursor block
        return grid
    while xi >= 0 and not any(grid[y][xi] for y in range(h)):  # gap before cursor
        xi -= 1
    return crop([row[:xi + 1] for row in grid]) if xi >= 0 else grid


def _frame_grid(g):
    w, h = g.size
    return [[1 if g.getpixel((x, y)) < 128 else 0 for x in range(w)] for y in range(h)]


def calc_bitmap(captures):
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
    if last and not is_err:
        return crop_echo(last)
    grid = _frame_grid(Image.open(shot).convert("L"))
    if not sum(sum(r) for r in grid):
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


def calc_from_trace(trace):
    """Exact reference: reconstruct the LCD from the trace's port writes (no GIF
    capture noise) and isolate the top-left echo."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "tl", os.path.join(ROOT, "tools", "trace_lcd.py"))
    tl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tl)
    return crop_echo(tl.reconstruct(trace))


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


def js_bitmap(expr):
    code = (
        "const fs=require('fs');const mp=require(process.argv[1]+'/web/mathprint/app.js');"
        "mp.setFont(JSON.parse(fs.readFileSync(process.argv[1]+'/web/mathprint/font.json')));"
        "process.stdout.write(mp.toText(mp.parse(process.argv[2])));"
    )
    out = subprocess.run(["node", "-e", code, ROOT, expr],
                         check=True, capture_output=True, text=True).stdout
    grid = [[1 if c == "#" else 0 for c in line] for line in out.splitlines()]
    return crop(grid)


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
        parts.append("handler-record/multi-arg")
    if d:
        parts.append("descriptor/geometry")
    return " + ".join(parts) or "light entry-line"


def main():
    do_trace = "--no-trace" not in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or list(EXAMPLES)
    outdir = tempfile.mkdtemp(prefix="mp-parity-")
    print(f"artifacts in {outdir}\n")
    for name in names:
        expr, keys = EXAMPLES[name]
        shot, ram, trace = run_calc(keys, outdir, name, trace=do_trace)
        calc = calc_bitmap(shot)
        model = js_bitmap(expr)
        print(f"===== {name}: {expr} =====")
        pct, bad, dim = diff_metric(calc, model)
        print(f"calc {len(calc[0])}x{len(calc)}   model {len(model[0])}x{len(model)}"
              f"   match {pct:.1f}% ({bad} px off, {dim})")
        print(side_by_side(calc, model))
        st = read_state(ram)
        print("state: " + "  ".join(
            f"0x{a:04x}={st[a]:#04x}" for a in sorted(st)))
        if trace:
            fired = analyze_trace(trace)
            print("page-39 path: " + classify(fired))
            print("  anchors fired: " + ", ".join(
                f"{ANCHORS[a]}({fired[a]})" for a in sorted(fired)) or "none")
        print()


if __name__ == "__main__":
    main()
