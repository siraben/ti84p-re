#!/usr/bin/env python3
"""Build compact TI-BASIC interpreter coverage evidence for OS 2.55MP.

The analysis deliberately separates two claims:

* finite models exhaust every input in a bounded ROM-derived decision; and
* calculator traces show which branches and subsystem features real programs hit.

Raw TLMT traces are inputs, not repository artifacts.  The checked-in JSON keeps
only hashes, counts, observed branch outcomes, and a Z3-minimized diverse corpus.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Callable, Iterable, Iterator, Sequence

from hardware_trace import make_banker
from rom_image import RomImage, RomLocation
from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from tilem_trace_resolve import iter_records, read_header, resolve_instruction
from z80_disassembly import Z80Instruction, direct_target, disassemble_page


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "tools" / "rom.bin"
DEFAULT_OUTPUT = ROOT / "tools" / "tibasic-coverage.json"

TWO_BYTE_LEADS = frozenset({
    0x5C, 0x5D, 0x5E, 0x60, 0x61, 0x62, 0x63, 0x7E, 0xBB, 0xAA, 0xEF,
})

# These tags describe distinct interpreter work, not individual fixtures.  They
# are combined with observed branch outcomes before exact corpus minimization.
TRACE_FEATURES = {
    "hello": {"statement", "string", "display"},
    "factorial": {"statement", "prompt", "scalar_store", "for_end", "fp_arithmetic", "display"},
    "data": {"statement", "two_byte_token", "list_literal", "list_store", "list_fold", "display"},
    "dfs": {"statement", "two_byte_token", "list_store", "while_end", "for_end", "if_then_else_scan", "nested_blocks", "display"},
    "callabi": {"statement", "two_byte_token", "list_store", "program_call", "return", "shared_globals", "ans", "display"},
    "callstop": {"statement", "program_call", "stop", "nonlocal_termination", "display"},
    "branchmatrix": {"block_matrix", "else", "repeat", "optional_quote", "nested_blocks"},
    "missingend": {"missing_end_error"},
    "terminalif": {"terminal_if_error"},
}

TRACE_PROVENANCE = {
    **{label: "natural_tibasic" for label in TRACE_FEATURES},
    "cflowlow": "public_bcall_probe",
    "cflowhigh": "public_bcall_probe",
    "cflowvalid": "public_bcall_probe",
    "cmdclose": "internal_entry_probe",
    "cmdopen": "internal_entry_probe",
    "cmdunit": "internal_entry_probe",
    "cmdbad": "internal_entry_probe",
    "gramlow": "internal_entry_probe",
    "gramhigh": "internal_entry_probe",
    "gramflag": "internal_entry_probe",
    "gramnonzero": "internal_entry_probe",
}

ERROR_TRACES = frozenset({"missingend", "terminalif"})


@dataclass(frozen=True)
class BranchSite:
    component: str
    location: RomLocation
    instruction: str
    kind: str
    target: tuple[str, int] | None
    fallthrough: tuple[str, int]

    @property
    def key(self) -> tuple[str, int]:
        return f"page_{self.location.page:02X}", self.location.address

    @property
    def identifier(self) -> str:
        return str(self.location)


def logical_code_point(page: int, address: int) -> tuple[str, int]:
    """Resolve a static logical target in the fixed or current page window."""

    return ("ram", address) if address < 0x4000 else (f"page_{page:02X}", address)


def format_code_point(point: tuple[str, int]) -> str:
    space, address = point
    return (
        f"ram:{address:04X}"
        if space == "ram"
        else f"{space.removeprefix('page_')}:{address:04X}"
    )


@dataclass(frozen=True)
class FiniteModel:
    name: str
    rom: str
    domain: str
    inputs: tuple[object, ...]
    classify: Callable[[object], str]
    boundary: str


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def parse_trace(value: str) -> tuple[str, Path]:
    label, separator, raw_path = value.partition("=")
    if not separator or not label or not raw_path:
        raise argparse.ArgumentTypeError("trace must be LABEL=PATH")
    path = Path(raw_path)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"trace does not exist: {path}")
    return label, path


def z3_minimum_cover(
    candidates: Sequence[str], features: dict[str, set[str]]
) -> tuple[str, ...]:
    """Return the unique minimum-cardinality, label-stable feature cover."""

    if not shutil.which("z3"):
        raise RuntimeError("z3 is required; run this tool through `nix develop -c`")
    universe = sorted(set().union(*(features[label] for label in candidates)))
    variables = {label: f"x{index}" for index, label in enumerate(candidates)}
    lines = ["(set-option :opt.priority lex)"]
    lines.extend(f"(declare-const {variables[label]} Bool)" for label in candidates)
    for feature in universe:
        members = [variables[label] for label in candidates if feature in features[label]]
        lines.append(f"(assert (or {' '.join(members)}))")
    count = " ".join(f"(ite {variables[label]} 1 0)" for label in candidates)
    lines.append(f"(minimize (+ {count}))")
    # Prefer earlier sorted labels only after cardinality.  This makes report
    # regeneration deterministic when multiple exact covers exist.
    preference = " ".join(
        f"(ite {variables[label]} {1 << (len(candidates) - index - 1)} 0)"
        for index, label in enumerate(candidates)
    )
    lines.append(f"(maximize (+ {preference}))")
    lines.extend(["(check-sat)", "(get-model)"])
    result = subprocess.run(
        ["z3", "-in"], input="\n".join(lines) + "\n", text=True,
        capture_output=True, check=False,
    )
    if result.returncode or not result.stdout.startswith("sat\n"):
        raise RuntimeError(f"z3 cover failure: {result.stderr or result.stdout}")
    values = dict(re.findall(r"\(define-fun (x\d+) \(\) Bool\s+(true|false)\)", result.stdout))
    if len(values) != len(candidates):
        raise RuntimeError("z3 model omitted a corpus variable")
    return tuple(label for label in candidates if values[variables[label]] == "true")


def finite_models() -> tuple[FiniteModel, ...]:
    bytes_domain = tuple(range(0x100))
    return (
        FiniteModel(
            "encoded token width", "00:1FE8–2000", "all 256 lead bytes",
            bytes_domain,
            lambda token: "two_byte" if token in TWO_BYTE_LEADS else "one_byte",
            "Models the CPIR membership result, not validity of the second byte.",
        ),
        FiniteModel(
            "statement delimiter", "38:72DA–72E4", "all 256 fetched bytes",
            bytes_domain,
            lambda token: (
                "colon" if token == 0x3E else "end" if token == 0
                else "eol" if token == 0x3F else "ordinary"
            ),
            "Models the byte classifier; refill and parser-memory faults remain external.",
        ),
        FiniteModel(
            "token scan step", "38:4180–419D", "all 256 current bytes",
            bytes_domain,
            lambda token: (
                "delimiter_return" if token in {0, 0x3E, 0x3F}
                else "quoted_string_scan" if token == 0x2A
                else "skip_two_bytes" if token in TWO_BYTE_LEADS
                else "skip_one_byte"
            ),
            "Models one outer scan decision; quoted-string contents and stream length are unbounded.",
        ),
        FiniteModel(
            "block matcher transition", "38:4130–417E",
            "all 65,536 DE depths × 8 decision-equivalent token/lookahead classes",
            tuple(
                state
                for depth in range(0x10000)
                for state in (
                    (depth, 0xD0, False), (depth, 0xD4, False),
                    (depth, 0xD3, False), (depth, 0xD1, False),
                    (depth, 0xD2, False), (depth, 0xCE, True),
                    (depth, 0xCE, False), (depth, 0x00, False),
                )
            ),
            lambda state: block_transition(*state),
            "Models one 16-bit nest-counter transition, including wrap; arbitrary block streams remain unbounded.",
        ),
        FiniteModel(
            "extended grammar fold", "38:6FB7–6FC2", "all 256 token-class bytes",
            bytes_domain,
            lambda token: "below_f2" if token < 0xF2 else "extended_add_12_wraps",
            "Models the CP F2h / ADD 12h decision and carry boundary, not later grammar handlers.",
        ),
        FiniteModel(
            "precedence handler family", "38:7010–7029",
            "256 grammar classes × all 256 C values",
            tuple((grammar, level) for grammar in bytes_domain for level in bytes_domain),
            lambda state: (
                "postfix_478c" if state[1] == 2
                else "leaf_7175" if state[1] == 3
                else "base_table_4000"
            ),
            "Models handler-family selection; the computed table destination and recursive handler state remain separate.",
        ),
        FiniteModel(
            "command finalization gate", "02:5676–568A", "all 256 C values",
            bytes_domain,
            lambda value: (
                "explicit_rparen" if value == 0x11
                else "left_paren_form" if value == 0x10
                else "unit_form" if value == 0x01
                else "implicit_statement_end" if value == 0
                else "syntax_error"
            ),
            "Models the first gate only; the three cleanup continuations execute outside this bounded decision.",
        ),
        FiniteModel(
            "control-flow table dispatch", "33:436B–4380", "all 256 incoming A values",
            bytes_domain,
            lambda value: (
                "error_below_20" if value < 0x20
                else f"table_row_{value - 0x20:02x}" if value < 0x2D
                else "error_at_or_above_2d"
            ),
            "Models bounds and table index; loop-frame and handler bodies remain external.",
        ),
    )


def block_transition(depth: int, token: int, followed_by_then: bool) -> str:
    if token == 0xD0:
        return "stop_else" if depth == 0 else "skip_nested_else"
    if token == 0xD4:
        return "stop_end" if depth == 0 else "close_nested"
    if token in {0xD1, 0xD2, 0xD3}:
        return "open_loop_wrap" if depth == 0xFFFF else "open_loop"
    if token == 0xCE:
        if not followed_by_then:
            return "single_line_if"
        return "open_if_wrap" if depth == 0xFFFF else "open_if_then"
    return "scan_ordinary"


def analyze_model(model: FiniteModel) -> dict[str, object]:
    classes: dict[str, list[object]] = defaultdict(list)
    for value in model.inputs:
        classes[model.classify(value)].append(value)
    labels = sorted(classes)
    # Every input has one semantic class.  Feed one stable witness per class to
    # Z3 instead of creating (for the block model) 131,072 equivalent Boolean
    # variables.  Exhaustive enumeration above proves the class partition;
    # Z3 proves the smallest representative cover of that partition.
    witness_indices = [model.inputs.index(classes[label][0]) for label in labels]
    candidates = [str(index) for index in witness_indices]
    cover = z3_minimum_cover(
        candidates,
        {str(index): {model.classify(model.inputs[index])} for index in witness_indices},
    )

    def render(value: object) -> object:
        if isinstance(value, tuple):
            return [int(item) if isinstance(item, bool) else item for item in value]
        return value

    return {
        "name": model.name,
        "rom": model.rom,
        "input_domain": model.domain,
        "states_exhausted": len(model.inputs),
        "semantic_outcomes": len(classes),
        "outcome_counts": {label: len(classes[label]) for label in labels},
        "minimum_representatives": {
            model.classify(model.inputs[int(index)]): render(model.inputs[int(index)])
            for index in cover
        },
        "minimum_representative_count": len(cover),
        "minimizer": "exact lexicographic Optimize set cover via Z3",
        "boundary": model.boundary,
    }


def conditional_instruction(instruction: Z80Instruction) -> bool:
    mnemonic = instruction.mnemonic
    operands = instruction.operands.replace(" ", "")
    if mnemonic in {"jr", "jp", "call"}:
        return "," in operands
    if mnemonic == "ret":
        return bool(operands)
    return mnemonic == "djnz"


def relative_target(instruction: Z80Instruction) -> int:
    displacement = int.from_bytes(instruction.data[-1:], "little", signed=True)
    return (instruction.end_address + displacement) & 0xFFFF


def build_branch_sites(rom: RomImage) -> tuple[BranchSite, ...]:
    components = {
        "block matching": (0x38, (0x4136, 0x4139, 0x413D, 0x414D, 0x4153, 0x415F, 0x4166, 0x416A, 0x416E, 0x4178, 0x417B)),
        "token scanning": (0x38, (0x4187, 0x418A, 0x4192, 0x4198)),
        "grammar dispatch": (0x38, (0x6FBC, 0x7014, 0x7018, 0x702F, 0x7032)),
        "command finalization": (0x02, (0x5679, 0x567D, 0x5681, 0x5684)),
        "control-flow dispatch": (0x33, (0x436D, 0x4372)),
    }
    pages = {
        page: {item.location.address: item for item in disassemble_page(rom, page)}
        for page in {page for page, _addresses in components.values()}
    }
    sites = []
    for component, (page, addresses) in components.items():
        for address in addresses:
            instruction = pages[page][address]
            if not conditional_instruction(instruction):
                raise ValueError(f"expected conditional instruction at {page:02X}:{address:04X}")
            if instruction.mnemonic in {"jr", "djnz"}:
                target_address = relative_target(instruction)
            elif instruction.mnemonic in {"jp", "call"}:
                target_address = direct_target(instruction)
                if target_address is None:
                    raise ValueError(f"missing target at {instruction.location}")
            else:
                target_address = None
            sites.append(BranchSite(
                component, instruction.location, instruction.text,
                instruction.mnemonic,
                None if target_address is None else logical_code_point(page, target_address),
                logical_code_point(page, instruction.end_address),
            ))
    return tuple(sites)


def classify_successor(site: BranchSite, space: str, address: int) -> str | None:
    if site.kind == "ret":
        return "fallthrough" if (space, address) == site.fallthrough else "returned"
    if site.target and (space, address) == site.target:
        return "taken"
    if (space, address) == site.fallthrough:
        return "fallthrough"
    return None


def scan_trace(
    label: str, path: Path, sites: tuple[BranchSite, ...]
) -> tuple[dict[str, object], set[str]]:
    index = {site.key: site for site in sites}
    outcomes: Counter[str] = Counter()
    hits: Counter[str] = Counter()
    unresolved = 0
    instruction_count = 0
    pending: BranchSite | None = None
    banker = make_banker("ti84p-reset")
    with path.open("rb") as stream:
        read_header(stream)
        records: Iterator[tuple[int, object]] = iter_records(stream)
        resolved = (
            resolve_instruction(banker, payload)[0]
            for record_type, payload in records
            if record_type == 0x01
        )
        for space, address, _flat, _page in resolved:
            if pending is not None:
                outcome = classify_successor(pending, space, address)
                if outcome is None:
                    unresolved += 1
                else:
                    outcomes[f"{pending.identifier}:{outcome}"] += 1
                pending = None
            site = index.get((space, address))
            if site is not None:
                hits[site.identifier] += 1
                pending = site
            instruction_count += 1
    features = {f"branch:{identifier}" for identifier in outcomes}
    features.update(f"semantic:{feature}" for feature in TRACE_FEATURES.get(label, set()))
    provenance = TRACE_PROVENANCE.get(label, "unspecified")
    termination = (
        "error"
        if label in ERROR_TRACES
        else "completed"
        if provenance == "natural_tibasic"
        else "probe_exit_or_error"
    )
    return ({
        "label": label,
        "provenance": provenance,
        "termination": termination,
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "instructions": instruction_count,
        "branch_sites_hit": len(hits),
        "branch_outcomes": dict(sorted(outcomes.items())),
        "unclassified_branch_successors": unresolved,
        "semantic_features": sorted(TRACE_FEATURES.get(label, set())),
    }, features)


def verify_rom_signatures(rom: RomImage) -> list[dict[str, str]]:
    signatures = (
        (0x00, 0x1FE8, "c5e521f61f010b00b7edb1e1c1c9"),
        (0x38, 0x4130, "110000cd6072d8fed02010"),
        (0x38, 0x4180, "cdda72ed435d96c8fe2a2009"),
        (0x38, 0x6FB7, "cdf870fef23802c6120e03184c"),
        (0x38, 0x7010, "4779fe02280bfe03280c210040"),
        (0x02, 0x5676, "79fe112848fe10282efe012837b7"),
        (0x33, 0x436B, "d620da1127fe0dd21127875f1600"),
    )
    rows = []
    for page, address, expected in signatures:
        actual = rom.bytes_at(page, address, len(bytes.fromhex(expected))).hex()
        if actual != expected:
            raise ValueError(
                f"ROM signature mismatch at {page:02X}:{address:04X}: {actual} != {expected}"
            )
        rows.append({"location": f"{page:02X}:{address:04X}", "sha256": hashlib.sha256(bytes.fromhex(actual)).hexdigest()})
    return rows


def build_report(rom_path: Path, traces: Sequence[tuple[str, Path]]) -> dict[str, object]:
    rom = RomImage.from_path(rom_path)
    if digest(rom_path) != TI84_PLUS_OS_255MP_SHA256:
        raise ValueError("ROM SHA-256 does not match the pinned TI-84 Plus OS 2.55MP image")
    signatures = verify_rom_signatures(rom)
    models = [analyze_model(model) for model in finite_models()]
    sites = build_branch_sites(rom)
    trace_rows = []
    trace_features: dict[str, set[str]] = {}
    for label, path in traces:
        row, features = scan_trace(label, path, sites)
        trace_rows.append(row)
        trace_features[label] = features
    labels = sorted(trace_features)
    selected = z3_minimum_cover(labels, trace_features) if labels else ()
    aggregate_outcomes: Counter[str] = Counter()
    outcomes_by_provenance: dict[str, Counter[str]] = defaultdict(Counter)
    for row in trace_rows:
        aggregate_outcomes.update(row["branch_outcomes"])
        outcomes_by_provenance[row["provenance"]].update(row["branch_outcomes"])
    branch_rows = []
    for site in sites:
        possible = ("returned", "fallthrough") if site.kind == "ret" else ("taken", "fallthrough")
        observed = {
            outcome: aggregate_outcomes[f"{site.identifier}:{outcome}"]
            for outcome in possible
            if aggregate_outcomes[f"{site.identifier}:{outcome}"]
        }
        branch_rows.append({
            "component": site.component,
            "location": site.identifier,
            "instruction": site.instruction,
            "target": None if site.target is None else format_code_point(site.target),
            "fallthrough": format_code_point(site.fallthrough),
            "observed": observed,
        })
    feature_universe = set().union(*trace_features.values()) if trace_features else set()
    outcome_features = {
        label: {feature for feature in features if feature.startswith("branch:")}
        for label, features in trace_features.items()
    }
    outcome_labels = sorted(
        label for label, features in outcome_features.items() if features
    )
    selected_outcomes = (
        z3_minimum_cover(outcome_labels, outcome_features) if outcome_labels else ()
    )
    return {
        "schema": 2,
        "rom": {"path": "tools/rom.bin", "sha256": digest(rom_path)},
        "scope": {
            "claim": "bounded TI-BASIC parser decisions plus provenance-labeled outcomes from natural programs and exact-ROM probes",
            "not_a_claim": "natural reachability of probe-only states, complete TI-BASIC grammar, arbitrary token-stream, error-state, floating-point, VAT, or whole-ROM path coverage",
        },
        "rom_signatures": signatures,
        "finite_models": models,
        "finite_summary": {
            "models": len(models),
            "states_exhausted": sum(row["states_exhausted"] for row in models),
            "semantic_outcomes": sum(row["semantic_outcomes"] for row in models),
            "minimum_representatives": sum(row["minimum_representative_count"] for row in models),
        },
        "dynamic": {
            "trace_count": len(trace_rows),
            "branch_sites": len(sites),
            "branch_outcomes_possible": 2 * len(sites),
            "branch_outcomes_observed": len(aggregate_outcomes),
            "branch_outcomes_observed_by_provenance": {
                provenance: len(outcomes)
                for provenance, outcomes in sorted(outcomes_by_provenance.items())
            },
            "traces": sorted(trace_rows, key=lambda row: row["label"]),
            "branches": branch_rows,
            "minimum_diverse_corpus": {
                "algorithm": "exact lexicographic Optimize set cover via Z3",
                "objective": "preserve every observed branch outcome and semantic interpreter feature",
                "source_trace_count": len(labels),
                "selected_trace_count": len(selected),
                "selected": list(selected),
                "omitted": sorted(set(labels) - set(selected)),
                "covered_features": len(feature_universe),
                "feature_kinds": dict(sorted(Counter(feature.partition(":")[0] for feature in feature_universe).items())),
                "proven_minimum": True,
            },
            "minimum_outcome_corpus": {
                "algorithm": "exact lexicographic Optimize set cover via Z3",
                "objective": "preserve every observed branch outcome",
                "source_trace_count": len(outcome_labels),
                "selected_trace_count": len(selected_outcomes),
                "selected": list(selected_outcomes),
                "omitted": sorted(set(outcome_labels) - set(selected_outcomes)),
                "covered_outcomes": len(aggregate_outcomes),
                "proven_minimum": True,
            },
        },
        "open_paths": [
            "computed parser-handler destinations and recursive handler bodies",
            "arbitrary-length token streams, quoted strings, and nested blocks",
            "loop-frame byte layout and error unwinding",
            "floating-point, VAT, list, graph, and display subsystem internals",
            "natural-program witnesses for outcomes currently reached only by probes",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--trace", action="append", type=parse_trace, default=[])
    args = parser.parse_args()
    labels = [label for label, _path in args.trace]
    if len(labels) != len(set(labels)):
        parser.error("trace labels must be unique")
    try:
        report = build_report(args.rom, args.trace)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    finite = report["finite_summary"]
    dynamic = report["dynamic"]
    print(
        f"wrote {args.output}: {finite['states_exhausted']:,} finite states, "
        f"{finite['semantic_outcomes']} outcomes; "
        f"{dynamic['branch_outcomes_observed']}/{dynamic['branch_outcomes_possible']} "
        "dynamic branch outcomes"
    )


if __name__ == "__main__":
    main()
