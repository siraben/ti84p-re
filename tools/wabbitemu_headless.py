"""Build and run the pinned Wabbitemu core without its Windows GUI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
import re
import subprocess


WABBITEMU_COMMIT = "48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422"
WABBITEMU_ARCHIVE_URL = (
    "https://codeload.github.com/sputt/wabbitemu/tar.gz/" + WABBITEMU_COMMIT
)
WABBITEMU_ARCHIVE_SHA256 = (
    "e65e20f5b45dbf5312e92a2619e3fbc0dfe228d4464134753fdc4930b7d12ac4"
)
WABBITEMU_TREE_SHA256 = (
    "a8a4f97fc7952770bed317b4a477f80345894da38d14fad8f0bf0ee60aae71ba"
)
FLASH_SIZE = 0x100000

SOURCE_HASHES = {
    "stdafx.h": "d0f54379a6837f20576ef498474ba663726fe18ae0f82532b3e6e6f0ed4465f0",
    "core/core.c": "7e7552577b9934a8e344d0bea8152e2b46ddf6840e997e478723cfde7c170c2b",
    "core/device.c": "c4db4da57e60a752274a58974284c442f5085b34d0e8152cf04fe7ab71996d8b",
    "core/alu.c": "07913115373e5a7581c2d44051f9fe30127ae69d6bf2d515a1177206e54cd5c6",
    "core/control.c": "8f00848f99c2492fb7c345b94357ecd7b5f28313ce9f82fead2c178aff3033fc",
    "core/indexcb.c": "ab22139ff8d2f81d5fdbd8b10ea15c30f17a089b3d41fe8c32b3153563e196d9",
    "hardware/83psehw.c": "3acba050bde4df46348aac703899e2980efb24b5fec83f3f0b5940a47f8327c4",
    "hardware/83phw.c": "a0ef5de56ea1c108c62c21128697e82da17518a6c9beb21459f14bbcd965307a",
    "hardware/lcd.c": "d5740860bb8ac31d2837242d792cce5628c9756f9754db03e78c42b5f1b34dec",
    "hardware/colorlcd.c": "5ff7bddd637e9dbd35b53c2d4a65d014922ca480dd16c749b293780d20f561cc",
    "hardware/keys.c": "76bd42cddd50634495b01a4ff6d89f75f5448f0c869aa926b492aab021fd57d9",
}

COMPILE_SOURCES = tuple(path for path in SOURCE_HASHES if path.endswith(".c"))
REPORT_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")


class WabbitemuHeadlessError(ValueError):
    """A pinned-source, build, execution, or report invariant failed."""


@dataclass(frozen=True)
class WabbitemuGateWrite:
    """One native port-0x14 write and its lock-state effect."""

    page: int
    address: int
    value: int
    before_locked: bool
    after_locked: bool
    ram: bool

    def native_text(self) -> str:
        prefix = "RAM:" if self.ram else ""
        return (
            f"{prefix}{self.page:02X}:{self.address:04X}:{self.value:02X}:"
            f"{int(self.before_locked)}>{int(self.after_locked)}"
        )


@dataclass(frozen=True)
class WabbitemuGateTransition:
    """One observed change in Wabbitemu's Flash-lock state."""

    page: int
    address: int
    before_locked: bool
    after_locked: bool
    ram: bool

    def native_text(self) -> str:
        prefix = "RAM:" if self.ram else ""
        return (
            f"{prefix}{self.page:02X}:{self.address:04X}:"
            f"{int(self.before_locked)}>{int(self.after_locked)}"
        )


@dataclass(frozen=True)
class WabbitemuRunReport:
    """Stable fields emitted by the native headless runner."""

    steps: int
    tstates: int
    pc: int
    halted: bool
    changed_bytes: int
    input_fnv1a64: str
    output_fnv1a64: str
    wake: str
    settled: bool
    visits: tuple[str, ...]
    gate_writes: tuple[WabbitemuGateWrite, ...]
    gate_transitions: tuple[WabbitemuGateTransition, ...]
    unlocked_write_bcall_visits: int
    unlocked_erase_bcall_visits: int
    unlocked_program_worker_entry_visits: int
    unlocked_program_write_visits: int
    unlocked_program_success_reset_visits: int
    unlocked_program_failure_reset_visits: int
    input_sha256: str = ""
    output_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuExecutionReport:
    """Stable fields emitted by the guarded execution-probe mode."""

    page: int
    boot_steps: int
    boot_tstates: int
    boot_pc: int
    boot_page: str
    flash_locked: bool
    flash_lower: int
    flash_upper: int
    ram_lower: int
    ram_upper: int
    ram_mode: int
    injected_page: int
    injected_address: int
    probe_size: int
    call_address: int
    return_address: int
    probe_steps: int
    call_visits: int
    target_visits: int
    target_followup_visits: int
    return_visits: int
    violation_resets: int
    marker: int
    classification: str
    fixture_rom_sha256: str = ""
    machine_code_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuRamExecutionReport:
    """Stable fields emitted by the guarded RAM execution-probe mode."""

    target_page: int
    target_offset: int
    target_address: int
    target_physical: int
    boot_steps: int
    boot_tstates: int
    boot_pc: int
    boot_page: str
    boot_ram_lower: int
    boot_ram_upper: int
    boot_ram_mode: int
    configured_lower_chunk: int
    configured_upper_chunk: int
    configured_ram_lower: int
    configured_ram_upper: int
    configured_ram_mode: int
    source_page: int
    source_address: int
    probe_size: int
    call_address: int
    return_address: int
    probe_steps: int
    call_visits: int
    target_visits: int
    target_followup_visits: int
    return_visits: int
    violation_resets: int
    expected_marker: int
    marker: int
    classification: str
    source_rom_sha256: str = ""
    machine_code_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuFlashProgramReport:
    """Stable fields emitted by the native Flash byte-program probe."""

    target_page: int
    target_offset: int
    target_address: int
    target_physical: int
    original_rom_byte: int
    initial: int
    requested: int
    configured_flash_locked: bool
    initial_toggle: int
    command_writes: int
    stored: int
    step_after_write: str
    error_after_write: bool
    toggle_after_write: int
    first_read: int
    error_after_first: bool
    toggle_after_first: int
    second_read: int
    error_after_second: bool
    toggle_after_second: int
    tstates: int
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuFlashCommandReport:
    """Stable fields emitted by the native Flash command-family probe."""

    flash_size: int
    flash_version: int
    configured_flash_locked: bool
    initial_step: str
    autoselect_entry_step: str
    autoselect_maker: int
    autoselect_device: int
    autoselect_protection: int
    autoselect_reset_step: str
    autoselect_array_byte: int
    partial_step_before_reset: str
    partial_reset_step: str
    cfi_step: str
    cfi_changed_bytes: int
    suspend_window_step: str
    suspend_step: str
    suspend_changed_bytes: int
    resume_step: str
    resume_changed_bytes: int
    fast_entry_step: str
    fast_first_select_step: str
    fast_first_initial: int
    fast_first_requested: int
    fast_first_stored: int
    fast_after_first_step: str
    fast_second_select_step: str
    fast_second_initial: int
    fast_second_requested: int
    fast_second_stored: int
    fast_after_second_step: str
    fast_exit_select_step: str
    fast_exit_step: str
    sector_target_page: int
    sector_target_address: int
    sector_start: int
    sector_size: int
    sector_step: str
    sector_erased_bytes: int
    sector_changed_bytes: int
    sector_outside_changed_bytes: int
    chip_step: str
    chip_non_ff_before: int
    chip_non_ff_after: int
    chip_changed_bytes: int
    chip_boot_before: int
    chip_boot_after: int
    tstates: int
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuFlashWorkerReport:
    """Stable fields emitted by the retail-ROM Flash worker probe."""

    target_page: int
    target_offset: int
    target_address: int
    target_physical: int
    original_rom_byte: int
    initial: int
    requested: int
    initial_toggle: int
    boot_steps: int
    boot_tstates: int
    boot_pc: int
    boot_page: str
    boot_flash_locked: bool
    boot_flash_lower: int
    boot_flash_upper: int
    configured_flash_locked: bool
    source_page: int
    source_address: int
    harness_size: int
    return_address: int
    max_probe_steps: int
    probe_steps: int
    probe_tstates: int
    bcall_visits: int
    worker_entry_visits: int
    program_write_visits: int
    dq7_read_visits: int
    final_dq7_read_visits: int
    success_reset_visits: int
    failure_reset_visits: int
    return_visits: int
    violation_resets: int
    poll_reads: tuple[int, ...]
    stored: int
    flash_step: str
    flash_error: bool
    flash_toggle: int
    return_af: int
    return_bc: int
    return_de: int
    return_hl: int
    port06: int
    bank1_page: str
    final_pc: int
    classification: str
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def file_sha256(path: Path) -> str:
    """Return a streaming SHA-256 digest for *path*."""

    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_tree_sha256(source: Path) -> str:
    """Hash paths and contents in a checkout, excluding Git administration."""

    digest = sha256()
    paths = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(source).parts
    )
    for path in paths:
        relative = path.relative_to(source).as_posix().encode()
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def validate_pinned_source(source: Path) -> dict[str, str]:
    """Verify every Wabbitemu translation unit used by the runner."""

    try:
        tree_digest = source_tree_sha256(source)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot hash Wabbitemu source tree: {error}") from error
    if tree_digest != WABBITEMU_TREE_SHA256:
        raise WabbitemuHeadlessError(
            f"source tree SHA-256 is {tree_digest}; expected {WABBITEMU_TREE_SHA256}"
        )
    actual = {}
    for relative, expected in SOURCE_HASHES.items():
        path = source / relative
        try:
            digest = file_sha256(path)
        except OSError as error:
            raise WabbitemuHeadlessError(f"cannot read pinned source {path}: {error}") from error
        if digest != expected:
            raise WabbitemuHeadlessError(
                f"{relative} SHA-256 is {digest}; expected {expected}"
            )
        actual[relative] = digest
    return actual


def build_command(
    source: Path,
    harness: Path,
    output: Path,
    *,
    cxx: str = "g++",
) -> list[str]:
    """Return the exact Linux compilation command for the pinned core."""

    includes = (source, source / "core", source / "hardware", source / "utilities")
    return [
        cxx,
        "-std=gnu++11",
        "-O2",
        "-D_LINUX",
        "-D__pragma(x)=",
        *(f"-I{path}" for path in includes),
        str(harness),
        *(str(source / relative) for relative in COMPILE_SOURCES),
        "-lm",
        "-o",
        str(output),
    ]


def build_headless(
    source: Path,
    harness: Path,
    output: Path,
    *,
    cxx: str = "g++",
) -> list[str]:
    """Validate the pinned sources and compile the native runner."""

    validate_pinned_source(source)
    command = build_command(source, harness, output, cxx=cxx)
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise WabbitemuHeadlessError(f"Wabbitemu headless build failed: {error}") from error
    return command


def _parse_gate_event(
    value: str,
    *,
    includes_value: bool,
) -> tuple[int, int, int | None, bool, bool, bool]:
    """Parse the native physical-PC and lock-state event notation."""

    parts = value.split(":")
    ram = parts[0] == "RAM"
    if ram:
        parts = parts[1:]
    expected_parts = 4 if includes_value else 3
    if len(parts) != expected_parts:
        raise WabbitemuHeadlessError(f"invalid native gate event {value!r}")
    try:
        page = int(parts[0], 16)
        address = int(parts[1], 16)
        event_value = int(parts[2], 16) if includes_value else None
        transition = parts[3] if includes_value else parts[2]
        before_text, after_text = transition.split(">", 1)
        if before_text not in {"0", "1"} or after_text not in {"0", "1"}:
            raise ValueError
        if not 0 <= page <= 0xFF or not 0 <= address <= 0xFFFF:
            raise ValueError
        if event_value is not None and not 0 <= event_value <= 0xFF:
            raise ValueError
    except ValueError as error:
        raise WabbitemuHeadlessError(
            f"invalid native gate event {value!r}"
        ) from error
    return (
        page,
        address,
        event_value,
        before_text == "1",
        after_text == "1",
        ram,
    )


def parse_gate_write(value: str) -> WabbitemuGateWrite:
    """Parse one native port-0x14 write report field."""

    page, address, event_value, before, after, ram = _parse_gate_event(
        value,
        includes_value=True,
    )
    assert event_value is not None
    return WabbitemuGateWrite(page, address, event_value, before, after, ram)


def parse_gate_transition(value: str) -> WabbitemuGateTransition:
    """Parse one native Flash-lock transition report field."""

    page, address, _, before, after, ram = _parse_gate_event(
        value,
        includes_value=False,
    )
    return WabbitemuGateTransition(page, address, before, after, ram)


def validate_retail_flash_path(report: WabbitemuRunReport) -> None:
    """Require a locked-to-unlocked retail write path with successful workers."""

    unlocks = tuple(
        write
        for write in report.gate_writes
        if write.value & 1 and write.before_locked and not write.after_locked
    )
    relocks = tuple(
        write
        for write in report.gate_writes
        if not (write.value & 1) and not write.before_locked and write.after_locked
    )
    if not unlocks or not relocks:
        raise WabbitemuHeadlessError(
            "native run does not contain accepted port-0x14 unlock and relock writes"
        )
    entries = report.unlocked_program_worker_entry_visits
    if report.unlocked_write_bcall_visits <= 0 or entries <= 0:
        raise WabbitemuHeadlessError(
            "native run does not reach the retail write bcall and copied worker"
        )
    if report.unlocked_write_bcall_visits != entries:
        raise WabbitemuHeadlessError(
            "retail write-bcall and copied-worker entry counts disagree"
        )
    if report.unlocked_program_write_visits < entries:
        raise WabbitemuHeadlessError(
            "copied workers do not issue at least one byte-program write each"
        )
    if report.unlocked_program_success_reset_visits != entries:
        raise WabbitemuHeadlessError(
            "copied-worker success tails do not match copied-worker entries"
        )
    if report.unlocked_program_failure_reset_visits != 0:
        raise WabbitemuHeadlessError(
            "native run reaches a copied-worker failure tail"
        )


def parse_run_report(line: str) -> WabbitemuRunReport:
    """Parse one native runner status line, rejecting missing fields."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    required = {
        "steps",
        "tstates",
        "pc",
        "halted",
        "changed_bytes",
        "input_fnv1a64",
        "output_fnv1a64",
        "wake",
        "settled",
        "visits",
        "gate_writes",
        "gate_transitions",
        "unlocked_write_bcall_visits",
        "unlocked_erase_bcall_visits",
        "unlocked_program_worker_entry_visits",
        "unlocked_program_write_visits",
        "unlocked_program_success_reset_visits",
        "unlocked_program_failure_reset_visits",
    }
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native runner report omits " + ", ".join(missing)
        )
    try:
        return WabbitemuRunReport(
            steps=int(fields["steps"], 0),
            tstates=int(fields["tstates"], 0),
            pc=int(fields["pc"], 0),
            halted=bool(int(fields["halted"], 0)),
            changed_bytes=int(fields["changed_bytes"], 0),
            input_fnv1a64=fields["input_fnv1a64"],
            output_fnv1a64=fields["output_fnv1a64"],
            wake=fields["wake"],
            settled=fields["settled"] == "yes",
            visits=(
                ()
                if fields["visits"] == "-"
                else tuple(filter(None, fields["visits"].split(",")))
            ),
            gate_writes=(
                ()
                if fields["gate_writes"] == "-"
                else tuple(
                    parse_gate_write(value)
                    for value in fields["gate_writes"].split(",")
                    if value
                )
            ),
            gate_transitions=(
                ()
                if fields["gate_transitions"] == "-"
                else tuple(
                    parse_gate_transition(value)
                    for value in fields["gate_transitions"].split(",")
                    if value
                )
            ),
            unlocked_write_bcall_visits=int(
                fields["unlocked_write_bcall_visits"], 0
            ),
            unlocked_erase_bcall_visits=int(
                fields["unlocked_erase_bcall_visits"], 0
            ),
            unlocked_program_worker_entry_visits=int(
                fields["unlocked_program_worker_entry_visits"], 0
            ),
            unlocked_program_write_visits=int(
                fields["unlocked_program_write_visits"], 0
            ),
            unlocked_program_success_reset_visits=int(
                fields["unlocked_program_success_reset_visits"], 0
            ),
            unlocked_program_failure_reset_visits=int(
                fields["unlocked_program_failure_reset_visits"], 0
            ),
        )
    except ValueError as error:
        raise WabbitemuHeadlessError(f"invalid native runner report: {line.strip()}") from error


def parse_execution_report(line: str) -> WabbitemuExecutionReport:
    """Parse one guarded native execution report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    required = {
        "mode",
        "page",
        "boot_steps",
        "boot_tstates",
        "boot_pc",
        "boot_page",
        "flash_locked",
        "flash_lower",
        "flash_upper",
        "ram_lower",
        "ram_upper",
        "ram_mode",
        "injected_page",
        "injected_address",
        "probe_size",
        "call_address",
        "return_address",
        "probe_steps",
        "call_visits",
        "target_visits",
        "target_followup_visits",
        "return_visits",
        "violation_resets",
        "marker",
        "classification",
    }
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native execution report omits " + ", ".join(missing)
        )
    if fields["mode"] != "execution-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native execution mode {fields['mode']!r}"
        )
    try:
        flash_locked = int(fields["flash_locked"], 0)
        if flash_locked not in (0, 1):
            raise ValueError("flash_locked must be zero or one")
        if fields["classification"] not in {
            "returned",
            "violation-reset",
            "indeterminate",
        }:
            raise ValueError("unknown execution classification")
        return WabbitemuExecutionReport(
            page=int(fields["page"], 0),
            boot_steps=int(fields["boot_steps"], 0),
            boot_tstates=int(fields["boot_tstates"], 0),
            boot_pc=int(fields["boot_pc"], 0),
            boot_page=fields["boot_page"],
            flash_locked=bool(flash_locked),
            flash_lower=int(fields["flash_lower"], 0),
            flash_upper=int(fields["flash_upper"], 0),
            ram_lower=int(fields["ram_lower"], 0),
            ram_upper=int(fields["ram_upper"], 0),
            ram_mode=int(fields["ram_mode"], 0),
            injected_page=int(fields["injected_page"], 0),
            injected_address=int(fields["injected_address"], 0),
            probe_size=int(fields["probe_size"], 0),
            call_address=int(fields["call_address"], 0),
            return_address=int(fields["return_address"], 0),
            probe_steps=int(fields["probe_steps"], 0),
            call_visits=int(fields["call_visits"], 0),
            target_visits=int(fields["target_visits"], 0),
            target_followup_visits=int(fields["target_followup_visits"], 0),
            return_visits=int(fields["return_visits"], 0),
            violation_resets=int(fields["violation_resets"], 0),
            marker=int(fields["marker"], 0),
            classification=fields["classification"],
        )
    except ValueError as error:
        raise WabbitemuHeadlessError(
            f"invalid native execution report: {line.strip()}"
        ) from error


def parse_flash_program_report(line: str) -> WabbitemuFlashProgramReport:
    """Parse one native Flash byte-program report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    required = {
        "mode",
        "target_page",
        "target_offset",
        "target_address",
        "target_physical",
        "original_rom_byte",
        "initial",
        "requested",
        "configured_flash_locked",
        "initial_toggle",
        "command_writes",
        "stored",
        "step_after_write",
        "error_after_write",
        "toggle_after_write",
        "first_read",
        "error_after_first",
        "toggle_after_first",
        "second_read",
        "error_after_second",
        "toggle_after_second",
        "tstates",
    }
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native Flash program report omits " + ", ".join(missing)
        )
    if fields["mode"] != "flash-program-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native Flash program mode {fields['mode']!r}"
        )
    try:
        booleans = {
            name: int(fields[name], 0)
            for name in (
                "configured_flash_locked",
                "error_after_write",
                "error_after_first",
                "error_after_second",
            )
        }
        if any(value not in (0, 1) for value in booleans.values()):
            raise ValueError("Flash program booleans must be zero or one")
        return WabbitemuFlashProgramReport(
            target_page=int(fields["target_page"], 0),
            target_offset=int(fields["target_offset"], 0),
            target_address=int(fields["target_address"], 0),
            target_physical=int(fields["target_physical"], 0),
            original_rom_byte=int(fields["original_rom_byte"], 0),
            initial=int(fields["initial"], 0),
            requested=int(fields["requested"], 0),
            configured_flash_locked=bool(booleans["configured_flash_locked"]),
            initial_toggle=int(fields["initial_toggle"], 0),
            command_writes=int(fields["command_writes"], 0),
            stored=int(fields["stored"], 0),
            step_after_write=fields["step_after_write"],
            error_after_write=bool(booleans["error_after_write"]),
            toggle_after_write=int(fields["toggle_after_write"], 0),
            first_read=int(fields["first_read"], 0),
            error_after_first=bool(booleans["error_after_first"]),
            toggle_after_first=int(fields["toggle_after_first"], 0),
            second_read=int(fields["second_read"], 0),
            error_after_second=bool(booleans["error_after_second"]),
            toggle_after_second=int(fields["toggle_after_second"], 0),
            tstates=int(fields["tstates"], 0),
        )
    except ValueError as error:
        raise WabbitemuHeadlessError(
            f"invalid native Flash program report: {line.strip()}"
        ) from error


def parse_flash_command_report(line: str) -> WabbitemuFlashCommandReport:
    """Parse one native Flash command-family report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    numeric = {
        "flash_size",
        "flash_version",
        "autoselect_maker",
        "autoselect_device",
        "autoselect_protection",
        "autoselect_array_byte",
        "cfi_changed_bytes",
        "suspend_changed_bytes",
        "resume_changed_bytes",
        "fast_first_initial",
        "fast_first_requested",
        "fast_first_stored",
        "fast_second_initial",
        "fast_second_requested",
        "fast_second_stored",
        "sector_target_page",
        "sector_target_address",
        "sector_start",
        "sector_size",
        "sector_erased_bytes",
        "sector_changed_bytes",
        "sector_outside_changed_bytes",
        "chip_non_ff_before",
        "chip_non_ff_after",
        "chip_changed_bytes",
        "chip_boot_before",
        "chip_boot_after",
        "tstates",
    }
    steps = {
        "initial_step",
        "autoselect_entry_step",
        "autoselect_reset_step",
        "partial_step_before_reset",
        "partial_reset_step",
        "cfi_step",
        "suspend_window_step",
        "suspend_step",
        "resume_step",
        "fast_entry_step",
        "fast_first_select_step",
        "fast_after_first_step",
        "fast_second_select_step",
        "fast_after_second_step",
        "fast_exit_select_step",
        "fast_exit_step",
        "sector_step",
        "chip_step",
    }
    required = {"mode", "configured_flash_locked", *numeric, *steps}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native Flash command report omits " + ", ".join(missing)
        )
    if fields["mode"] != "flash-command-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native Flash command mode {fields['mode']!r}"
        )
    try:
        configured_flash_locked = int(fields["configured_flash_locked"], 0)
        if configured_flash_locked not in (0, 1):
            raise ValueError("Flash command boolean must be zero or one")
        values: dict[str, object] = {
            name: int(fields[name], 0) for name in numeric
        }
        values.update({name: fields[name] for name in steps})
        return WabbitemuFlashCommandReport(
            configured_flash_locked=bool(configured_flash_locked),
            **values,
        )
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native Flash command report: {line.strip()}"
        ) from error


def parse_flash_worker_report(line: str) -> WabbitemuFlashWorkerReport:
    """Parse one retail-ROM Flash worker report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    required = {
        "mode",
        "target_page",
        "target_offset",
        "target_address",
        "target_physical",
        "original_rom_byte",
        "initial",
        "requested",
        "initial_toggle",
        "boot_steps",
        "boot_tstates",
        "boot_pc",
        "boot_page",
        "boot_flash_locked",
        "boot_flash_lower",
        "boot_flash_upper",
        "configured_flash_locked",
        "source_page",
        "source_address",
        "harness_size",
        "return_address",
        "max_probe_steps",
        "probe_steps",
        "probe_tstates",
        "bcall_visits",
        "worker_entry_visits",
        "program_write_visits",
        "dq7_read_visits",
        "final_dq7_read_visits",
        "success_reset_visits",
        "failure_reset_visits",
        "return_visits",
        "violation_resets",
        "poll_reads",
        "stored",
        "flash_step",
        "flash_error",
        "flash_toggle",
        "return_af",
        "return_bc",
        "return_de",
        "return_hl",
        "port06",
        "bank1_page",
        "final_pc",
        "classification",
    }
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native Flash worker report omits " + ", ".join(missing)
        )
    if fields["mode"] != "flash-worker-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native Flash worker mode {fields['mode']!r}"
        )
    if fields["classification"] not in {
        "success",
        "failure",
        "step-limit",
        "indeterminate",
    }:
        raise WabbitemuHeadlessError(
            f"unknown native Flash worker classification "
            f"{fields['classification']!r}"
        )
    try:
        booleans = {
            name: int(fields[name], 0)
            for name in (
                "boot_flash_locked",
                "configured_flash_locked",
                "flash_error",
            )
        }
        if any(value not in (0, 1) for value in booleans.values()):
            raise ValueError("Flash worker booleans must be zero or one")
        poll_reads = (
            ()
            if fields["poll_reads"] == "-"
            else tuple(int(value, 16) for value in fields["poll_reads"].split(","))
        )
        return WabbitemuFlashWorkerReport(
            target_page=int(fields["target_page"], 0),
            target_offset=int(fields["target_offset"], 0),
            target_address=int(fields["target_address"], 0),
            target_physical=int(fields["target_physical"], 0),
            original_rom_byte=int(fields["original_rom_byte"], 0),
            initial=int(fields["initial"], 0),
            requested=int(fields["requested"], 0),
            initial_toggle=int(fields["initial_toggle"], 0),
            boot_steps=int(fields["boot_steps"], 0),
            boot_tstates=int(fields["boot_tstates"], 0),
            boot_pc=int(fields["boot_pc"], 0),
            boot_page=fields["boot_page"],
            boot_flash_locked=bool(booleans["boot_flash_locked"]),
            boot_flash_lower=int(fields["boot_flash_lower"], 0),
            boot_flash_upper=int(fields["boot_flash_upper"], 0),
            configured_flash_locked=bool(booleans["configured_flash_locked"]),
            source_page=int(fields["source_page"], 0),
            source_address=int(fields["source_address"], 0),
            harness_size=int(fields["harness_size"], 0),
            return_address=int(fields["return_address"], 0),
            max_probe_steps=int(fields["max_probe_steps"], 0),
            probe_steps=int(fields["probe_steps"], 0),
            probe_tstates=int(fields["probe_tstates"], 0),
            bcall_visits=int(fields["bcall_visits"], 0),
            worker_entry_visits=int(fields["worker_entry_visits"], 0),
            program_write_visits=int(fields["program_write_visits"], 0),
            dq7_read_visits=int(fields["dq7_read_visits"], 0),
            final_dq7_read_visits=int(fields["final_dq7_read_visits"], 0),
            success_reset_visits=int(fields["success_reset_visits"], 0),
            failure_reset_visits=int(fields["failure_reset_visits"], 0),
            return_visits=int(fields["return_visits"], 0),
            violation_resets=int(fields["violation_resets"], 0),
            poll_reads=poll_reads,
            stored=int(fields["stored"], 0),
            flash_step=fields["flash_step"],
            flash_error=bool(booleans["flash_error"]),
            flash_toggle=int(fields["flash_toggle"], 0),
            return_af=int(fields["return_af"], 0),
            return_bc=int(fields["return_bc"], 0),
            return_de=int(fields["return_de"], 0),
            return_hl=int(fields["return_hl"], 0),
            port06=int(fields["port06"], 0),
            bank1_page=fields["bank1_page"],
            final_pc=int(fields["final_pc"], 0),
            classification=fields["classification"],
        )
    except ValueError as error:
        raise WabbitemuHeadlessError(
            f"invalid native Flash worker report: {line.strip()}"
        ) from error


def parse_ram_execution_report(line: str) -> WabbitemuRamExecutionReport:
    """Parse one guarded native RAM execution report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    required = {
        "mode",
        "target_page",
        "target_offset",
        "target_address",
        "target_physical",
        "boot_steps",
        "boot_tstates",
        "boot_pc",
        "boot_page",
        "boot_ram_lower",
        "boot_ram_upper",
        "boot_ram_mode",
        "configured_lower_chunk",
        "configured_upper_chunk",
        "configured_ram_lower",
        "configured_ram_upper",
        "configured_ram_mode",
        "source_page",
        "source_address",
        "probe_size",
        "call_address",
        "return_address",
        "probe_steps",
        "call_visits",
        "target_visits",
        "target_followup_visits",
        "return_visits",
        "violation_resets",
        "expected_marker",
        "marker",
        "classification",
    }
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native RAM execution report omits " + ", ".join(missing)
        )
    if fields["mode"] != "ram-execution-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native RAM execution mode {fields['mode']!r}"
        )
    if fields["classification"] not in {
        "returned",
        "violation-reset",
        "indeterminate",
    }:
        raise WabbitemuHeadlessError(
            f"unknown native RAM execution classification "
            f"{fields['classification']!r}"
        )
    try:
        return WabbitemuRamExecutionReport(
            target_page=int(fields["target_page"], 0),
            target_offset=int(fields["target_offset"], 0),
            target_address=int(fields["target_address"], 0),
            target_physical=int(fields["target_physical"], 0),
            boot_steps=int(fields["boot_steps"], 0),
            boot_tstates=int(fields["boot_tstates"], 0),
            boot_pc=int(fields["boot_pc"], 0),
            boot_page=fields["boot_page"],
            boot_ram_lower=int(fields["boot_ram_lower"], 0),
            boot_ram_upper=int(fields["boot_ram_upper"], 0),
            boot_ram_mode=int(fields["boot_ram_mode"], 0),
            configured_lower_chunk=int(fields["configured_lower_chunk"], 0),
            configured_upper_chunk=int(fields["configured_upper_chunk"], 0),
            configured_ram_lower=int(fields["configured_ram_lower"], 0),
            configured_ram_upper=int(fields["configured_ram_upper"], 0),
            configured_ram_mode=int(fields["configured_ram_mode"], 0),
            source_page=int(fields["source_page"], 0),
            source_address=int(fields["source_address"], 0),
            probe_size=int(fields["probe_size"], 0),
            call_address=int(fields["call_address"], 0),
            return_address=int(fields["return_address"], 0),
            probe_steps=int(fields["probe_steps"], 0),
            call_visits=int(fields["call_visits"], 0),
            target_visits=int(fields["target_visits"], 0),
            target_followup_visits=int(fields["target_followup_visits"], 0),
            return_visits=int(fields["return_visits"], 0),
            violation_resets=int(fields["violation_resets"], 0),
            expected_marker=int(fields["expected_marker"], 0),
            marker=int(fields["marker"], 0),
            classification=fields["classification"],
        )
    except ValueError as error:
        raise WabbitemuHeadlessError(
            f"invalid native RAM execution report: {line.strip()}"
        ) from error


def run_flash_program_probe(
    binary: Path,
    source_rom: Path,
    initial: int,
    requested: int,
    *,
    initial_toggle: int = 0,
) -> WabbitemuFlashProgramReport:
    """Run one byte-program case through the pinned native core."""

    for value, name in ((initial, "initial"), (requested, "requested")):
        if not 0 <= value <= 0xFF:
            raise WabbitemuHeadlessError(f"{name} Flash byte must be between 0 and 255")
    if initial_toggle not in (0, 0x40):
        raise WabbitemuHeadlessError("initial Flash toggle must be 0 or 0x40")
    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot inspect Flash program fixture: {error}") from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [
        str(binary),
        "--flash-program-probe",
        str(source_rom),
        str(initial),
        str(requested),
        str(initial_toggle),
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native Flash program probe failed: {detail}")
    report = parse_flash_program_report(completed.stdout)
    if (report.initial, report.requested, report.initial_toggle) != (
        initial,
        requested,
        initial_toggle,
    ):
        raise WabbitemuHeadlessError(
            "native Flash program report disagrees with the requested case"
        )
    return WabbitemuFlashProgramReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_flash_command_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuFlashCommandReport:
    """Run the guarded command-family matrix through the pinned native core."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect Flash command fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--flash-command-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native Flash command probe failed: {detail}")
    report = parse_flash_command_report(completed.stdout)
    return WabbitemuFlashCommandReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_flash_worker_probe(
    binary: Path,
    source_rom: Path,
    initial: int,
    requested: int,
    *,
    initial_toggle: int = 0,
    max_boot_steps: int = 5_000_000,
    max_probe_steps: int = 10_000,
) -> WabbitemuFlashWorkerReport:
    """Run one byte through the retail-ROM block worker under Wabbitemu."""

    for value, name in ((initial, "initial"), (requested, "requested")):
        if not 0 <= value <= 0xFF:
            raise WabbitemuHeadlessError(f"{name} Flash byte must be between 0 and 255")
    if initial_toggle not in (0, 0x40):
        raise WabbitemuHeadlessError("initial Flash toggle must be 0 or 0x40")
    if max_boot_steps <= 0 or max_probe_steps <= 0:
        raise WabbitemuHeadlessError("Flash worker step bounds must be positive")
    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot inspect Flash worker ROM: {error}") from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [
        str(binary),
        "--flash-worker-probe",
        str(source_rom),
        str(initial),
        str(requested),
        str(initial_toggle),
        str(max_boot_steps),
        str(max_probe_steps),
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native Flash worker probe failed: {detail}")
    report = parse_flash_worker_report(completed.stdout)
    if (
        report.initial,
        report.requested,
        report.initial_toggle,
        report.max_probe_steps,
    ) != (initial, requested, initial_toggle, max_probe_steps):
        raise WabbitemuHeadlessError(
            "native Flash worker report disagrees with the requested case"
        )
    return WabbitemuFlashWorkerReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_ram_execution_probe(
    binary: Path,
    source_rom: Path,
    machine_code: Path,
    physical_page: int,
    page_offset: int,
    ram_mode: int,
    lower_chunk: int,
    upper_chunk: int,
    *,
    max_boot_steps: int = 5_000_000,
    max_probe_steps: int = 1_000,
) -> WabbitemuRamExecutionReport:
    """Run one guarded RAM target through the pinned native core."""

    if not 0 <= physical_page < 8:
        raise WabbitemuHeadlessError("physical RAM page must be between 0 and 7")
    if not 0 <= page_offset <= 0x4000 - 6:
        raise WabbitemuHeadlessError(
            "RAM target offset must leave room for the marker routine"
        )
    if not 0 <= ram_mode <= 3:
        raise WabbitemuHeadlessError("RAM execution mode must be between 0 and 3")
    if not 0 <= lower_chunk <= 0xFF or not 0 <= upper_chunk <= 0xFF:
        raise WabbitemuHeadlessError("RAM chunk bounds must be bytes")
    try:
        rom_size = source_rom.stat().st_size
        probe_size = machine_code.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot inspect RAM execution fixture: {error}") from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    if probe_size <= 0:
        raise WabbitemuHeadlessError("RAM probe machine code is empty")
    if max_boot_steps <= 0 or max_probe_steps <= 0:
        raise WabbitemuHeadlessError("RAM execution-probe step bounds must be positive")

    command = [
        str(binary),
        "--ram-execution-probe",
        str(source_rom),
        str(machine_code),
        str(physical_page),
        str(page_offset),
        str(ram_mode),
        str(lower_chunk),
        str(upper_chunk),
        str(max_boot_steps),
        str(max_probe_steps),
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode not in (0, 3):
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native RAM execution probe failed: {detail}")
    report = parse_ram_execution_report(completed.stdout)
    expected_identity = (
        physical_page,
        page_offset,
        ram_mode,
        lower_chunk,
        upper_chunk,
        probe_size,
    )
    observed_identity = (
        report.target_page,
        report.target_offset,
        report.configured_ram_mode,
        report.configured_lower_chunk,
        report.configured_upper_chunk,
        report.probe_size,
    )
    if observed_identity != expected_identity:
        raise WabbitemuHeadlessError(
            "native RAM execution report disagrees with the requested fixture"
        )
    return WabbitemuRamExecutionReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "machine_code_sha256": file_sha256(machine_code),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_execution_probe(
    binary: Path,
    fixture_rom: Path,
    machine_code: Path,
    page: int,
    *,
    max_boot_steps: int = 5_000_000,
    max_probe_steps: int = 1_000,
) -> WabbitemuExecutionReport:
    """Run one guarded Flash boundary probe through the pinned native core."""

    if not 0 <= page < 64:
        raise WabbitemuHeadlessError("Flash page must be between 0x00 and 0x3F")
    try:
        rom_size = fixture_rom.stat().st_size
        probe_size = machine_code.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot inspect execution fixture: {error}") from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"fixture ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    if probe_size <= 0:
        raise WabbitemuHeadlessError("probe machine code is empty")
    if max_boot_steps <= 0 or max_probe_steps <= 0:
        raise WabbitemuHeadlessError("execution-probe step bounds must be positive")

    command = [
        str(binary),
        "--execution-probe",
        str(fixture_rom),
        str(machine_code),
        str(page),
        str(max_boot_steps),
        str(max_probe_steps),
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode not in (0, 3):
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native execution probe failed: {detail}")
    report = parse_execution_report(completed.stdout)
    if report.page != page:
        raise WabbitemuHeadlessError(
            f"native execution report page is 0x{report.page:02X}; expected 0x{page:02X}"
        )
    if report.probe_size != probe_size:
        raise WabbitemuHeadlessError(
            f"native execution report probe size is {report.probe_size}; "
            f"expected {probe_size}"
        )
    return WabbitemuExecutionReport(
        **{
            **report.to_dict(),
            "fixture_rom_sha256": file_sha256(fixture_rom),
            "machine_code_sha256": file_sha256(machine_code),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_headless(
    binary: Path,
    input_image: Path,
    output_image: Path,
    *,
    max_steps: int = 200_000_000,
    min_steps: int = 20_000_000,
    sample_interval: int = 1_000_000,
    settle_samples: int = 10,
) -> WabbitemuRunReport:
    """Cold-boot one image, wake it, and return a hash-complete run report."""

    try:
        input_size = input_image.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot inspect input image: {error}") from error
    if input_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"input image must contain 0x{FLASH_SIZE:X} bytes, got 0x{input_size:X}"
        )
    command = [
        str(binary),
        str(input_image),
        str(output_image),
        str(max_steps),
        str(min_steps),
        str(sample_interval),
        str(settle_samples),
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode not in (0, 3):
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native runner failed: {detail}")
    report = parse_run_report(completed.stdout)
    try:
        output_size = output_image.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(f"native runner produced no output image: {error}") from error
    if output_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"output image must contain 0x{FLASH_SIZE:X} bytes, got 0x{output_size:X}"
        )
    return replace(
        report,
        input_sha256=file_sha256(input_image),
        output_sha256=file_sha256(output_image),
    )
