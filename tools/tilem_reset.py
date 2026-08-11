"""Pinned TilEm reset build helpers, typed reports, and source oracle."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from tilem_core import (
    TilemCoreError,
    run_probe,
)
from tilem_core import (
    build_command as build_core_command,
)
from tilem_core import (
    build_probe as build_core_probe,
)

REPORT_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")
TOOLS = Path(__file__).resolve().parent
TilemResetError = TilemCoreError


@dataclass(frozen=True)
class ResetDisposition:
    """One TilEm field group explicitly reset or retained."""

    fields: str
    disposition: str
    value: str


RESET_GROUPS = (
    "Z80 registers and interrupt state",
    "LCD controller state",
    "raw link output and link-assist state",
    "keypad and ON-key state",
    "Flash command gate, state, and busy flag",
    "MD5 accelerator",
    "programmable timers",
    "TI-84 Plus mapped and derived hardware registers",
)

RETAINED_COMPONENTS = (
    "ROM and RAM contents",
    "LCD memory and emulation flags",
    "Flash address, data, toggles, override group, and emulation flags",
    "external link and GrayLink state",
    "unlisted TI-84 Plus hardware registers",
    "battery and power-on-HALT policy",
    "Z80 clock, access timestamps, emulation flags, and pending exception",
    "dynamically allocated Z80 timer",
    "dynamically allocated breakpoint",
)

RESET_DISPOSITIONS = (
    ResetDisposition(
        "AF/BC/DE/HL, alternates, IX/IY, IR, SP, WZ/WZ2",
        "rebuilt",
        "0xFFFF",
    ),
    ResetDisposition("PC, R bit 7", "rebuilt", "0x8000, 0x80"),
    ResetDisposition(
        "IFF1, IFF2, IM, pending interrupts, HALT",
        "cleared",
        "zero",
    ),
    ResetDisposition(
        "LCD controller fields",
        "rebuilt",
        "inactive, contrast 32, 8-bit mode, increment 7, row stride 16",
    ),
    ResetDisposition("LCD backing memory", "retained", "seeded bytes"),
    ResetDisposition(
        "raw link output and assist fields",
        "cleared",
        "zero",
    ),
    ResetDisposition(
        "external lines, link emulator, and GrayLink fields",
        "retained",
        "seeded values",
    ),
    ResetDisposition(
        "key group, ON state, and key matrix",
        "rebuilt",
        "group 0xFF; other fields zero",
    ),
    ResetDisposition(
        "Flash unlock, command state, and busy state",
        "cleared",
        "array-read mode and idle",
    ),
    ResetDisposition(
        "Flash program address/data, toggles, override, and emulation flags",
        "retained",
        "seeded values",
    ),
    ResetDisposition("MD5 registers, shift, and mode", "cleared", "zero"),
    ResetDisposition(
        "programmable-timer frequency, reload, status, and schedules",
        "cleared",
        "zero and disabled",
    ),
    ResetDisposition(
        "mapper, protection, speed, delay, and standard-timer registers",
        "rebuilt",
        "TI-84 Plus reset values",
    ),
    ResetDisposition(
        "port 0x05, ports 0x09-0x0F, RTC registers, and LCD_WAIT",
        "retained",
        "seeded values",
    ),
    ResetDisposition(
        "Z80 clock, access timestamps, flags, dynamic timers, and breakpoints",
        "retained",
        "scheduler/debugger state",
    ),
)


@dataclass(frozen=True)
class TilemResetReport:
    """Stable fields emitted by the direct TilEm reset probe."""

    reset_pc: int
    reset_sp: int
    reset_cpu_words_ffff: bool
    reset_r7: int
    reset_iff1: bool
    reset_iff2: bool
    reset_im: int
    reset_interrupts: int
    reset_halted: bool
    reset_pages: tuple[int, ...]
    reset_speed: int
    reset_ports_match: bool
    reset_derived_match: bool
    reset_groups: tuple[bool, ...]
    retained: tuple[bool, ...]
    reset_flash: tuple[int, ...]
    reset_lcd: tuple[int, ...]
    reset_link: tuple[int, ...]
    reset_keypad: tuple[int, ...]
    reset_md5: tuple[int, ...]
    reset_user_timers: bool
    retained_clock: int
    retained_dynamic_timer: int
    violation_stop: int
    violation_exception: int
    violation_pc: int
    violation_af: int
    violation_sp: int
    violation_pages: tuple[int, ...]
    violation_ram_marker: int
    violation_flash: tuple[int, ...]
    warnings: tuple[str, ...] = ()
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_command(
    source: Path,
    adapter: Path,
    output: Path,
    *,
    cc: str = "cc",
) -> list[str]:
    """Return the direct-core reset-probe compiler command."""

    return build_core_command(
        source,
        [TOOLS / "tilem_probe_support.c", adapter],
        output,
        cc=cc,
    )


def build_probe(
    source: Path,
    adapter: Path,
    output: Path,
    *,
    cc: str = "cc",
) -> list[str]:
    """Validate pinned sources and compile the direct-core probe."""

    return build_core_probe(
        source,
        [TOOLS / "tilem_probe_support.c", adapter],
        output,
        cc=cc,
    )


def _parse_vector(
    fields: dict[str, str],
    name: str,
    length: int,
    *,
    base: int,
) -> tuple[int, ...]:
    values = tuple(int(value, base) for value in fields[name].split(","))
    if len(values) != length:
        raise ValueError(f"{name} must contain {length} values")
    return values


def parse_reset_report(line: str) -> TilemResetReport:
    """Parse one direct TilEm reset and execution-violation report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    booleans = {
        "reset_cpu_words_ffff",
        "reset_iff1",
        "reset_iff2",
        "reset_halted",
        "reset_ports_match",
        "reset_derived_match",
        "reset_user_timers",
    }
    numeric = {
        "reset_pc",
        "reset_sp",
        "reset_r7",
        "reset_im",
        "reset_interrupts",
        "reset_speed",
        "retained_clock",
        "retained_dynamic_timer",
        "violation_stop",
        "violation_exception",
        "violation_pc",
        "violation_af",
        "violation_sp",
        "violation_ram_marker",
    }
    vectors = {
        "reset_pages",
        "reset_groups",
        "retained",
        "reset_flash",
        "reset_lcd",
        "reset_link",
        "reset_keypad",
        "reset_md5",
        "violation_pages",
        "violation_flash",
    }
    required = {"mode", *booleans, *numeric, *vectors}
    missing = sorted(required - fields.keys())
    if missing:
        raise TilemResetError("native TilEm reset report omits " + ", ".join(missing))
    if fields["mode"] != "tilem-reset-probe":
        raise TilemResetError(f"unexpected TilEm reset mode {fields['mode']!r}")
    try:
        values: dict[str, object] = {name: int(fields[name], 0) for name in numeric}
        bool_values = {name: int(fields[name], 0) for name in booleans}
        if any(value not in (0, 1) for value in bool_values.values()):
            raise ValueError("scalar Boolean fields must be zero or one")
        reset_groups_raw = _parse_vector(fields, "reset_groups", 8, base=0)
        retained_raw = _parse_vector(fields, "retained", 9, base=0)
        if any(value not in (0, 1) for value in (*reset_groups_raw, *retained_raw)):
            raise ValueError("reset and retention vectors must contain bits")
        values.update({name: bool(value) for name, value in bool_values.items()})
        return TilemResetReport(
            reset_pages=_parse_vector(fields, "reset_pages", 4, base=16),
            reset_groups=tuple(bool(value) for value in reset_groups_raw),
            retained=tuple(bool(value) for value in retained_raw),
            reset_flash=_parse_vector(fields, "reset_flash", 3, base=10),
            reset_lcd=_parse_vector(fields, "reset_lcd", 11, base=10),
            reset_link=_parse_vector(fields, "reset_link", 8, base=10),
            reset_keypad=_parse_vector(fields, "reset_keypad", 4, base=10),
            reset_md5=_parse_vector(fields, "reset_md5", 3, base=10),
            violation_pages=_parse_vector(fields, "violation_pages", 4, base=16),
            violation_flash=_parse_vector(fields, "violation_flash", 3, base=10),
            **values,
        )
    except (TypeError, ValueError) as error:
        raise TilemResetError(
            f"invalid native TilEm reset report: {line.strip()}"
        ) from error


def expected_reset_values() -> dict[str, object]:
    """Return the exact expected native observations for the seeded cases."""

    return {
        "reset_pc": 0x8000,
        "reset_sp": 0xFFFF,
        "reset_cpu_words_ffff": True,
        "reset_r7": 0x80,
        "reset_iff1": False,
        "reset_iff2": False,
        "reset_im": 0,
        "reset_interrupts": 0,
        "reset_halted": False,
        "reset_pages": (0x00, 0x3E, 0x3F, 0x3F),
        "reset_speed": 6000,
        "reset_ports_match": True,
        "reset_derived_match": True,
        "reset_groups": (True,) * len(RESET_GROUPS),
        "retained": (True,) * len(RETAINED_COMPONENTS),
        "reset_flash": (0, 0, 0),
        "reset_lcd": (0, 32, 0, 1, 0, 0, 0, 7, 0, 0, 16),
        "reset_link": (0,) * 8,
        "reset_keypad": (0xFF, 0, 0, 1),
        "reset_md5": (1, 0, 0),
        "reset_user_timers": True,
        "retained_clock": 123456,
        "retained_dynamic_timer": 4321,
        "violation_stop": 0x08,
        "violation_exception": 0x02,
        "violation_pc": 0x8000,
        "violation_af": 0xFFFF,
        "violation_sp": 0xFFFF,
        "violation_pages": (0x00, 0x3E, 0x3F, 0x3F),
        "violation_ram_marker": 0x5A,
        "violation_flash": (0, 0, 0),
        "warnings": ("TilEm warning: Executing in restricted Flash area",),
    }


def validate_reset_report(report: TilemResetReport) -> dict[str, object]:
    """Check direct reset observations against the pinned source model."""

    expected = expected_reset_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise TilemResetError(
            "native TilEm reset report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "reset_dispositions": [entry.__dict__ for entry in RESET_DISPOSITIONS],
            "reset_groups": RESET_GROUPS,
            "retained_components": RETAINED_COMPONENTS,
            "violation_order": (
                "fetch raises an exception, the complete opcode executes, and the "
                "main loop then calls tilem_calc_reset"
            ),
            "violation_fixture": (
                "forbidden Flash opcode LD (0x8000),A stores 0x5A into mapped RAM "
                "before the full reset"
            ),
            "direct_seed_scope": (
                "the probe seeds internal emulator fields and synthetic memory; it "
                "does not execute TI-OS or model physical reset retention"
            ),
        },
        "native": observed,
    }


def run_reset_probe(binary: Path) -> TilemResetReport:
    """Run the direct reset and violation cases through a built probe."""

    completed = run_probe(binary, ["--reset-probe"])
    report = parse_reset_report(completed.stdout)
    return TilemResetReport(
        **{
            **report.to_dict(),
            "warnings": completed.stderr_lines,
            "binary_sha256": completed.binary_sha256,
        }
    )
