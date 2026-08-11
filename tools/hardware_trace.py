"""Higher-level, importable access to resolved TilEm hardware traces."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from tilem_trace_resolve import (
    IDX_AF,
    IDX_BC,
    IDX_CLOCK,
    IDX_DE,
    IDX_HL,
    IDX_IX,
    IDX_IY,
    IDX_OPCODE,
    IDX_PC,
    IDX_SP,
    IDX_WZ,
    Banker,
    decode_io_event,
    iter_records,
    read_header,
    resolve_instruction,
)


@dataclass(frozen=True)
class TraceHeader:
    version: int
    flags: int
    range_start: int
    range_end: int


@dataclass(frozen=True)
class ResolvedIoEvent:
    instruction_index: int
    clock: int
    logical_pc: int
    space: str
    address: int
    direction: str
    port: int
    value: int | None
    form: str


@dataclass(frozen=True)
class ResolvedInstruction:
    """One instruction resolved through the replayed memory mapping."""

    instruction_index: int
    clock: int
    logical_pc: int
    space: str
    address: int
    flat_address: int | None
    page: int | None
    physical_page: int | None
    opcode: int
    af: int
    bc: int
    de: int
    hl: int
    ix: int
    iy: int
    sp: int
    wz: int


@dataclass(frozen=True)
class ResolvedExecution:
    """One resolved instruction and its optional decoded I/O operation."""

    instruction: ResolvedInstruction
    io_event: ResolvedIoEvent | None


@dataclass(frozen=True)
class ResolvedMemoryWrite:
    """One logical write attributed to the instruction that generated it."""

    instruction_index: int
    clock: int
    logical_pc: int
    pc_space: str
    pc_address: int
    logical_address: int
    value: int
    target_kind: str | None
    target_page: int | None
    page_offset: int | None
    flat_address: int | None
    unresolved: bool


@dataclass(frozen=True)
class TracePointCounts:
    """Constant-memory hit counts for selected resolved instruction points."""

    processed_instructions: int
    counts: dict[tuple[str, int], int]


def make_banker(
    initial_mapping: str = "unknown",
    *,
    initial_port4: int | None = None,
    initial_port5: int | None = None,
    initial_port6: int | None = None,
    initial_port7: int | None = None,
    initial_port27: int | None = None,
    initial_port28: int | None = None,
) -> Banker:
    """Construct a mapping replay state from a named or explicit initial map."""

    explicit = (
        initial_port4,
        initial_port5,
        initial_port6,
        initial_port7,
        initial_port27,
        initial_port28,
    )
    if initial_mapping == "ti84p-reset":
        if any(value is not None for value in explicit):
            raise ValueError(
                "ti84p-reset cannot be combined with explicit initial ports"
            )
        return Banker.ti84p_reset()
    if initial_mapping != "unknown":
        raise ValueError(f"unknown initial mapping: {initial_mapping}")
    return Banker(
        initial_port4=initial_port4,
        initial_port5=initial_port5,
        initial_port6=initial_port6,
        initial_port7=initial_port7,
        initial_port27=initial_port27,
        initial_port28=initial_port28,
    )


def trace_header(path: Path) -> TraceHeader:
    """Read the fixed trace metadata without consuming its records."""

    with path.open("rb") as fp:
        header = read_header(fp)
    return TraceHeader(
        version=header["version"],
        flags=header["flags"],
        range_start=header["range_start"],
        range_end=header["range_end"],
    )


def resolve_memory_target(
    banker: Banker, logical_address: int
) -> tuple[str | None, int | None, int | None, int | None, bool]:
    """Resolve a logical write to kind, page, page offset, and Flash offset."""

    region = logical_address >> 14
    kind, page = banker.mapped_address(logical_address)
    unresolved = bool(region and page is None)
    if page is None:
        return kind, None, None, None, unresolved
    page_offset = logical_address & 0x3FFF
    flat_address = page * 0x4000 + page_offset if kind == "flash" else None
    return kind, page, page_offset, flat_address, False


class MemoryWriteAttributor:
    """Buffer TLMT writes until their following instruction record arrives."""

    def __init__(self, banker: Banker):
        self.banker = banker
        self.pending: list[
            tuple[
                int,
                int,
                str | None,
                int | None,
                int | None,
                int | None,
                bool,
            ]
        ] = []
        self.instruction_index = 0

    def feed(self, record_type: int, payload: tuple) -> list[ResolvedMemoryWrite]:
        """Consume one TLMT record and return newly attributed writes."""

        if record_type == 0x02:
            logical_address, value = payload
            target = resolve_memory_target(self.banker, logical_address)
            self.pending.append((logical_address, value, *target))
            return []
        if record_type != 0x01:
            return []

        pc_space, pc_address, _flat, _page = self.banker.resolve(payload[IDX_PC])
        events = [
            ResolvedMemoryWrite(
                instruction_index=self.instruction_index,
                clock=payload[IDX_CLOCK],
                logical_pc=payload[IDX_PC],
                pc_space=pc_space,
                pc_address=pc_address,
                logical_address=logical_address,
                value=value,
                target_kind=kind,
                target_page=page,
                page_offset=page_offset,
                flat_address=flat_address,
                unresolved=unresolved,
            )
            for (
                logical_address,
                value,
                kind,
                page,
                page_offset,
                flat_address,
                unresolved,
            ) in self.pending
        ]
        self.pending.clear()
        resolve_instruction(self.banker, payload)
        self.instruction_index += 1
        return events


def iter_resolved_memory_writes(
    path: Path,
    *,
    target_kinds: set[str] | None = None,
    target_pages: set[int] | None = None,
    initial_mapping: str = "unknown",
    initial_port4: int | None = None,
    initial_port5: int | None = None,
    initial_port6: int | None = None,
    initial_port7: int | None = None,
    initial_port27: int | None = None,
    initial_port28: int | None = None,
    resync: bool = False,
) -> Iterator[ResolvedMemoryWrite]:
    """Yield resolved memory writes while replaying the trace mapping."""

    banker = make_banker(
        initial_mapping,
        initial_port4=initial_port4,
        initial_port5=initial_port5,
        initial_port6=initial_port6,
        initial_port7=initial_port7,
        initial_port27=initial_port27,
        initial_port28=initial_port28,
    )
    attributor = MemoryWriteAttributor(banker)
    with path.open("rb") as fp:
        read_header(fp)
        for record_type, payload in iter_records(fp, resync=resync):
            for event in attributor.feed(record_type, payload):
                if target_kinds is not None and event.target_kind not in target_kinds:
                    continue
                if target_pages is not None and event.target_page not in target_pages:
                    continue
                yield event


def iter_resolved_executions(
    path: Path,
    *,
    initial_mapping: str = "unknown",
    initial_port4: int | None = None,
    initial_port5: int | None = None,
    initial_port6: int | None = None,
    initial_port7: int | None = None,
    initial_port27: int | None = None,
    initial_port28: int | None = None,
    resync: bool = False,
    decode_io: bool = True,
) -> Iterator[ResolvedExecution]:
    """Yield instructions and decoded I/O in one streaming mapping replay."""

    banker = make_banker(
        initial_mapping,
        initial_port4=initial_port4,
        initial_port5=initial_port5,
        initial_port6=initial_port6,
        initial_port7=initial_port7,
        initial_port27=initial_port27,
        initial_port28=initial_port28,
    )
    instruction_index = 0
    with path.open("rb") as fp:
        read_header(fp)
        for record_type, payload in iter_records(fp, resync=resync):
            if record_type != 0x01:
                continue
            physical_kind, physical_page = banker.mapped_address(payload[IDX_PC])
            (space, address, flat_address, page), _switch = resolve_instruction(
                banker, payload
            )
            instruction = ResolvedInstruction(
                instruction_index=instruction_index,
                clock=payload[IDX_CLOCK],
                logical_pc=payload[IDX_PC],
                space=space,
                address=address,
                flat_address=flat_address,
                page=page,
                physical_page=(
                    physical_page & 0x7F
                    if physical_kind == "ram" and physical_page is not None
                    else None
                ),
                opcode=payload[IDX_OPCODE],
                af=payload[IDX_AF],
                bc=payload[IDX_BC],
                de=payload[IDX_DE],
                hl=payload[IDX_HL],
                ix=payload[IDX_IX],
                iy=payload[IDX_IY],
                sp=payload[IDX_SP],
                wz=payload[IDX_WZ],
            )
            decoded = decode_io_event(payload) if decode_io else None
            io_event = None
            if decoded is not None:
                direction, port, value, form = decoded
                io_event = ResolvedIoEvent(
                    instruction_index=instruction_index,
                    clock=payload[IDX_CLOCK],
                    logical_pc=payload[IDX_PC],
                    space=space,
                    address=address,
                    direction=direction,
                    port=port,
                    value=value,
                    form=form,
                )
            yield ResolvedExecution(instruction, io_event)
            instruction_index += 1


def iter_resolved_instructions(
    path: Path,
    *,
    initial_mapping: str = "unknown",
    initial_port4: int | None = None,
    initial_port5: int | None = None,
    initial_port6: int | None = None,
    initial_port7: int | None = None,
    initial_port27: int | None = None,
    initial_port28: int | None = None,
    resync: bool = False,
) -> Iterator[ResolvedInstruction]:
    """Yield resolved instructions while replaying the trace mapping."""

    for execution in iter_resolved_executions(
        path,
        initial_mapping=initial_mapping,
        initial_port4=initial_port4,
        initial_port5=initial_port5,
        initial_port6=initial_port6,
        initial_port7=initial_port7,
        initial_port27=initial_port27,
        initial_port28=initial_port28,
        resync=resync,
        decode_io=False,
    ):
        yield execution.instruction


def iter_resolved_io_events(
    path: Path,
    *,
    ports: set[int] | None = None,
    initial_mapping: str = "unknown",
    initial_port4: int | None = None,
    initial_port5: int | None = None,
    initial_port6: int | None = None,
    initial_port7: int | None = None,
    initial_port27: int | None = None,
    initial_port28: int | None = None,
    resync: bool = False,
) -> Iterator[ResolvedIoEvent]:
    """Yield resolved I/O instructions while replaying the trace mapping."""

    for execution in iter_resolved_executions(
        path,
        initial_mapping=initial_mapping,
        initial_port4=initial_port4,
        initial_port5=initial_port5,
        initial_port6=initial_port6,
        initial_port7=initial_port7,
        initial_port27=initial_port27,
        initial_port28=initial_port28,
        resync=resync,
    ):
        if execution.io_event is not None and (
            ports is None or execution.io_event.port in ports
        ):
            yield execution.io_event


def count_resolved_trace_points(
    path: Path,
    points: set[tuple[str, int]] | frozenset[tuple[str, int]],
    *,
    initial_mapping: str = "unknown",
    initial_port4: int | None = None,
    initial_port5: int | None = None,
    initial_port6: int | None = None,
    initial_port7: int | None = None,
    initial_port27: int | None = None,
    initial_port28: int | None = None,
    resync: bool = False,
) -> TracePointCounts:
    """Count selected resolved PCs without allocating per-instruction objects.

    Mapping writes still replay for every instruction. Only requested points
    enter the retained counter, which keeps memory use independent of trace
    length and avoids constructing the higher-level execution dataclasses.
    """

    banker = make_banker(
        initial_mapping,
        initial_port4=initial_port4,
        initial_port5=initial_port5,
        initial_port6=initial_port6,
        initial_port7=initial_port7,
        initial_port27=initial_port27,
        initial_port28=initial_port28,
    )
    wanted = frozenset(points)
    counts: Counter[tuple[str, int]] = Counter()
    processed = 0
    with path.open("rb") as fp:
        read_header(fp)
        for record_type, payload in iter_records(fp, resync=resync):
            if record_type != 0x01:
                continue
            (space, address, _flat_address, _page), _switch = resolve_instruction(
                banker, payload
            )
            point = (space, address)
            if point in wanted:
                counts[point] += 1
            processed += 1
    return TracePointCounts(processed, dict(counts))
