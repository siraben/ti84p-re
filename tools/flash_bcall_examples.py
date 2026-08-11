"""Assembly, parsing, and oracle support for Flash bcall usage examples."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from wabbitemu_headless import WabbitemuHeadlessError, file_sha256

REPORT_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")


@dataclass(frozen=True)
class FlashBcallUsageReport:
    """Complete native report for the executable documentation examples."""

    probe_size: int
    boot_steps: int
    boot_tstates: int
    max_probe_steps: int
    probe_steps: int
    probe_tstates: int
    writeflash_visits: int
    writeflashunsafe_visits: int
    writeabytesafe_visits: int
    writeabyte_visits: int
    erasepage_visits: int
    eraseflash_visits: int
    erasecertificate_visits: int
    setbound_visits: int
    flashtoram_visits: int
    worker_entry_visits: int
    violation_resets: int
    completed: bool
    writeflash_af: int
    writeflashunsafe_af: int
    writeabytesafe_af: int
    writeabyte_af: int
    erasepage_af: int
    eraseflash_af: int
    erasecertificate_af: int
    bound_iff_af: int
    writeflash_stored: tuple[int, int]
    writeflash_copy: tuple[int, int]
    writeflashunsafe_stored: tuple[int, int]
    writeflashunsafe_copy: tuple[int, int]
    writeabytesafe_stored: int
    writeabytesafe_copy: int
    writeabyte_stored: int
    writeabyte_copy: int
    erasepage_stored: int
    erasepage_copy: int
    eraseflash_stored: int
    eraseflash_copy: int
    erasecertificate_stored: int
    erasecertificate_copy: int
    op1: int
    context_bit1: bool
    flash_upper: int
    flash_locked: bool
    final_pc: int
    source_rom_sha256: str = ""
    machine_code_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def assemble_flash_bcall_probe(
    source: Path,
    output: Path,
    *,
    spasm: str = "spasm",
) -> list[str]:
    """Assemble the executable Flash bcall examples as a raw RAM program."""

    command = [spasm, "-N", str(source), str(output)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute SPASM: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise WabbitemuHeadlessError(f"SPASM failed: {detail}")
    if not output.is_file() or output.stat().st_size == 0:
        raise WabbitemuHeadlessError("SPASM did not produce a nonempty probe")
    return command


def _integer(fields: dict[str, str], name: str) -> int:
    try:
        return int(fields[name], 0)
    except (KeyError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid Flash bcall usage field {name}"
        ) from error


def _boolean(fields: dict[str, str], name: str) -> bool:
    value = _integer(fields, name)
    if value not in (0, 1):
        raise WabbitemuHeadlessError(
            f"Flash bcall usage field {name} must be zero or one"
        )
    return bool(value)


def _pair(fields: dict[str, str], name: str) -> tuple[int, int]:
    try:
        values = tuple(int(value, 16) for value in fields[name].split(","))
    except (KeyError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid Flash bcall usage field {name}"
        ) from error
    if len(values) != 2 or any(not 0 <= value <= 0xFF for value in values):
        raise WabbitemuHeadlessError(
            f"Flash bcall usage field {name} must contain two bytes"
        )
    return values[0], values[1]


def parse_flash_bcall_usage_report(line: str) -> FlashBcallUsageReport:
    """Parse the native one-line Flash bcall example report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    if fields.get("mode") != "flash-bcall-usage-probe":
        raise WabbitemuHeadlessError("native Flash bcall usage mode is invalid")
    integer_fields = (
        "probe_size",
        "boot_steps",
        "boot_tstates",
        "max_probe_steps",
        "probe_steps",
        "probe_tstates",
        "writeflash_visits",
        "writeflashunsafe_visits",
        "writeabytesafe_visits",
        "writeabyte_visits",
        "erasepage_visits",
        "eraseflash_visits",
        "erasecertificate_visits",
        "setbound_visits",
        "flashtoram_visits",
        "worker_entry_visits",
        "violation_resets",
        "writeflash_af",
        "writeflashunsafe_af",
        "writeabytesafe_af",
        "writeabyte_af",
        "erasepage_af",
        "eraseflash_af",
        "erasecertificate_af",
        "bound_iff_af",
        "writeabytesafe_stored",
        "writeabytesafe_copy",
        "writeabyte_stored",
        "writeabyte_copy",
        "erasepage_stored",
        "erasepage_copy",
        "eraseflash_stored",
        "eraseflash_copy",
        "erasecertificate_stored",
        "erasecertificate_copy",
        "op1",
        "flash_upper",
        "final_pc",
    )
    values = {name: _integer(fields, name) for name in integer_fields}
    values.update(
        {
            "completed": _boolean(fields, "completed"),
            "context_bit1": _boolean(fields, "context_bit1"),
            "flash_locked": _boolean(fields, "flash_locked"),
            "writeflash_stored": _pair(fields, "writeflash_stored"),
            "writeflash_copy": _pair(fields, "writeflash_copy"),
            "writeflashunsafe_stored": _pair(fields, "writeflashunsafe_stored"),
            "writeflashunsafe_copy": _pair(fields, "writeflashunsafe_copy"),
        }
    )
    try:
        return FlashBcallUsageReport(**values)
    except TypeError as error:
        raise WabbitemuHeadlessError(
            f"invalid native Flash bcall usage report: {line.strip()}"
        ) from error


def validate_flash_bcall_usage_report(
    report: FlashBcallUsageReport,
) -> dict[str, object]:
    """Require the bcall, worker, result, scratch, and readback contract."""

    observed = report.to_dict()
    expected: dict[str, object] = {
        "writeflash_visits": 1,
        "writeflashunsafe_visits": 4,
        "writeabytesafe_visits": 1,
        "writeabyte_visits": 2,
        "erasepage_visits": 1,
        "eraseflash_visits": 3,
        "erasecertificate_visits": 1,
        "setbound_visits": 1,
        "flashtoram_visits": 7,
        "worker_entry_visits": 14,
        "violation_resets": 0,
        "completed": True,
        "writeflash_stored": (0xA5, 0x5A),
        "writeflash_copy": (0xA5, 0x5A),
        "writeflashunsafe_stored": (0x3C, 0xC3),
        "writeflashunsafe_copy": (0x3C, 0xC3),
        "writeabytesafe_stored": 0xFC,
        "writeabytesafe_copy": 0xFC,
        "writeabyte_stored": 0xF8,
        "writeabyte_copy": 0xF8,
        "erasepage_stored": 0xFF,
        "erasepage_copy": 0xFF,
        "eraseflash_stored": 0xFF,
        "eraseflash_copy": 0xFF,
        "erasecertificate_stored": 0xFF,
        "erasecertificate_copy": 0xFF,
        "erasecertificate_af": 0xA545,
        "op1": 0xF8,
        "context_bit1": False,
        "flash_upper": 0x2A,
        "flash_locked": False,
    }
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    for name in (
        "writeflash_af",
        "writeflashunsafe_af",
        "writeabytesafe_af",
        "writeabyte_af",
        "erasepage_af",
        "eraseflash_af",
    ):
        value = observed[name]
        if not isinstance(value, int) or value >> 8 != 0 or value & 0x40 == 0:
            disagreements[name] = {
                "expected": "A=0 with Z set",
                "observed": value,
            }
    if report.bound_iff_af & 0x04:
        disagreements["bound_iff_af"] = {
            "expected": "P/V clear after _SetFlashLowerBound leaves IFF2 clear",
            "observed": report.bound_iff_af,
        }
    for name in ("probe_size", "boot_steps", "probe_steps", "probe_tstates"):
        value = observed[name]
        if not isinstance(value, int) or value <= 0:
            disagreements[name] = {"expected": "positive", "observed": value}
    if disagreements:
        raise WabbitemuHeadlessError(
            "native Flash bcall usage report disagrees with the ROM-derived "
            "contract: " + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "bcall_ids": [
                0x80C9,
                0x8087,
                0x80C6,
                0x8021,
                0x8084,
                0x8024,
                0x8060,
                0x80CF,
                0x5017,
            ],
            "safe_block_program": "08:4100 FF FF -> A5 5A",
            "unsafe_block_program": "3E:4100 FF FF -> 3C C3",
            "safe_byte_program": "08:4102 FE -> FC through OP1",
            "unsafe_byte_program": "3E:4102 FE -> F8 through OP1",
            "page_sector_erase": "0C:4000 becomes FF",
            "raw_sector_erase": "10:4567 becomes FF",
            "certificate_sector_erase": "3E:6001 becomes FF; AF preserved",
            "readback": "seven _FlashToRam calls match array data",
            "set_bound": "port-23 upper bound 2A; IFF2 clear",
            "physical_scope": False,
        },
        "native": observed,
    }


def run_flash_bcall_usage_probe(
    binary: Path,
    source_rom: Path,
    machine_code: Path,
    *,
    max_boot_steps: int = 5_000_000,
    max_probe_steps: int = 250_000,
) -> FlashBcallUsageReport:
    """Execute the assembled examples through Wabbitemu's retail ROM."""

    if max_boot_steps <= 0 or max_probe_steps <= 0:
        raise WabbitemuHeadlessError("probe step bounds must be positive")
    command = [
        str(binary),
        "--flash-bcall-usage-probe",
        str(source_rom),
        str(machine_code),
        str(max_boot_steps),
        str(max_probe_steps),
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot execute native Flash bcall usage probe: {error}"
        ) from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native Flash bcall usage probe failed: {detail}")
    report = parse_flash_bcall_usage_report(completed.stdout)
    return FlashBcallUsageReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "machine_code_sha256": file_sha256(machine_code),
            "binary_sha256": file_sha256(binary),
        }
    )
