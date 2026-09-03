"""Verify prefixed-opcode M1 placement in pinned emulator source trees."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from ti84re.hardware.bus_timing import PREFIX_M1_PROBE_CASES
from ti84re.emulators.tilem.core import TILEM_COMMIT, TILEM_TREE, validate_tilem_source
from ti84re.emulators.wabbitemu.headless import (
    WABBITEMU_COMMIT,
    WABBITEMU_TREE_SHA256,
    validate_pinned_source,
)


class PrefixFetchModelError(ValueError):
    """A pinned source tree no longer exposes the checked fetch structure."""


@dataclass(frozen=True)
class PrefixFetchModelReport:
    """One emulator's source-derived prefix-fetch classification."""

    emulator: str
    revision: str
    source_identity: str
    indexed_cb_m1_fetches: int
    indexed_cb_final_opcode_path: str
    source_sites: tuple[str, ...]
    case_m1_fetches: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable source report."""

        return asdict(self)


def _read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise PrefixFetchModelError(f"cannot read pinned source {path}: {error}") from error


def _require_once(text: str, fragment: str, label: str) -> int:
    count = text.count(fragment)
    if count != 1:
        raise PrefixFetchModelError(
            f"pinned source must contain one {label}; found {count}"
        )
    return text[: text.index(fragment)].count("\n") + 1


def _case_counts(model: str) -> dict[str, int]:
    if model not in {"tilem", "wabbitemu"}:
        raise ValueError(f"unknown prefix-fetch model {model!r}")
    return {
        case.key: (
            case.tilem_m1_fetches
            if model == "tilem"
            else case.wabbitemu_m1_fetches
        )
        for case in PREFIX_M1_PROBE_CASES
    }


def analyze_tilem_prefix_fetches(source: Path) -> PrefixFetchModelReport:
    """Verify TilEm's M1 and indexed-CB read paths at the pinned commit."""

    validate_tilem_source(source)
    main = _read_source(source / "emu/z80main.h")
    indexed = _read_source(source / "emu/z80ddfd.h")
    memory = _read_source(source / "emu/x4/x4_memory.c")
    main_line = _require_once(
        main,
        "case 0xDD:\n\t op = readb_m1(PC++);",
        "DD-prefix M1 fetch",
    )
    indexed_line = _require_once(
        indexed,
        "case 0xCB:\n\t offs = (int) (signed char) readb(PC++);\n"
        "\t WZ = RegHL + offs;\n\t op = readb(PC++);",
        "indexed-CB displacement and final-opcode read path",
    )
    memory_line = _require_once(
        memory,
        "byte x4_z80_rdmem_m1(TilemCalc* calc, dword A)",
        "TI-84 Plus M1 memory callback",
    )
    return PrefixFetchModelReport(
        emulator="TilEm",
        revision=TILEM_COMMIT,
        source_identity=f"git-tree:{TILEM_TREE}",
        indexed_cb_m1_fetches=2,
        indexed_cb_final_opcode_path="ordinary readb, not readb_m1",
        source_sites=(
            f"emu/z80main.h:{main_line}",
            f"emu/z80ddfd.h:{indexed_line}",
            f"emu/x4/x4_memory.c:{memory_line}",
        ),
        case_m1_fetches=_case_counts("tilem"),
    )


def analyze_wabbitemu_prefix_fetches(source: Path) -> PrefixFetchModelReport:
    """Verify Wabbitemu's M1 and indexed-CB paths at the pinned commit."""

    validate_pinned_source(source)
    core = _read_source(source / "core/core.c")
    fetch_line = _require_once(
        core,
        "static int CPU_opcode_fetch(CPU_t *cpu)",
        "opcode-fetch function",
    )
    indexed_line = _require_once(
        core,
        "if (cpu->prefix) {\n\t\tCPU_mem_read(cpu, cpu->pc++);"
        "\t\t\t\t//read the offset, NOT INST\n\t\tchar offset = cpu->bus;\n"
        "\t\tCPU_opcode_fetch(cpu);\t\t\t\t\t\t//CB opcode, this is an INST",
        "indexed-CB displacement and final-opcode fetch path",
    )
    compensation_line = _require_once(
        core,
        "cpu->r = ((cpu->r - 1) & 0x7f) + (cpu->r & 0x80);",
        "indexed-CB R-register compensation",
    )
    return PrefixFetchModelReport(
        emulator="Wabbitemu",
        revision=WABBITEMU_COMMIT,
        source_identity=f"tree-sha256:{WABBITEMU_TREE_SHA256}",
        indexed_cb_m1_fetches=3,
        indexed_cb_final_opcode_path=(
            "CPU_opcode_fetch wait path followed by R-register compensation"
        ),
        source_sites=(
            f"core/core.c:{fetch_line}",
            f"core/core.c:{indexed_line}",
            f"core/core.c:{compensation_line}",
        ),
        case_m1_fetches=_case_counts("wabbitemu"),
    )


def compare_prefix_fetch_models(
    tilem_source: Path,
    wabbitemu_source: Path,
) -> dict[str, object]:
    """Return the pinned source reports and their indexed-CB disagreement."""

    tilem = analyze_tilem_prefix_fetches(tilem_source)
    wabbitemu = analyze_wabbitemu_prefix_fetches(wabbitemu_source)
    return {
        "models": [tilem.to_dict(), wabbitemu.to_dict()],
        "indexed_cb_disagreement": {
            "tilem_m1_fetches": tilem.indexed_cb_m1_fetches,
            "wabbitemu_m1_fetches": wabbitemu.indexed_cb_m1_fetches,
            "physical_result": None,
        },
        "evidence_scope": (
            "exact pinned emulator source structure; not emulator runtime or "
            "physical ASIC timing"
        ),
    }
