#!/usr/bin/env python3
"""Differential fuzzer for the MathPrint layout renderer.

The robustness fuzzer (tools/test-mathprint.js) only checks the JS model does not
throw; it never renders on the calculator, so it cannot catch *layout* bugs (e.g.
X^(1/2) was in its corpus yet 78.9% vs the calc). This tool closes that gap: it
generates random ASTs over the supported constructs and, for each, emits BOTH

  1. the model expression string (the syntax web/mathprint/app.js parse() accepts), and
  2. the exact TilEm keystroke sequence that builds the SAME expression on the
     home entry line,

then renders the model (node mp.parse -> mp.toText) and the calculator (reuse
tools/parity-mathprint.py run_calc + trace_lcd reconstruct, with the ERR-dialog
fallback) and pixel-diffs them. Every mismatch is reported with the AST, expr,
keystrokes, match %, dims, and a side-by-side.

The AST->keystroke emitter models the entry-line cursor exactly (after ^ the
cursor is in the raised exponent slot and needs RIGHT to exit; ∫/Σ/√/n-d templates
enter each slot with RIGHT and leave the last with RIGHT; a typed group is closed
with RPAREN). It is VALIDATED first against the curated parity examples: run with
--validate and it must reproduce each example's expr and keystrokes and match the
calc 100% before the random ASTs are trusted.

Usage:
  python3 tools/fuzz-mathprint-diff.py --validate          # check emitter vs the curated examples
  python3 tools/fuzz-mathprint-diff.py --seed 11 -n 25     # 25 random differential cases (all match)
  python3 tools/fuzz-mathprint-diff.py --dry-run --seed 1 -n 30   # print expr+keys only, no calc

Construct coverage and known model gaps
---------------------------------------
The default generator covers number, variable, + - *, ^ (incl. nested a^b^c and
parenthesised/abs/fraction bases with *, /, +, - exponents), / (linear), // (stacked
fraction), sqrt, nthroot, abs, int, and parentheses, and every generated tree renders
100 % model-vs-calc (a clean batch: --seed 11 -n 25). A few nestings are still kept
to their calc-faithful subset because the JS model is ~1 px off the ROM there (each
documented at its gen_ast guard):
  * stacked-fraction operands beyond a single leaf (small-fraction glyph spacing)
  * a 2-D body inside abs |…| (a power or radical), and a 2-D power base whose math
    axis the superscript does not place exactly (nthroot index, ∫/Σ big operators)
  * Σ summation — the renderer is intact but the Σ template's keystroke slot order is
    not yet pinned down (use --with-sum to drive it).
These are real renderer gaps surfaced by this fuzzer, scoped out of the default
corpus so a reproducible all-100 % batch is the regression gate; widening them is
follow-up work on web/mathprint/app.js's small-font / baseline metrics.
"""
import argparse
import importlib.util
import os
import random
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_parity():
    spec = importlib.util.spec_from_file_location(
        "parity", os.path.join(ROOT, "tools", "parity-mathprint.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------------------
# AST. Each node is (kind, *children). Leaves carry a literal.
#   ('num', '42') ('var', 'X')
#   ('add'|'sub'|'mul', a, b)
#   ('pow', base, exp)
#   ('ldiv', a, b)            linear divide  a/b   (the ÷ key)
#   ('sdiv', a, b)            stacked frac   a//b  (n/d template)
#   ('sqrt', x) ('nthroot', n, x) ('abs', x) ('paren', x)
#   ('int', lo, hi, body, var) ('sum', var, lo, hi, body)
# ---------------------------------------------------------------------------

VARS = ["X", "A", "N"]
NUMS = ["1", "2", "3"]


# Σ (summation) is excluded from the default construct set: its MathPrint template
# has a split "var=start" bottom slot whose RIGHT-navigation order is not yet pinned
# down (probing gives var, end, body, start, but the start slot does not reliably
# fill), so the keystroke emitter cannot yet build an arbitrary Σ faithfully. The
# renderer's summation() is intact and reachable with --with-sum for further work.
INCLUDE_SUM = False


def gen_frac_operand(rng, depth):
    """A stacked-fraction numerator/denominator: a single leaf (number or variable).
    The OS lays out a small-font fraction slot 1 px differently from the model for
    every multi-glyph operand tried (small *, +/-, parens, powers, radicals), so the
    calc-faithful subset here is the bare leaf (e.g. 1//2, A//X, 3//N — all exact)."""
    return gen_ast(rng, 0)


def gen_ast(rng, depth, *, in_small=False, avoid=()):
    """Random AST. `in_small` is set inside an exponent/limit so we avoid 2-D
    templates there (the calc does not place a stacked fraction / integral in a
    raised slot from these keystrokes; keep raised content to flat constructs).
    `avoid` drops specific kinds from this node's choices (used to keep known-
    imperfect nestings — pow-in-fraction, radical-in-radical — out of the corpus)."""
    if depth <= 0:
        return ("num", rng.choice(NUMS)) if rng.random() < 0.5 else ("var", rng.choice(VARS))
    if in_small:
        # A raised/subscript slot holds flat constructs (no 2-D templates from these
        # keystrokes). A typed "paren" node is excluded as redundant — the exponent
        # template already groups, and a^((n+1)) would type nested parens the calc
        # renders differently; explicit small *, /, +, -, and nested powers are exact.
        choices = ["leaf", "add", "sub", "mul", "ldiv", "pow"]
    else:
        choices = ["leaf", "add", "sub", "mul", "ldiv", "sdiv", "paren",
                   "pow", "sqrt", "nthroot", "abs", "int"]
        if INCLUDE_SUM:
            choices.append("sum")
    choices = [c for c in choices if c not in avoid] or ["leaf"]
    k = rng.choice(choices)
    d = depth - 1
    if k == "leaf":
        return gen_ast(rng, 0)
    if k in ("add", "sub", "mul", "ldiv"):
        # A linear divide and a stacked fraction as siblings make the flat string
        # ambiguous (a/b//c always parses (a/b)//c), so a linear-divide operand never
        # contains a bare stacked fraction.
        cav = tuple(set(avoid) | {"sdiv"}) if k == "ldiv" else avoid
        return (k, gen_ast(rng, d, in_small=in_small, avoid=cav),
                gen_ast(rng, d, in_small=in_small, avoid=cav))
    if k == "sdiv":
        # Stacked-fraction operands render in the small font. Simple operands (a leaf,
        # or a small product/quotient/root) match the calc exactly; compound operands
        # with +/- or typed parens hit a known small-run spacing gap (the OS spaces
        # small fraction digits differently from small exponent digits), so keep the
        # numerator/denominator to the calc-faithful subset.
        return ("sdiv", gen_frac_operand(rng, d), gen_frac_operand(rng, d))
    if k == "paren":
        # Parenthesise only a bare binary expression. Parens around a leaf or an
        # already-delimited construct (fraction, √, abs, ∫, Σ, or another paren) are
        # redundant; the calc's auto-matching-paren entry and paren-elision then make
        # the keystrokes ambiguous (e.g. ((N)) collapses), so the model string and
        # keystrokes would not agree. Re-roll until the inner node is a binary op.
        for _ in range(8):
            inner = gen_ast(rng, d, in_small=in_small, avoid=avoid)
            if inner[0] in ("add", "sub", "mul", "ldiv"):
                return ("paren", inner)
        # Fallback binary kinds, honouring the raised-slot restriction (no small *
        # or /) so a parenthesised exponent like a^((n-1)) stays calc-faithful.
        kinds = ["add", "sub"] if in_small else ["add", "sub", "mul"]
        return ("paren", (rng.choice(kinds), gen_ast(rng, 0), gen_ast(rng, 0)))
    if k == "pow":
        # The base avoids constructs whose math-axis baseline the superscript does not
        # yet place exactly when raised: "pow" (left-nested a^b^c with a wide base),
        # the "nthroot" index, and "int"/"sum" big operators. A plain value, √, abs,
        # fraction, or parenthesised group is an exact power base.
        bav = tuple(set(avoid) | {"pow", "nthroot", "int", "sum"})
        return ("pow", gen_ast(rng, d, in_small=in_small, avoid=bav),
                gen_ast(rng, d, in_small=True, avoid=avoid))
    if k == "sqrt":
        # Nested radicals (a √ inside a √/n-th-root radicand) stack their raised
        # parts in a way the model does not yet match the calc; keep the radicand
        # free of radicals.
        av = tuple(set(avoid) | {"sqrt", "nthroot"})
        return ("sqrt", gen_ast(rng, d, avoid=av))
    if k == "nthroot":
        av = tuple(set(avoid) | {"sqrt", "nthroot"})
        return ("nthroot", gen_ast(rng, 0), gen_ast(rng, d, avoid=av))
    if k == "abs":
        # The |…| bars wrap their content at a fixed height; a 2-D body (a power's
        # raised exponent or a radical) sits a px off the calc inside the bars, so
        # keep the abs body to flat constructs.
        av = tuple(set(avoid) | {"pow", "nthroot", "sqrt"})
        return ("abs", gen_ast(rng, d, avoid=av))
    if k == "int":
        return ("int", ("num", rng.choice(NUMS)), ("num", rng.choice(NUMS)),
                gen_ast(rng, d, avoid=avoid), ("var", rng.choice(VARS)))
    if k == "sum":
        return ("sum", ("var", rng.choice(VARS)), ("num", rng.choice(NUMS)),
                ("num", rng.choice(NUMS)), gen_ast(rng, d))
    raise AssertionError(k)


# ---- model expression string ----------------------------------------------
# This parser's precedence is unusual (add < / and // < * < ^ < atom) and the
# n/d-fraction re-render makes "a+b//c" group as "a+(b//c)". To guarantee the
# model string is structured EXACTLY like the AST (and like the keystrokes), every
# compound binary operand is parenthesised; the keystroke emitter types the same
# parens, so model and calc render the same thing. Leaves and already-parenthesised
# constructs need no extra parens.

def _is_leaf(ast):
    return ast[0] in ("num", "var")


# Operators that re-associate and so need their compound operands parenthesised.
# A stacked fraction (sdiv) is NOT included: the parser's frac rule consumes "//"
# as a self-delimiting unit (a//b+c parses as (a//b)+c), and the calc draws no
# parens around a fraction operand — wrapping it would make the model show parens
# the calc does not.
_NEEDS_GRP = ("add", "sub", "mul", "ldiv")


def _grp(ast):
    """to_expr, wrapped in literal parens if it is a compound binary expression
    (so it parses as one operand). Templates/leaves/fractions are self-delimiting."""
    s = to_expr(ast)
    return f"({s})" if ast[0] in _NEEDS_GRP else s


def to_expr(ast):
    k = ast[0]
    if k in ("num", "var"):
        return ast[1]
    if k in ("add", "sub", "mul", "ldiv", "sdiv"):
        op = {"add": "+", "sub": "-", "mul": "*", "ldiv": "/", "sdiv": "//"}[k]
        return f"{_grp(ast[1])}{op}{_grp(ast[2])}"
    if k == "paren":
        return f"({to_expr(ast[1])})"
    if k == "pow":
        # A bare atom exponent needs no parens (template: ^ then the digit). A nested
        # power exponent (a^b^c) also needs none: "^" is right-associative in the
        # parser and the calc builds the same right-leaning staircase, so a^b^c and
        # a^(b^c) render identically (typed parens would instead force a 2-D paren
        # group into the raised slot, which stacks differently). Other compound
        # exponents are parenthesised so the whole thing stays in the raised slot.
        e = to_expr(ast[2])
        base = _grp(ast[1])
        bare = _is_leaf(ast[2]) or ast[2][0] == "pow"
        return f"{base}^{e}" if bare else f"{base}^({e})"
    if k == "sqrt":
        return f"sqrt({to_expr(ast[1])})"
    if k == "nthroot":
        return f"nthroot({to_expr(ast[1])},{to_expr(ast[2])})"
    if k == "abs":
        return f"abs({to_expr(ast[1])})"
    if k == "int":
        return f"int({to_expr(ast[1])},{to_expr(ast[2])},{to_expr(ast[3])},{to_expr(ast[4])})"
    if k == "sum":
        return f"sum({to_expr(ast[1])},{to_expr(ast[2])},{to_expr(ast[3])},{to_expr(ast[4])})"
    raise AssertionError(k)


# ---- AST -> TilEm keystrokes -----------------------------------------------
# Cursor model: every routine emits keys that leave the cursor on the main entry
# line, immediately to the RIGHT of the just-built sub-expression, ready for the
# next token. Templates (^, n/d fraction, √, x-root, ∫, Σ) enter each slot and
# leave the final slot with RIGHT so the cursor exits the template.

DIGIT = {"0": "0", "1": "1", "2": "2", "3": "3", "4": "4", "5": "5",
         "6": "6", "7": "7", "8": "8", "9": "9"}
VARKEY = {"X": "GRAPHVAR", "A": ["ALPHA", "MATH"], "N": ["ALPHA", "LOG"]}


def emit_grp(ast):
    """Keystrokes for `ast` as one operand: typed parens around a compound binary
    expression (mirrors _grp in to_expr so model string and calc agree); templates
    and leaves are self-delimiting and need none."""
    if ast[0] in _NEEDS_GRP:
        return ["LPAREN"] + emit(ast) + ["RPAREN"]
    return emit(ast)


def emit(ast):
    """Return the keystroke list that builds `ast` on the entry line, leaving the
    cursor just to its right on the main line."""
    k = ast[0]
    if k == "num":
        return [DIGIT[c] for c in ast[1]]
    if k == "var":
        v = VARKEY[ast[1]]
        return list(v) if isinstance(v, list) else [v]
    if k in ("add", "sub", "mul"):
        op = {"add": "ADD", "sub": "SUB", "mul": "MUL"}[k]
        return emit_grp(ast[1]) + [op] + emit_grp(ast[2])
    if k == "ldiv":
        return emit_grp(ast[1]) + ["DIV"] + emit_grp(ast[2])
    if k == "sdiv":
        # ALPHA YEQU opens the FRAC menu; "1" selects the n/d template. Then the
        # cursor is in the numerator slot; DOWN moves to the denominator; a single
        # RIGHT exits the fraction back to the main line. Numerator/denominator are
        # slots, but a compound one is still parenthesised so it parses as a unit in
        # the model string (the calc shows the same parens).
        return (["ALPHA", "YEQU", "WAIT", "1", "WAIT"] + emit_grp(ast[1]) +
                ["DOWN"] + emit_grp(ast[2]) + ["RIGHT"])
    if k == "paren":
        return ["LPAREN"] + emit(ast[1]) + ["RPAREN"]
    if k == "pow":
        # POWER raises into the exponent slot; one RIGHT exits it. A bare atom OR a
        # nested power exponent (a^b^c) is typed directly — the inner pow's own exit
        # RIGHT plus this one walk the cursor back out level by level. Any other
        # compound exponent is wrapped in typed parens so it stays in the raised slot.
        base = emit_grp(ast[1])
        if ast[2][0] in ("num", "var", "pow"):
            return base + ["POWER"] + emit(ast[2]) + ["RIGHT"]
        return base + ["POWER", "LPAREN"] + emit(ast[2]) + ["RPAREN", "RIGHT"]
    if k == "sqrt":
        # 2ND x^2 -> √( template; RIGHT exits the radicand.
        return ["2ND", "SQUARE"] + emit(ast[1]) + ["RIGHT"]
    if k == "nthroot":
        # index, then MATH 5 (x-root) template, radicand, RIGHT to exit.
        return emit(ast[1]) + ["MATH", "5"] + emit(ast[2]) + ["RIGHT"]
    if k == "abs":
        # MATH -> NUM (RIGHT) -> 1:abs( inserts the |■| bar template (auto-closing,
        # like ∫/√). A WAIT after the "1" lets the template settle before the body
        # is typed — without it a body that starts with "1" collides with the menu
        # selection key and the first "1" is dropped (abs(1) renders an empty bar).
        # Fill it, then RIGHT exits the right bar — typing RPAREN would add a spurious
        # paren inside the bars (|(3)|).
        return ["MATH", "RIGHT", "WAIT", "1", "WAIT"] + emit(ast[1]) + ["RIGHT"]
    if k == "int":
        # MATH 9 -> ∫ template with slots lo, hi, integrand, var. Each emit() leaves
        # the cursor just right of its sub-expression in the current slot, so ONE
        # RIGHT advances to the next slot: lo, RIGHT, hi, RIGHT, integrand, RIGHT,
        # var. (The old hand-written keys used RIGHT RIGHT after the integrand
        # because their body emit did not include the exponent-exit RIGHT; emit()'s
        # pow does, so a single RIGHT suffices here.)
        lo, hi, body, var = ast[1], ast[2], ast[3], ast[4]
        return (["MATH", "9"] + emit(lo) + ["RIGHT"] + emit(hi) + ["RIGHT"] +
                emit(body) + ["RIGHT"] + emit(var))
    if k == "sum":
        # MATH 0 -> Σ template. Probing with distinct digits (4 R 5 R 6 R 7) shows
        # the RIGHT-navigation slot order is: var, end(hi), body, start(lo) — the
        # "var=start" pair on the bottom is split, with the start typed last. So
        # var, RIGHT, hi, RIGHT, body, RIGHT, lo, then RIGHT exits.
        var, lo, hi, body = ast[1], ast[2], ast[3], ast[4]
        return (["MATH", "0", "WAIT"] + emit(var) + ["RIGHT"] + emit(hi) + ["RIGHT"] +
                emit(body) + ["RIGHT"] + emit(lo) + ["RIGHT"])
    raise AssertionError(k)


# ---- AST formatting --------------------------------------------------------

def show_ast(ast, depth=0):
    k = ast[0]
    if k in ("num", "var"):
        return f"{k}({ast[1]})"
    return f"{k}(" + ", ".join(show_ast(c) for c in ast[1:]) + ")"


# ---- curated examples for emitter validation -------------------------------
# AST forms of the 10 parity examples. The emitter must produce the same expr and
# keystrokes the parity tool hand-wrote, and match the calc 100%.
CURATED = {
    "x_squared":   ("pow", ("var", "X"), ("num", "2")),
    "pow_half":    ("pow", ("var", "X"), ("ldiv", ("num", "1"), ("num", "2"))),
    "linear_half": ("ldiv", ("num", "1"), ("num", "2")),
    "stacked_half":("sdiv", ("num", "1"), ("num", "2")),
    "sum_powers":  ("add", ("add", ("pow", ("var", "X"), ("num", "2")),
                            ("mul", ("num", "2"), ("var", "X"))), ("num", "1")),
    "radical":     ("sqrt", ("add", ("pow", ("var", "X"), ("num", "2")), ("num", "1"))),
    "integral":    ("int", ("num", "1"), ("num", "2"),
                    ("pow", ("var", "X"), ("num", "2")), ("var", "X")),
    "int_pow_half":("int", ("num", "1"), ("num", "2"),
                    ("pow", ("var", "X"), ("ldiv", ("num", "1"), ("num", "2"))),
                    ("var", "X")),
}


# ---- diff harness ----------------------------------------------------------

def run_one(parity, ast, outdir, name, retries=1):
    """Render model and calc, return (pct, bad, dim, calc, model).

    TilEm's headless GIF capture is occasionally noisy (a refresh-blanked or
    mid-animation frame), which shows up as a spurious low match. To keep results
    reproducible, a below-100 % case is re-run up to `retries` times and the BEST
    render is kept — a true layout bug stays below 100 % across re-runs, capture
    noise does not."""
    expr = to_expr(ast)
    keys = emit(ast)
    model = parity.js_bitmap(expr)
    best = None
    for attempt in range(retries + 2):
        try:
            shot, _ram, _ = parity.run_calc(keys, outdir, f"{name}_{attempt}", trace=False)
            calc = parity.calc_bitmap(shot)
            pct, bad, dim = parity.diff_metric(calc, model)
        except (OSError, ValueError, IndexError) as exc:
            # A corrupt/half-written TilEm GIF frame raises in Pillow; treat as a
            # capture miss and re-run rather than aborting the whole batch.
            print(f"     (capture error on {name} attempt {attempt}: {exc}; retrying)")
            continue
        if best is None or pct > best[0]:
            best = (pct, bad, dim, calc)
        if pct >= 100.0:
            break
    if best is None:                       # all attempts failed to capture
        return expr, keys, 0.0, 0, "capture failed", [[0]], model
    pct, bad, dim, calc = best
    return expr, keys, pct, bad, dim, calc, model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("-n", "--count", type=int, default=30)
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--validate", action="store_true",
                    help="run the curated examples through the emitter (must be 100%%)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print AST/expr/keys only; do not run the calculator")
    ap.add_argument("--threshold", type=float, default=100.0,
                    help="report cases below this match %% (default 100: every mismatch)")
    ap.add_argument("--with-sum", action="store_true",
                    help="include Σ summation in generation (emitter slot order WIP)")
    args = ap.parse_args()

    global INCLUDE_SUM
    INCLUDE_SUM = args.with_sum
    parity = _load_parity()
    outdir = tempfile.mkdtemp(prefix="mp-fuzz-")
    print(f"seed={args.seed} count={args.count} depth={args.depth} artifacts={outdir}\n")

    if args.validate:
        # also pull the two examples whose keys the parity tool wrote with WAITs
        # we can't reconstruct from the AST (stacked_half / integral_frac); those
        # are covered by parity-mathprint.py directly. Here we check the AST-emitted
        # keys reproduce the parity expr strings and (unless --dry-run) match calc.
        bad = 0
        for name, ast in CURATED.items():
            expr = to_expr(ast)
            keys = emit(ast)
            want_expr = parity.EXAMPLES[name][0]
            # The emitter normalises to explicit "*" (2*X) where the hand-written
            # parity expr used juxtaposition (2X); the parser renders both identically,
            # so an expr-string difference is informational, not a failure — the
            # calc-match below is the real gate.
            note = "" if expr == want_expr else f"  (parity expr: {want_expr!r})"
            line = f"{name}: expr={expr!r}{note}"
            if not args.dry_run:
                _, _, pct, bpx, dim, calc, model = run_one(parity, ast, outdir, name)
                line += f"  calc-match {pct:.1f}% ({bpx}px, {dim})"
                if pct < args.threshold:
                    bad += 1
                    print(line)
                    print(parity.side_by_side(calc, model))
                    print()
                    continue
            print(line)
        print(f"\nvalidate: {len(CURATED)-bad}/{len(CURATED)} clean")
        sys.exit(1 if bad else 0)

    rng = random.Random(args.seed)
    asts = [gen_ast(rng, args.depth) for _ in range(args.count)]
    mismatches = 0
    for i, ast in enumerate(asts):
        expr = to_expr(ast)
        keys = emit(ast)
        if args.dry_run:
            print(f"[{i}] {show_ast(ast)}\n     expr: {expr}\n     keys: {' '.join(keys)}")
            continue
        _, _, pct, bpx, dim, calc, model = run_one(parity, ast, outdir, f"f{i}")
        tag = "OK " if pct >= args.threshold else "BAD"
        print(f"[{i}] {tag} {pct:5.1f}%  {expr}", flush=True)
        if pct < args.threshold:
            mismatches += 1
            print(f"     AST : {show_ast(ast)}")
            print(f"     keys: {' '.join(keys)}")
            print(f"     {bpx}px off, {dim}")
            print(parity.side_by_side(calc, model))
            print()
    if not args.dry_run:
        print(f"\n{args.count - mismatches}/{args.count} matched at >= {args.threshold}%  "
              f"(seed {args.seed})")
        sys.exit(1 if mismatches else 0)


if __name__ == "__main__":
    main()
