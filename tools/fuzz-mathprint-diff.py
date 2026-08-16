#!/usr/bin/env python3
"""Differential fuzzer for the MathPrint layout renderer.

The robustness fuzzer (tools/test-mathprint.js) only checks the JS model does not
throw; it never renders on the calculator, so it cannot catch *layout* bugs (e.g.
X^(1/2) was in its corpus yet 78.9% vs the calc). This tool closes that gap: it
generates random ASTs over the supported constructs and, for each, emits BOTH

  1. the model expression string (the syntax web/mathprint/app.js parse() accepts), and
  2. a TilEm keystroke sequence intended to build the same expression on the
     home entry line,

then renders the ROM-translated settled-record path and the calculator and
pixel-diffs the pre-ENTER screenshot. Every mismatch is reported with the AST,
expression, keystrokes, match percentage, dimensions, and a side-by-side before
an instruction trace is captured for diagnosis.

The AST-to-keystroke emitter models template navigation (after ^ the
cursor is in the raised exponent slot and needs RIGHT to exit; ∫/Σ/√/n-d templates
enter each slot with RIGHT and leave the last with RIGHT; a typed group is closed
with RPAREN). `--validate` exercises a curated AST set before random generation.

Usage:
  python3 tools/fuzz-mathprint-diff.py --validate          # check emitter vs the curated examples
  python3 tools/fuzz-mathprint-diff.py --seed 11 -n 25     # 25 random differential cases
  python3 tools/fuzz-mathprint-diff.py --dry-run --seed 1 -n 30   # print expr+keys only, no calc

Construct coverage
------------------
The default generator covers number, variable, + - *, ^ (incl. nested a^b^c and
parenthesised/abs/fraction bases with *, /, +, - exponents), / (linear), // (stacked
fraction), sqrt, nthroot, abs, int, sum, nDeriv, e^x, 10^x, logBASE, and
parentheses. Fraction children, radicands, absolute-value bodies, and power bases
may contain structural records.
The generator keeps raised slots and nth-root indices to entry sequences whose
cursor behavior is independently pinned; this constrains input construction, not
the JavaScript record renderer. The calculator entry path accepts at most four
nested structural records. Random differential cases stay within that entry
boundary, while `--validate-entry-depth` checks both sides of the ROM gate.
"""
import argparse
import importlib.util
import os
import random
import subprocess
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
#   ('nderiv', body, var, value)
#   ('epow'|'tenpow', exponent) ('logbase', base, argument)
#   ('matrix1x1'|'matrix1x2'|'matrix2x2', element, ...)
# ---------------------------------------------------------------------------

VARS = ["X", "A", "N"]
NUMS = ["1", "2", "3"]

STRUCTURAL_KINDS = frozenset({
    "pow", "sdiv", "sqrt", "nthroot", "abs", "int", "sum", "nderiv",
    "epow", "tenpow", "logbase",
})
CALCULATOR_MAX_STRUCTURAL_DEPTH = 4
CALCULATOR_INPUT_CADENCES = (
    (0.1, 0.0),
    (0.16, 0.03),
    (0.24, 0.12),
)
MATRIX_SHAPES = {
    "matrix1x1": (1, 1),
    "matrix1x2": (1, 2),
    "matrix2x2": (2, 2),
}


# The variable and lower bound share the first summation field; RIGHT then
# advances to the upper bound and body.
INCLUDE_SUM = True
INCLUDE_MATRIX = False
MATRIX_ONLY = False


def gen_frac_operand(rng, depth):
    """Build a structural child for a stacked-fraction slot."""
    return gen_ast(rng, depth)


def gen_matrix_element(rng, depth):
    """Generate an evaluable matrix cell while retaining 2-D structures."""
    if depth <= 0:
        return ("num", rng.choice(NUMS))
    kind = rng.choice(("leaf", "add", "mul", "sdiv", "pow", "sqrt", "abs"))
    if kind == "leaf":
        return ("num", rng.choice(NUMS))
    if kind in {"add", "mul", "sdiv"}:
        return (
            kind,
            gen_matrix_element(rng, depth - 1),
            gen_matrix_element(rng, depth - 1),
        )
    if kind == "pow":
        return (
            "pow", gen_matrix_element(rng, depth - 1),
            ("num", rng.choice(NUMS)),
        )
    return (kind, gen_matrix_element(rng, depth - 1))


def gen_ast(rng, depth, *, in_small=False, avoid=()):
    """Random AST. `in_small` is set inside an exponent/limit so we avoid 2-D
    templates there (the calc does not place a stacked fraction / integral in a
    raised slot from these keystrokes; keep raised content to flat constructs).
    `avoid` drops kinds whose flat textual spelling would be ambiguous in the
    surrounding operator."""
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
                   "pow", "sqrt", "nthroot", "abs", "int", "nderiv",
                   "epow", "tenpow", "logbase"]
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
        return ("pow", gen_ast(rng, d, in_small=in_small, avoid=avoid),
                gen_ast(rng, d, in_small=True, avoid=avoid))
    if k == "sqrt":
        return ("sqrt", gen_ast(rng, d, avoid=avoid))
    if k == "nthroot":
        return ("nthroot", gen_ast(rng, 0), gen_ast(rng, d, avoid=avoid))
    if k == "abs":
        return ("abs", gen_ast(rng, d, avoid=avoid))
    if k == "int":
        return ("int", ("num", rng.choice(NUMS)), ("num", rng.choice(NUMS)),
                gen_ast(rng, d, avoid=avoid), ("var", rng.choice(VARS)))
    if k == "sum":
        return ("sum", ("var", rng.choice(VARS)), ("num", rng.choice(NUMS)),
                ("num", rng.choice(NUMS)), gen_ast(rng, d))
    if k == "nderiv":
        return ("nderiv", gen_ast(rng, d, avoid=avoid),
                ("var", rng.choice(VARS)), gen_ast(rng, d, avoid=avoid))
    if k in ("epow", "tenpow"):
        return (k, gen_ast(rng, d, in_small=True, avoid=avoid))
    if k == "logbase":
        return ("logbase", gen_ast(rng, d, in_small=True, avoid=avoid),
                gen_ast(rng, d, avoid=avoid))
    if k in MATRIX_SHAPES:
        rows, columns = MATRIX_SHAPES[k]
        return (k, *(
            gen_matrix_element(rng, d) for _ in range(rows * columns)
        ))
    raise AssertionError(k)


def calculator_structural_depth(ast):
    """Return the maximum structural-record nesting along any AST path.

    Binary token sequences and explicit parentheses do not allocate a settled
    structural record. Every kind in STRUCTURAL_KINDS adds one level before its
    children are considered, matching the byte checked at 35:7B37.
    """
    child_depth = max(
        (calculator_structural_depth(child) for child in ast[1:]
         if isinstance(child, tuple)),
        default=0,
    )
    return child_depth + (ast[0] in STRUCTURAL_KINDS)


def gen_comparable_asts(rng, depth, count, *, max_structural_depth=4):
    """Generate `count` ASTs accepted by the calculator's structural gate."""
    if count < 0:
        raise ValueError("count must be non-negative")
    if not 0 <= max_structural_depth <= 0xff:
        raise ValueError("maximum structural depth must be an unsigned byte")
    accepted = []
    rejected = 0
    attempts = 0
    attempt_limit = max(1000, count * 1000)
    while len(accepted) < count and attempts < attempt_limit:
        if MATRIX_ONLY or (INCLUDE_MATRIX and rng.random() < 0.25):
            kind = rng.choice(tuple(MATRIX_SHAPES))
            rows, columns = MATRIX_SHAPES[kind]
            ast = (kind, *(
                gen_matrix_element(rng, max(0, depth - 1))
                for _ in range(rows * columns)
            ))
        else:
            ast = gen_ast(rng, depth)
        attempts += 1
        if calculator_structural_depth(ast) > max_structural_depth:
            rejected += 1
            continue
        accepted.append(ast)
    if len(accepted) != count:
        raise RuntimeError(
            f"could not generate {count} calculator-admissible ASTs after "
            f"{attempts} candidates"
        )
    return accepted, rejected


def structural_depth_boundary_cases():
    """Return paired depth-four/depth-five entry cases for each constructor."""
    leaf = ("num", "2")
    candidates = {
        "power": ("pow", leaf, leaf),
        "fraction": ("sdiv", ("num", "1"), leaf),
        "radical": ("sqrt", leaf),
        "nth-root": ("nthroot", ("var", "A"), leaf),
        "absolute": ("abs", leaf),
        "integral": (
            "int", ("num", "1"), ("num", "1"), leaf, ("var", "N")),
        "summation": (
            "sum", ("var", "N"), ("num", "1"), ("num", "1"), leaf),
        "nDeriv": ("nderiv", leaf, ("var", "N"), ("num", "1")),
        "e-power": ("epow", leaf),
        "ten-power": ("tenpow", leaf),
        "log-base": ("logbase", leaf, leaf),
    }

    def at_depth_four(child):
        return (
            "int", ("num", "1"), ("num", "1"),
            ("nthroot", ("var", "A"), ("abs", child)),
            ("var", "N"),
        )

    def at_depth_five(child):
        return (
            "int", ("num", "1"), ("num", "1"),
            ("abs", ("nthroot", ("var", "A"), ("abs", child))),
            ("var", "N"),
        )

    return [
        (name, at_depth_four(child), at_depth_five(child))
        for name, child in candidates.items()
    ]


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


def _power_base(ast):
    """Preserve a compound or powered AST when it becomes another power's base."""
    s = to_expr(ast)
    return f"({s})" if ast[0] in _NEEDS_GRP + ("pow",) else s


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
        base = _power_base(ast[1])
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
    if k == "nderiv":
        return f"nDeriv({to_expr(ast[1])},{to_expr(ast[2])},{to_expr(ast[3])})"
    if k == "epow":
        return f"exp({to_expr(ast[1])})"
    if k == "tenpow":
        return f"tenpow({to_expr(ast[1])})"
    if k == "logbase":
        return f"logbase({to_expr(ast[1])},{to_expr(ast[2])})"
    if k in MATRIX_SHAPES:
        rows, columns = MATRIX_SHAPES[k]
        elements = ",".join(to_expr(element) for element in ast[1:])
        return f"matrix({rows},{columns},{elements})"
    raise AssertionError(k)


def to_spec(ast):
    """Translate the generated AST and its explicit UI groups to renderer input."""
    k = ast[0]
    if k in ("num", "var"):
        return [ord(char) for char in ast[1]]

    def grouped(child, *, power_base=False):
        spec = to_spec(child)
        kinds = _NEEDS_GRP + (("pow",) if power_base else ())
        return {"kind": "group", "expression": spec} if child[0] in kinds else spec

    if k in ("add", "sub", "mul", "ldiv"):
        token = {"add": 0x70, "sub": 0x71, "mul": 0x82, "ldiv": 0x83}[k]
        return {
            "kind": "sequence",
            "parts": [grouped(ast[1]), [token], grouped(ast[2])],
        }
    if k == "sdiv":
        return {
            "kind": "fraction",
            "numerator": grouped(ast[1]),
            "denominator": grouped(ast[2]),
        }
    if k == "paren":
        return {"kind": "group", "expression": to_spec(ast[1])}
    if k == "pow":
        exponent = to_spec(ast[2])
        if ast[2][0] not in ("num", "var", "pow"):
            exponent = {"kind": "group", "expression": exponent}
        return {
            "kind": "power", "base": grouped(ast[1], power_base=True),
            "exponent": exponent,
        }
    if k == "sqrt":
        return {"kind": "radical", "radicand": to_spec(ast[1])}
    if k == "nthroot":
        return {
            "kind": "nthRoot", "index": to_spec(ast[1]),
            "radicand": to_spec(ast[2]),
        }
    if k == "abs":
        return {"kind": "absolute", "body": to_spec(ast[1])}
    if k == "int":
        return {
            "kind": "integral", "lower": to_spec(ast[1]),
            "upper": to_spec(ast[2]), "body": to_spec(ast[3]),
            "variable": to_spec(ast[4]),
        }
    if k == "sum":
        return {
            "kind": "summation", "variable": to_spec(ast[1]),
            "lower": to_spec(ast[2]), "upper": to_spec(ast[3]),
            "body": to_spec(ast[4]),
        }
    if k == "nderiv":
        return {
            "kind": "nDeriv", "variable": to_spec(ast[2]),
            "body": to_spec(ast[1]), "value": to_spec(ast[3]),
        }
    if k == "epow":
        return {"kind": "ePower", "exponent": to_spec(ast[1])}
    if k == "tenpow":
        return {"kind": "tenPower", "exponent": to_spec(ast[1])}
    if k == "logbase":
        return {
            "kind": "logBase", "base": to_spec(ast[1]),
            "argument": to_spec(ast[2]),
        }
    if k in MATRIX_SHAPES:
        rows, columns = MATRIX_SHAPES[k]
        return {
            "kind": "matrix", "rows": rows, "columns": columns,
            "elements": [to_spec(element) for element in ast[1:]],
        }
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


def emit_power_base(ast):
    """Type an explicit group when a power becomes another power's base."""
    if ast[0] in _NEEDS_GRP + ("pow",):
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
        base = emit_power_base(ast[1])
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
        # the cursor just right of its sub-expression in the current slot, so one
        # RIGHT advances to the next slot: lo, RIGHT, hi, RIGHT, integrand, RIGHT,
        # var. Wait for the template and each slot transition; nested templates can
        # otherwise still be rebuilding when the next key arrives.
        lo, hi, body, var = ast[1], ast[2], ast[3], ast[4]
        return (["MATH", "9", "WAIT"] + emit(lo) + ["RIGHT", "WAIT"] +
                emit(hi) + ["RIGHT", "WAIT"] + emit(body) +
                ["RIGHT", "WAIT"] + emit(var) + ["WAIT"])
    if k == "sum":
        # MATH 0 -> Σ template. The variable and lower bound share the first
        # field: entering the variable moves the cursor across the equals sign
        # into the lower-bound slot. RIGHT then advances to the upper bound and
        # body; the final RIGHT exits the template.
        var, lo, hi, body = ast[1], ast[2], ast[3], ast[4]
        return (["MATH", "0", "WAIT"] + emit(var) + ["WAIT"] + emit(lo) +
                ["RIGHT", "WAIT"] + emit(hi) + ["RIGHT", "WAIT"] +
                emit(body) + ["RIGHT", "WAIT"])
    if k == "nderiv":
        # MATH 8 opens variable, body, and evaluation-value slots. Entering the
        # one-token variable advances to the body. RIGHT then selects the value
        # and exits the template.
        body, var, value = ast[1], ast[2], ast[3]
        return (["MATH", "8", "WAIT"] + emit(var) + ["WAIT"] + emit(body) +
                ["RIGHT", "WAIT"] + emit(value) + ["RIGHT", "WAIT"])
    if k == "epow":
        return ["2ND", "LN", "WAIT"] + emit(ast[1]) + ["RIGHT", "WAIT"]
    if k == "tenpow":
        return ["2ND", "LOG", "WAIT"] + emit(ast[1]) + ["RIGHT", "WAIT"]
    if k == "logbase":
        return (["MATH", "ALPHA", "MATH", "WAIT"] + emit(ast[1]) +
                ["RIGHT", "WAIT"] + emit(ast[2]) + ["RIGHT", "WAIT"])
    if k in MATRIX_SHAPES:
        rows, columns = MATRIX_SHAPES[k]
        keys = ["2ND", "MUL", "2ND", "MUL"]
        index = 1
        for row in range(rows):
            if row:
                keys.extend(["2ND", "MUL"])
            for column in range(columns):
                if column:
                    keys.append("COMMA")
                keys.extend(emit(ast[index]))
                index += 1
            keys.extend(["2ND", "SUB"])
        keys.extend(["2ND", "SUB"])
        return keys
    raise AssertionError(k)


# ---- AST formatting --------------------------------------------------------

def show_ast(ast, depth=0):
    k = ast[0]
    if k in ("num", "var"):
        return f"{k}({ast[1]})"
    return f"{k}(" + ", ".join(show_ast(c) for c in ast[1:]) + ")"


# ---- curated examples for emitter validation -------------------------------
# AST forms of the 10 parity examples. The emitter must produce the same expr and
# keystrokes corresponding to the parity tool's curated expressions.
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
    "summation":   ("sum", ("var", "N"), ("num", "1"), ("num", "3"),
                    ("pow", ("var", "N"), ("num", "2"))),
    "matrix":      ("matrix2x2",
                    ("sqrt", ("num", "2")),
                    ("pow", ("num", "2"), ("num", "2")),
                    ("num", "3"), ("num", "1")),
}


# ---- diff harness ----------------------------------------------------------

class ModelRenderError(RuntimeError):
    """The translated JavaScript model rejected a generated expression."""


class CalculatorInputMismatch(RuntimeError):
    """The calculator's final settled graph differs from the requested AST."""

    def __init__(self, expected, actual):
        self.expected = expected
        self.actual = actual
        super().__init__(
            "calculator settled graph differs from the requested AST: "
            f"expected {expected!r}, captured {actual!r}"
        )


def calculator_expression(parity, ram_path):
    """Return the final graph AST, preserving graph-walk failures as diagnostics."""
    try:
        return parity.calculator_settled_program(ram_path)["expression"]
    except ValueError as error:
        return f"unresolved settled graph: {error}"


def run_one(parity, ast, outdir, name, *, trace=False):
    """Render one translated model and calculator entry, optionally tracing it."""
    expr = to_expr(ast)
    # One final top-level RIGHT commits a completed nested template boundary.
    # The key is a no-op when the cursor is already at the outer boundary. This
    # leaves the accepted graph stable before the final RAM snapshot.
    keys = emit(ast) + ["RIGHT", "WAIT"]
    try:
        model, _expected_native, expected_expression = parity.js_render_spec(
            to_spec(ast))
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "no process output").strip()
        raise ModelRenderError(f"translated model failed: {detail}") from error
    matrix_case = ast[0] in MATRIX_SHAPES
    captures, ram_path, trace_path, _macro = parity.run_calc(
        keys, outdir, name, trace=trace, trace_history=matrix_case)
    actual_expression = calculator_expression(parity, ram_path)
    if actual_expression != expected_expression and not trace:
        for retry, (key_delay, inter_key_wait) in enumerate(
                CALCULATOR_INPUT_CADENCES[1:], start=1):
            captures, ram_path, trace_path, _macro = parity.run_calc(
                keys, outdir, f"{name}-retry{retry}", trace=False,
                trace_history=matrix_case,
                key_delay=key_delay, inter_key_wait=inter_key_wait)
            actual_expression = calculator_expression(parity, ram_path)
            if actual_expression == expected_expression:
                break
    if actual_expression != expected_expression:
        raise CalculatorInputMismatch(expected_expression, actual_expression)
    expected_size = (len(model[0]), len(model))
    calc = parity.calc_from_trace(
        trace_path, preserve_internal_gaps=matrix_case,
        expected_size=expected_size if matrix_case else None) if trace \
        else parity.calc_bitmap(
            captures, preserve_internal_gaps=True,
            require_history=True, expected_size=expected_size) if matrix_case \
        else parity.calc_entry_bitmap(captures)
    pct, bad, dim = parity.diff_metric(calc, model)
    return expr, keys, pct, bad, dim, calc, model


def validate_entry_depth(parity, outdir):
    """Exercise accepted depth four and rejected depth five on the calculator."""
    failures = 0
    key_delay, inter_key_wait = CALCULATOR_INPUT_CADENCES[-1]
    for name, accepted, rejected in structural_depth_boundary_cases():
        for label, ast, should_accept in (
                ("depth4", accepted, True), ("depth5", rejected, False)):
            model, _native, expected = parity.js_render_spec(to_spec(ast))
            keys = emit(ast) + ["RIGHT", "WAIT"]
            captures, ram_path, _trace, _macro = parity.run_calc(
                keys, outdir, f"entry-{name}-{label}", trace=False,
                key_delay=key_delay, inter_key_wait=inter_key_wait)
            actual = calculator_expression(parity, ram_path)
            admitted = actual == expected
            pixels_match = None
            if admitted:
                calc = parity.calc_entry_bitmap(captures)
                pixels_match = parity.diff_metric(calc, model)[0] == 100.0
            clean = admitted == should_accept and (
                not should_accept or pixels_match)
            status = "OK" if clean else "BAD"
            detail = "accepted" if admitted else "rejected"
            if admitted:
                detail += ", pixels exact" if pixels_match else ", pixel mismatch"
            print(f"{status} {name:10} {label}: {detail}", flush=True)
            failures += not clean
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("-n", "--count", type=int, default=30)
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--validate", action="store_true",
                    help="run the curated examples through the emitter and trace diff")
    ap.add_argument("--validate-entry-depth", action="store_true",
                    help="check all structural constructors at accepted depth 4 and rejected depth 5")
    ap.add_argument("--dry-run", action="store_true",
                    help="print AST/expr/keys only; do not run the calculator")
    ap.add_argument("--threshold", type=float, default=100.0,
                    help="report cases below this match %% (default 100: every mismatch)")
    ap.add_argument("--without-sum", action="store_true",
                    help="exclude Σ while diagnosing its calculator input sequence")
    ap.add_argument("--with-matrix", action="store_true",
                    help="include evaluable matrix literals in random generation")
    ap.add_argument("--matrix-only", action="store_true",
                    help="generate only evaluable top-level matrix literals")
    ap.add_argument("--trace-every-case", action="store_true",
                    help="capture a reset-origin instruction trace before comparing each case")
    ap.add_argument("--no-trace-on-mismatch", action="store_true",
                    help="retain screenshots and RAM but skip the diagnostic trace rerun")
    ap.add_argument("--max-entry-depth", type=int,
                    default=CALCULATOR_MAX_STRUCTURAL_DEPTH,
                    help="maximum structural nesting admitted to random calculator comparison (default 4)")
    args = ap.parse_args()

    global INCLUDE_SUM, INCLUDE_MATRIX, MATRIX_ONLY
    INCLUDE_SUM = not args.without_sum
    INCLUDE_MATRIX = args.with_matrix or args.matrix_only
    MATRIX_ONLY = args.matrix_only
    parity = _load_parity()
    if not args.dry_run:
        parity.validate_inputs()
    outdir = tempfile.mkdtemp(prefix="mp-fuzz-")
    print(f"seed={args.seed} count={args.count} depth={args.depth} artifacts={outdir}\n")

    if args.validate_entry_depth:
        if args.dry_run:
            ap.error("--validate-entry-depth requires calculator execution")
        failures = validate_entry_depth(parity, outdir)
        total = 2 * len(structural_depth_boundary_cases())
        print(f"\nentry-depth validation: {total - failures}/{total} clean")
        sys.exit(1 if failures else 0)

    if args.validate:
        # also pull the two examples whose keys the parity tool wrote with WAITs
        # we can't reconstruct from the AST (stacked_half / integral_frac); those
        # are covered by parity-mathprint.py directly. Here we check the AST-emitted
        # keys reproduce the parity expr strings and (unless --dry-run) match calc.
        bad = 0
        for name, ast in CURATED.items():
            expr = to_expr(ast)
            keys = emit(ast)
            want_expr = parity.EXAMPLES.get(name, (expr,))[0]
            # The emitter normalises to explicit "*" (2*X) where the hand-written
            # parity expr used juxtaposition (2X); the parser renders both identically,
            # so an expr-string difference is informational, not a failure — the
            # calc-match below is the real gate.
            note = "" if expr == want_expr else f"  (parity expr: {want_expr!r})"
            line = f"{name}: expr={expr!r}{note}"
            if not args.dry_run:
                _, _, pct, bpx, dim, calc, model = run_one(
                    parity, ast, outdir, name, trace=args.trace_every_case)
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

    if not 0 <= args.max_entry_depth <= 0xff:
        ap.error("--max-entry-depth must be between 0 and 255")
    rng = random.Random(args.seed)
    asts, entry_rejects = gen_comparable_asts(
        rng, args.depth, args.count,
        max_structural_depth=args.max_entry_depth)
    if entry_rejects:
        print(f"entry-depth filter: rejected {entry_rejects} candidate ASTs above "
              f"depth {args.max_entry_depth}\n")
    mismatches = 0
    inconclusive = 0
    for i, ast in enumerate(asts):
        expr = to_expr(ast)
        keys = emit(ast)
        if args.dry_run:
            print(f"[{i}] {show_ast(ast)}\n     expr: {expr}\n     keys: {' '.join(keys)}")
            continue
        try:
            _, _, pct, bpx, dim, calc, model = run_one(
                parity, ast, outdir, f"f{i}", trace=args.trace_every_case)
        except ModelRenderError as error:
            mismatches += 1
            print(f"[{i}] MODEL {expr}\n     AST : {show_ast(ast)}"
                  f"\n     keys: {' '.join(keys)}\n     {error}", flush=True)
            continue
        except CalculatorInputMismatch as error:
            inconclusive += 1
            print(f"[{i}] INC  {expr}\n     {error}", flush=True)
            continue
        except RuntimeError as error:
            # Preserve the completed cases and continue reducing the corpus.
            # A trace-limit hit is not evidence for or against pixel parity.
            inconclusive += 1
            print(f"[{i}] INC  {expr}\n     {error}", flush=True)
            continue
        tag = "OK " if pct >= args.threshold else "BAD"
        print(f"[{i}] {tag} {pct:5.1f}%  {expr}", flush=True)
        if pct < args.threshold:
            mismatches += 1
            print(f"     AST : {show_ast(ast)}")
            print(f"     keys: {' '.join(keys)}")
            print(f"     {bpx}px off, {dim}")
            print(parity.side_by_side(calc, model))
            if not args.trace_every_case and not args.no_trace_on_mismatch:
                try:
                    _, _, trace_pct, trace_bad, trace_dim, _, _ = run_one(
                        parity, ast, outdir, f"f{i}-trace", trace=True)
                    print(f"     trace replay: {trace_pct:.1f}% "
                          f"({trace_bad}px, {trace_dim})")
                except RuntimeError as error:
                    print(f"     trace capture inconclusive: {error}")
            print()
    if not args.dry_run:
        matched = args.count - mismatches - inconclusive
        print(f"\n{matched}/{args.count} matched at >= {args.threshold}%  "
              f"({inconclusive} inconclusive; seed {args.seed})")
        sys.exit(1 if mismatches or inconclusive else 0)


if __name__ == "__main__":
    main()
