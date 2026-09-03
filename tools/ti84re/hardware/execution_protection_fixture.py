"""Guarded ROM fixtures and trace reports for Flash execution protection."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from ti84re.file_hashes import file_sha256
from ti84re.trace.hardware import iter_resolved_instructions
from ti84re.rom.signatures import TI84_PLUS_OS_255MP_SHA256
from ti84re.tifiles.program import asm_call_body, asmprgm_body, encode_program_file

PAGE_SIZE = 0x4000
ROM_SIZE = 0x100000
PROGRAM_ORIGIN = 0x9D95
TARGET_ADDRESS = 0x7FF0
TARGET_SIZE = 6
RAM_TARGET_MIN = 0x4000
RAM_MODE_IMMEDIATE_OFFSET = 0xFC1D6
SOURCE_ROM_SHA256 = TI84_PLUS_OS_255MP_SHA256
ERASED_TARGET = bytes((0xFF,)) * TARGET_SIZE


@dataclass(frozen=True)
class FlashExecutionFixture:
    """One exact-ROM page-boundary execution fixture."""

    page: int
    marker: int
    rom: bytes
    program: bytes
    runner: bytes
    call_address: int
    return_address: int
    source_rom_sha256: str
    fixture_rom_sha256: str
    machine_code_sha256: str

    @property
    def program_name(self) -> str:
        return f"EXECP{self.page:02X}"

    @property
    def runner_name(self) -> str:
        return f"AREX{self.page:02X}"


@dataclass(frozen=True)
class FlashExecutionTraceResult:
    """Observed control-flow outcome for one emulator trace."""

    page: int
    classification: str
    call_visits: int
    target_visits: int
    target_followup_visits: int
    return_visits: int
    resets_after_call: int
    call_clock: int | None
    target_clock: int | None
    target_followup_clock: int | None
    return_clock: int | None
    reset_clock: int | None
    trace_sha256: str


@dataclass(frozen=True)
class RamExecutionProbe:
    """One validated RAM execution-protection probe."""

    physical_page: int
    page_offset: int
    selector: int
    target_address: int
    marker: int
    machine_code: bytes
    call_address: int
    return_address: int
    machine_code_sha256: str


@dataclass(frozen=True)
class RamExecutionTarget:
    """One RAM execution mode, physical page, and page-offset test point."""

    mode: int
    physical_page: int
    page_offset: int

    def __post_init__(self) -> None:
        if not 0 <= self.mode <= 3:
            raise ValueError("RAM execution mode must be between 0 and 3")
        if not 0 <= self.physical_page < 8:
            raise ValueError("physical RAM page must be between 0 and 7")
        ram_target_address(self.page_offset)

    @property
    def name(self) -> str:
        return (
            f"mode-{self.mode}-page-{self.physical_page}-"
            f"offset-{self.page_offset:04x}"
        )

    @property
    def marker(self) -> int:
        return ram_probe_marker(self.mode, self.physical_page)


@dataclass(frozen=True)
class TilemRamExecutionFixture:
    """One exact-ROM TilEm fixture with a selected boot RAM mode."""

    mode: int
    probe: RamExecutionProbe
    rom: bytes
    program: bytes
    runner: bytes
    source_rom_sha256: str
    fixture_rom_sha256: str

    @property
    def program_name(self) -> str:
        return (
            f"RE{self.mode}{self.probe.physical_page}"
            f"{self.probe.page_offset:04X}"
        )

    @property
    def runner_name(self) -> str:
        return (
            f"AR{self.mode}{self.probe.physical_page}"
            f"{self.probe.page_offset:04X}"
        )


@dataclass(frozen=True)
class RamExecutionTraceResult:
    """Observed TilEm control-flow outcome for one RAM target."""

    mode: int
    physical_page: int
    page_offset: int
    classification: str
    call_visits: int
    target_visits: int
    target_followup_visits: int
    return_visits: int
    resets_after_call: int
    call_clock: int | None
    target_clock: int | None
    target_followup_clock: int | None
    return_clock: int | None
    reset_clock: int | None
    trace_sha256: str


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def file_digest(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a potentially large trace without loading it as one byte string."""

    return file_sha256(path, chunk_size=chunk_size)


def validate_source_rom(source_rom: bytes) -> str:
    """Require the exact complete local OS 2.55MP ROM and return its hash."""

    source_digest = digest(source_rom)
    if len(source_rom) != ROM_SIZE or source_digest != SOURCE_ROM_SHA256:
        raise ValueError("fixture requires the exact local OS 2.55MP ROM")
    return source_digest


def assemble_probe(source: Path, page: int, output: Path, *, spasm: str = "spasm") -> bytes:
    """Assemble one guarded execution-protection probe."""

    marker_routine(page)
    completed = subprocess.run(
        [spasm, "-N", f"-DTARGET_PAGE=${page:02X}", str(source), str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"SPASM failed for page 0x{page:02X}: {detail}")
    try:
        return output.read_bytes()
    except OSError as error:
        raise RuntimeError(
            f"SPASM produced no output for page 0x{page:02X}: {error}"
        ) from error


def ram_target_address(page_offset: int) -> int:
    """Return the bank-A logical address for one physical RAM-page offset."""

    if not 0 <= page_offset <= PAGE_SIZE - TARGET_SIZE:
        raise ValueError("RAM target offset must leave room for the marker routine")
    return RAM_TARGET_MIN + page_offset


def ram_marker_routine(marker: int) -> bytes:
    """Return ``LD A,marker; LD (8478h),A; RET`` for a RAM target."""

    if not 0 <= marker <= 0xFF:
        raise ValueError("RAM marker must be a byte")
    return bytes((0x3E, marker, 0x32, 0x78, 0x84, 0xC9))


def ram_probe_marker(mode: int, physical_page: int) -> int:
    """Return the native-harness marker for one mode and physical page."""

    if not 0 <= mode <= 3:
        raise ValueError("RAM execution mode must be between 0 and 3")
    if not 0 <= physical_page < 8:
        raise ValueError("physical RAM page must be between 0 and 7")
    return 0x40 | (mode << 3) | physical_page


def assemble_ram_probe(
    source: Path,
    physical_page: int,
    page_offset: int,
    marker: int,
    output: Path,
    *,
    spasm: str = "spasm",
) -> bytes:
    """Assemble one guarded RAM execution-protection probe."""

    if not 0 <= physical_page < 8:
        raise ValueError("physical RAM page must be between 0 and 7")
    target_address = ram_target_address(page_offset)
    ram_marker_routine(marker)
    selector = 0x80 | physical_page
    completed = subprocess.run(
        [
            spasm,
            "-N",
            f"-DTARGET_SELECTOR=${selector:02X}",
            f"-DTARGET_ADDRESS=${target_address:04X}",
            f"-DMARKER=${marker:02X}",
            str(source),
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            f"SPASM failed for RAM page 0x{selector:02X}, offset "
            f"0x{page_offset:04X}: {detail}"
        )
    try:
        return output.read_bytes()
    except OSError as error:
        raise RuntimeError(
            f"SPASM produced no RAM probe for page 0x{selector:02X}: {error}"
        ) from error


def validate_ram_probe_machine_code(
    machine_code: bytes,
    physical_page: int,
    page_offset: int,
    marker: int,
) -> tuple[int, int]:
    """Validate a guarded RAM probe and return its CALL and return addresses."""

    if not 0 <= physical_page < 8:
        raise ValueError("physical RAM page must be between 0 and 7")
    target_address = ram_target_address(page_offset)
    signature = ram_marker_routine(marker)
    selector = 0x80 | physical_page
    if not machine_code:
        raise ValueError("RAM execution-protection probe machine code is empty")
    for sequence, label in (
        (bytes((0x3E, selector, 0xD3, 0x06)), "target-page mapping write"),
        (bytes((0x21, target_address & 0xFF, target_address >> 8)), "target data read"),
        (bytes.fromhex("06061ABE20"), "six-byte signature loop"),
        (bytes.fromhex("3EA0327884"), "pre-call marker seed"),
        (signature, "target marker signature"),
    ):
        if machine_code.count(sequence) != 1:
            raise ValueError(f"RAM probe must contain one exact {label}")
    call = bytes((0xCD, target_address & 0xFF, target_address >> 8))
    if machine_code.count(call) != 1:
        raise ValueError("RAM probe must contain one exact target CALL")
    call_address = PROGRAM_ORIGIN + machine_code.index(call)
    return call_address, call_address + len(call)


def build_ram_execution_probe(
    machine_code: bytes,
    physical_page: int,
    page_offset: int,
    marker: int,
) -> RamExecutionProbe:
    """Return one hash-complete validated RAM execution probe."""

    call_address, return_address = validate_ram_probe_machine_code(
        machine_code,
        physical_page,
        page_offset,
        marker,
    )
    return RamExecutionProbe(
        physical_page=physical_page,
        page_offset=page_offset,
        selector=0x80 | physical_page,
        target_address=ram_target_address(page_offset),
        marker=marker,
        machine_code=machine_code,
        call_address=call_address,
        return_address=return_address,
        machine_code_sha256=digest(machine_code),
    )


def build_tilem_ram_execution_fixture(
    source_rom: bytes,
    machine_code: bytes,
    mode: int,
    physical_page: int,
    page_offset: int,
    marker: int,
) -> TilemRamExecutionFixture:
    """Patch the boot RAM mode and package one self-installing TilEm probe."""

    source_digest = validate_source_rom(source_rom)
    if not 0 <= mode <= 3:
        raise ValueError("RAM execution mode must be between 0 and 3")
    if source_rom[RAM_MODE_IMMEDIATE_OFFSET] != 0:
        raise ValueError("boot RAM-mode immediate is not the expected zero byte")
    probe = build_ram_execution_probe(
        machine_code,
        physical_page,
        page_offset,
        marker,
    )
    rom = bytearray(source_rom)
    rom[RAM_MODE_IMMEDIATE_OFFSET] = mode << 4
    program_name = f"RE{mode}{physical_page}{page_offset:04X}"
    runner_name = f"AR{mode}{physical_page}{page_offset:04X}"
    comment = (
        f"RAM execution mode {mode}, page {physical_page}, "
        f"offset {page_offset:04X} probe"
    )
    return TilemRamExecutionFixture(
        mode=mode,
        probe=probe,
        rom=bytes(rom),
        program=encode_program_file(
            program_name,
            asmprgm_body(machine_code),
            comment=comment,
        ),
        runner=encode_program_file(
            runner_name,
            asm_call_body(program_name),
            comment=comment,
        ),
        source_rom_sha256=source_digest,
        fixture_rom_sha256=digest(rom),
    )


def marker_routine(page: int) -> bytes:
    """Return ``LD A,page; LD (8478h),A; RET`` for a boundary page."""

    if not 0 <= page <= 0x3F:
        raise ValueError("Flash page must be between 0x00 and 0x3F")
    return bytes((0x3E, page, 0x32, 0x78, 0x84, 0xC9))


def target_offset(page: int) -> int:
    """Return the flat ROM offset corresponding to ``page:7FF0``."""

    marker_routine(page)
    return page * PAGE_SIZE + TARGET_ADDRESS - 0x4000


def validate_probe_machine_code(machine_code: bytes, page: int) -> tuple[int, int]:
    """Validate the guarded probe and return its CALL and return addresses."""

    if not machine_code:
        raise ValueError("execution-protection probe machine code is empty")
    signature = marker_routine(page)
    if machine_code.count(signature) != 1:
        raise ValueError("probe must contain one exact target signature")
    for sequence, label in (
        (bytes((0x3E, page, 0xD3, 0x06)), "target-page mapping write"),
        (bytes.fromhex("21F07F"), "target data-read address"),
        (bytes.fromhex("06061ABE20"), "six-byte signature loop"),
        (bytes.fromhex("3EA0327884"), "pre-call OP1 marker"),
        (bytes.fromhex("3A788432"), "post-call marker capture"),
    ):
        if sequence not in machine_code:
            raise ValueError(f"probe lacks its {label}")
    call = bytes.fromhex("CDF07F")
    if machine_code.count(call) != 1:
        raise ValueError("probe must contain one CALL 7FF0h")
    if machine_code.count(bytes.fromhex("327884")) != 3:
        raise ValueError(
            "probe must contain target-signature, seed, and restore OP1 writes"
        )
    if machine_code.count(bytes.fromhex("D306")) != 2:
        raise ValueError("probe must map and restore port 0x06 exactly once")
    call_address = PROGRAM_ORIGIN + machine_code.index(call)
    return call_address, call_address + len(call)


def build_flash_execution_fixture(
    source_rom: bytes,
    machine_code: bytes,
    page: int,
) -> FlashExecutionFixture:
    """Patch one erased target and package its guarded assembly launcher."""

    source_digest = validate_source_rom(source_rom)
    call_address, return_address = validate_probe_machine_code(machine_code, page)
    offset = target_offset(page)
    if source_rom[offset : offset + TARGET_SIZE] != ERASED_TARGET:
        raise ValueError(f"page {page:02X}:7FF0 is not an erased six-byte span")

    rom = bytearray(source_rom)
    marker = marker_routine(page)
    rom[offset : offset + TARGET_SIZE] = marker
    program_name = f"EXECP{page:02X}"
    runner_name = f"AREX{page:02X}"
    comment = f"Execution-protection page {page:02X} probe"
    return FlashExecutionFixture(
        page=page,
        marker=page,
        rom=bytes(rom),
        program=encode_program_file(
            program_name,
            asmprgm_body(machine_code),
            comment=comment,
        ),
        runner=encode_program_file(
            runner_name,
            asm_call_body(program_name),
            comment=comment,
        ),
        call_address=call_address,
        return_address=return_address,
        source_rom_sha256=source_digest,
        fixture_rom_sha256=digest(rom),
        machine_code_sha256=digest(machine_code),
    )


def classify_flash_execution(
    *,
    call_visits: int,
    target_visits: int,
    target_followup_visits: int,
    return_visits: int,
    resets_after_call: int,
) -> str:
    """Classify the instruction sequence around one protected target fetch."""

    if (
        call_visits == 1
        and target_visits == 1
        and target_followup_visits == 1
        and return_visits == 1
        and resets_after_call == 0
    ):
        return "returned"
    if (
        call_visits == 1
        and target_visits == 1
        and target_followup_visits == 0
        and return_visits == 0
        and resets_after_call == 1
    ):
        return "violation-reset"
    return "indeterminate"


def analyze_flash_execution_trace(
    path: Path,
    fixture: FlashExecutionFixture,
) -> FlashExecutionTraceResult:
    """Classify a full TilEm trace as target return or protection reset."""

    call_visits = target_visits = target_followup_visits = 0
    return_visits = resets_after_call = 0
    call_clock = target_clock = target_followup_clock = None
    return_clock = reset_clock = None
    call_index = None
    for instruction in iter_resolved_instructions(
        path,
        initial_mapping="ti84p-reset",
    ):
        if instruction.logical_pc == fixture.call_address:
            call_visits += 1
            if call_clock is None:
                call_clock = instruction.clock
                call_index = instruction.instruction_index
            continue
        if (
            instruction.page == fixture.page
            and instruction.logical_pc == TARGET_ADDRESS
        ):
            target_visits += 1
            if target_clock is None:
                target_clock = instruction.clock
            continue
        if (
            instruction.page == fixture.page
            and instruction.logical_pc == TARGET_ADDRESS + 2
        ):
            target_followup_visits += 1
            if target_followup_clock is None:
                target_followup_clock = instruction.clock
            continue
        if instruction.logical_pc == fixture.return_address:
            return_visits += 1
            if return_clock is None:
                return_clock = instruction.clock
            continue
        if (
            call_index is not None
            and instruction.instruction_index > call_index
            and instruction.logical_pc == 0x8000
        ):
            resets_after_call += 1
            if reset_clock is None:
                reset_clock = instruction.clock

    classification = classify_flash_execution(
        call_visits=call_visits,
        target_visits=target_visits,
        target_followup_visits=target_followup_visits,
        return_visits=return_visits,
        resets_after_call=resets_after_call,
    )
    return FlashExecutionTraceResult(
        page=fixture.page,
        classification=classification,
        call_visits=call_visits,
        target_visits=target_visits,
        target_followup_visits=target_followup_visits,
        return_visits=return_visits,
        resets_after_call=resets_after_call,
        call_clock=call_clock,
        target_clock=target_clock,
        target_followup_clock=target_followup_clock,
        return_clock=return_clock,
        reset_clock=reset_clock,
        trace_sha256=file_digest(path),
    )


def analyze_ram_execution_trace(
    path: Path,
    fixture: TilemRamExecutionFixture,
) -> RamExecutionTraceResult:
    """Classify a full TilEm trace as RAM-target return or protection reset."""

    call_visits = target_visits = target_followup_visits = 0
    return_visits = resets_after_call = 0
    call_clock = target_clock = target_followup_clock = None
    return_clock = reset_clock = None
    call_index = None
    target_address = fixture.probe.target_address
    for instruction in iter_resolved_instructions(
        path,
        initial_mapping="ti84p-reset",
    ):
        if instruction.logical_pc == fixture.probe.call_address:
            call_visits += 1
            if call_clock is None:
                call_clock = instruction.clock
                call_index = instruction.instruction_index
            continue
        if (
            instruction.physical_page == fixture.probe.physical_page
            and instruction.logical_pc == target_address
        ):
            target_visits += 1
            if target_clock is None:
                target_clock = instruction.clock
            continue
        if (
            instruction.physical_page == fixture.probe.physical_page
            and instruction.logical_pc == target_address + 2
        ):
            target_followup_visits += 1
            if target_followup_clock is None:
                target_followup_clock = instruction.clock
            continue
        if instruction.logical_pc == fixture.probe.return_address:
            return_visits += 1
            if return_clock is None:
                return_clock = instruction.clock
            continue
        if (
            call_index is not None
            and instruction.instruction_index > call_index
            and instruction.logical_pc == 0x8000
        ):
            resets_after_call += 1
            if reset_clock is None:
                reset_clock = instruction.clock

    classification = classify_flash_execution(
        call_visits=call_visits,
        target_visits=target_visits,
        target_followup_visits=target_followup_visits,
        return_visits=return_visits,
        resets_after_call=resets_after_call,
    )
    return RamExecutionTraceResult(
        mode=fixture.mode,
        physical_page=fixture.probe.physical_page,
        page_offset=fixture.probe.page_offset,
        classification=classification,
        call_visits=call_visits,
        target_visits=target_visits,
        target_followup_visits=target_followup_visits,
        return_visits=return_visits,
        resets_after_call=resets_after_call,
        call_clock=call_clock,
        target_clock=target_clock,
        target_followup_clock=target_followup_clock,
        return_clock=return_clock,
        reset_clock=reset_clock,
        trace_sha256=file_digest(path),
    )
