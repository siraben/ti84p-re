"""Build typed direct, bcall, and cross-page ROM reference reports."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from rom_image import RomImage, RomLocation
from z80_disassembly import (
    BjumpSite,
    Z80Instruction,
    direct_target,
    disassemble_page,
    disassemble_rom,
    find_bcall_sites,
    find_bjump_sites,
)


def _instruction_report(
    instruction: Z80Instruction, *, match: bool
) -> dict[str, Any]:
    return {
        "location": str(instruction.location),
        "bytes": instruction.data.hex(),
        "instruction": instruction.text,
        "match": match,
    }


def resolved_direct_target(page: int, target: int) -> str:
    """Render the address space implied by a direct ROM CALL or JP."""

    if target < 0x4000:
        return f"00:{target:04X}"
    if target < 0x8000:
        if page == 0:
            return f"banked:{target:04X}"
        return f"{page:02X}:{target:04X}"
    return f"ram:{target:04X}"


def call_reports_for_page(
    rom: RomImage,
    page: int,
    instructions: Sequence[Z80Instruction],
    targets: frozenset[int],
    *,
    bcall: bool,
    before: int,
    after: int,
) -> list[dict[str, Any]]:
    """Build direct-reference or raw-bcall reports for one ROM page.

    The reports retain surrounding linear disassembly. They are candidate
    records, not claims that every decoded site is reachable code.
    """

    bcall_sites = (
        {site.location.address: site for site in find_bcall_sites(rom, page, targets)}
        if bcall
        else {}
    )
    reports = []
    for index, instruction in enumerate(instructions):
        if bcall:
            site = bcall_sites.get(instruction.location.address)
            if site is None:
                continue
            target = site.id
            sequence_bytes = bytes((0xEF, target & 0xFF, target >> 8))
        else:
            target = direct_target(instruction)
            if target not in targets:
                continue
            sequence_bytes = instruction.data
        start = max(0, index - before)
        stop = min(len(instructions), index + after + 1)
        reports.append(
            {
                "location": str(instruction.location),
                "bytes": sequence_bytes.hex(),
                "instruction": "rst 28h" if bcall else instruction.text,
                "kind": "bcall" if bcall else "direct",
                "target": target,
                "resolved_target": (
                    None if bcall else resolved_direct_target(page, target)
                ),
                "context": [
                    _instruction_report(context, match=context_index == index)
                    for context_index, context in enumerate(
                        instructions[start:stop], start=start
                    )
                ],
            }
        )
    return reports


def bjump_reports_for_page(
    rom: RomImage,
    page: int,
    instructions: Sequence[Z80Instruction],
    targets: frozenset[RomLocation],
    *,
    before: int,
    after: int,
) -> list[dict[str, Any]]:
    """Build inline cross-page descriptor reports for one ROM page."""

    sites = {
        site.location.address: site for site in find_bjump_sites(rom, page, targets)
    }
    reports = []
    for index, instruction in enumerate(instructions):
        site = sites.get(instruction.location.address)
        if site is None:
            continue
        start = max(0, index - before)
        stop = min(len(instructions), index + after + 1)
        reports.append(
            {
                "location": str(instruction.location),
                "bytes": rom.bytes_at(page, instruction.location.address, 6).hex(),
                "instruction": instruction.text,
                "kind": "bjump",
                "target": str(site.target),
                "target_page": site.target.page,
                "target_address": site.target.address,
                "raw_page": site.raw_page,
                "context": [
                    _instruction_report(context, match=context_index == index)
                    for context_index, context in enumerate(
                        instructions[start:stop], start=start
                    )
                ],
            }
        )
    return reports


def bjump_call_reports_for_page(
    instructions: Sequence[Z80Instruction],
    stubs: Sequence[BjumpSite],
    *,
    before: int,
    after: int,
) -> list[dict[str, Any]]:
    """Build reports for direct calls to page-0 bjump trampoline stubs.

    A stub is a ``CALL 2B09h`` followed by an inline target descriptor. The
    caller invokes the stub's page-0 address, so resolving the extra layer
    exposes the physical bank and logical destination.
    """

    by_address = {stub.location.address: stub for stub in stubs}
    reports = []
    for index, instruction in enumerate(instructions):
        stub = by_address.get(direct_target(instruction))
        if stub is None:
            continue
        start = max(0, index - before)
        stop = min(len(instructions), index + after + 1)
        reports.append(
            {
                "location": str(instruction.location),
                "bytes": instruction.data.hex(),
                "instruction": instruction.text,
                "kind": "bjump-call",
                "stub": str(stub.location),
                "target": str(stub.target),
                "target_page": stub.target.page,
                "target_address": stub.target.address,
                "raw_page": stub.raw_page,
                "context": [
                    _instruction_report(context, match=context_index == index)
                    for context_index, context in enumerate(
                        instructions[start:stop], start=start
                    )
                ],
            }
        )
    return reports


def analyze_calls(
    rom: RomImage,
    targets: frozenset[int],
    *,
    bcall: bool = False,
    before: int = 0,
    after: int = 0,
    executable: str = "z80dasm",
    pages: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    """Return direct-reference or raw-bcall candidates across a ROM."""

    reports = []
    disassemblies = (
        disassemble_rom(rom, executable=executable)
        if pages is None
        else (
            (page, disassemble_page(rom, page, executable=executable))
            for page in pages
        )
    )
    for page, instructions in disassemblies:
        reports.extend(
            call_reports_for_page(
                rom,
                page,
                instructions,
                targets,
                bcall=bcall,
                before=before,
                after=after,
            )
        )
    return reports


def analyze_bjumps(
    rom: RomImage,
    targets: frozenset[RomLocation],
    *,
    before: int = 0,
    after: int = 0,
    executable: str = "z80dasm",
    pages: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    """Return inline cross-page jump candidates across a ROM."""

    reports = []
    disassemblies = (
        disassemble_rom(rom, executable=executable)
        if pages is None
        else (
            (page, disassemble_page(rom, page, executable=executable))
            for page in pages
        )
    )
    for page, instructions in disassemblies:
        reports.extend(
            bjump_reports_for_page(
                rom,
                page,
                instructions,
                targets,
                before=before,
                after=after,
            )
        )
    return reports


def analyze_bjump_calls(
    rom: RomImage,
    targets: frozenset[RomLocation] | None,
    *,
    before: int = 0,
    after: int = 0,
    executable: str = "z80dasm",
    pages: Iterable[int] | None = None,
    target_pages: frozenset[int] | None = None,
) -> list[dict[str, Any]]:
    """Return callers of page-0 stubs that dispatch to requested targets."""

    stubs = tuple(
        stub
        for stub in find_bjump_sites(rom, 0, targets)
        if target_pages is None or stub.target.page in target_pages
    )
    reports = []
    disassemblies = (
        disassemble_rom(rom, executable=executable)
        if pages is None
        else (
            (page, disassemble_page(rom, page, executable=executable))
            for page in pages
        )
    )
    for _page, instructions in disassemblies:
        reports.extend(
            bjump_call_reports_for_page(
                instructions,
                stubs,
                before=before,
                after=after,
            )
        )
    return reports
