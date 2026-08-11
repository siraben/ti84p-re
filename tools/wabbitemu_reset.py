"""Reusable source model and oracle for Wabbitemu reset behavior."""

from __future__ import annotations

from dataclasses import dataclass
import json

from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuResetReport


@dataclass(frozen=True)
class ResetDisposition:
    """One field group explicitly cleared, rebuilt, or retained by reset."""

    fields: str
    disposition: str
    value: str


LOW_LEVEL_RESET_DISPOSITIONS = (
    ResetDisposition("cpu.pc, cpu.sp", "cleared", "0x0000"),
    ResetDisposition("cpu.imode", "rebuilt", "1"),
    ResetDisposition(
        "cpu.interrupt, cpu.ei_block, cpu.iff1, cpu.iff2, cpu.halt",
        "cleared",
        "false",
    ),
    ResetDisposition(
        "cpu.read, cpu.write, cpu.output, cpu.input, cpu.prefix",
        "cleared",
        "zero",
    ),
    ResetDisposition(
        "memory.port27_remap_count, memory.port28_remap_count",
        "cleared",
        "zero",
    ),
    ResetDisposition(
        "memory.ram_lower, memory.ram_upper",
        "rebuilt",
        "0x0000 through 0x03FF",
    ),
    ResetDisposition(
        "memory.banks, memory.normal_banks",
        "rebuilt",
        "boot page / page 0 / page 0 / RAM page 0",
    ),
    ResetDisposition(
        "memory.boot_mapped, memory.hasChangedPage0",
        "cleared",
        "false",
    ),
    ResetDisposition(
        "memory.protected_page[0:4], memory.protected_page_set",
        "cleared",
        "zero",
    ),
    ResetDisposition(
        "CPU registers AF/BC/DE/HL, alternates, IX/IY, I/R, bus, link_write, model_bits",
        "retained",
        "seeded values",
    ),
    ResetDisposition("RAM contents", "retained", "seeded bytes"),
    ResetDisposition(
        "Flash command, delay, lock, data, error, toggle, and bounds",
        "retained",
        "seeded values",
    ),
    ResetDisposition(
        "protection mode and ports 0x06/0x07/0x0E/0x0F/0x24",
        "retained",
        "seeded values",
    ),
    ResetDisposition(
        "timer T-states, frequency, elapsed fields, and version",
        "retained",
        "seeded values",
    ),
    ResetDisposition(
        "delay, MD5, standard interrupt, keypad, raw link, link assist",
        "retained",
        "seeded values",
    ),
    ResetDisposition(
        "programmable timers, RTC, USB, GPIO, and LCD",
        "retained",
        "seeded values",
    ),
)

FRONTEND_RESET_DISPOSITIONS = (
    ResetDisposition(
        "all CPU_reset field groups",
        "delegated",
        "same as the low-level reset",
    ),
    ResetDisposition(
        "LCD active, cursor, x/y/z, contrast, word length, last read, display, queue",
        "rebuilt",
        "inactive, zeroed, contrast 32, 8-bit words",
    ),
    ResetDisposition(
        "LCD last_tstate and lcd_delay",
        "retained",
        "seeded values",
    ),
)

RETAINED_COMPONENTS = (
    "CPU general and alternate registers",
    "RAM contents",
    "Flash command state",
    "Flash bounds and port 0x24",
    "execution-protection selectors",
    "timer context",
    "delay registers",
    "MD5 accelerator",
    "standard interrupt controller",
    "keypad and ON state",
    "raw link and link assist",
    "programmable timers and RTC",
    "USB and GPIO",
    "LCD state under CPU_reset",
)


def expected_reset_values() -> dict[str, object]:
    """Return exact values for the directly seeded native reset cases."""

    return {
        "reset_pc": 0x0000,
        "reset_sp": 0x0000,
        "reset_imode": 1,
        "reset_interrupt": False,
        "reset_ei_block": False,
        "reset_iff1": False,
        "reset_iff2": False,
        "reset_halt": False,
        "reset_io_flags": False,
        "reset_prefix": 0,
        "cpu_general_retained": True,
        "reset_ram_lower": 0x0000,
        "reset_ram_upper": 0x03FF,
        "reset_port27": 0,
        "reset_port28": 0,
        "reset_boot_mapped": False,
        "reset_page0_changed": False,
        "reset_banks_normal": True,
        "protected_pages_clear": True,
        "reset_pages": (0x3F, 0x00, 0x00, 0x00),
        "reset_page_ram": (False, False, False, True),
        "retained": (True,) * len(RETAINED_COMPONENTS),
        "reset_flash_step": "fast-program",
        "reset_flash_locked": False,
        "reset_flash_error": True,
        "reset_flash_toggle": 0x40,
        "reset_flash_write_byte": 0x5A,
        "reset_flash_delay": 0x12345678,
        "reset_flash_lower": 0x01CC,
        "reset_flash_upper": 0x02DD,
        "reset_port24": 0xEE,
        "reset_prot_mode": 3,
        "reset_selectors": (0x12, 0x85, 0x34, 0x56),
        "reset_ram_marker": 0xA5,
        "reset_timer_tstates": 123456,
        "reset_timer_freq": 25_000_000,
        "reset_timer_version": 1,
        "frontend_lcd_active": False,
        "frontend_lcd_x": 0,
        "frontend_lcd_y": 0,
        "frontend_lcd_z": 0,
        "frontend_lcd_contrast": 32,
        "frontend_lcd_word_len": 8,
        "frontend_lcd_last_read": 0,
        "frontend_lcd_display_clear": True,
        "frontend_lcd_last_tstate": 654321,
        "frontend_lcd_delay": 61,
        "frontend_non_lcd_retained": True,
        "program_violation_pc": 0x0002,
        "program_violation_af": 0x07F5,
        "program_violation_bc": 0xB6C6,
        "program_violation_sp": 0x0000,
        "program_violation_tstates": 7,
        "program_violation_flash_step": "read",
        "program_violation_flash_error": False,
        "error_violation_pc": 0x0002,
        "error_violation_af": 0xE0E5,
        "error_violation_bc": 0xC6D6,
        "error_violation_sp": 0x0000,
        "error_violation_tstates": 7,
        "error_violation_flash_step": "error",
        "error_violation_flash_error": False,
    }


def validate_reset_report(report: WabbitemuResetReport) -> dict[str, object]:
    """Check native reset observations against the pinned source model."""

    expected = expected_reset_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native reset report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "low_level_dispositions": [
                disposition.__dict__ for disposition in LOW_LEVEL_RESET_DISPOSITIONS
            ],
            "frontend_dispositions": [
                disposition.__dict__ for disposition in FRONTEND_RESET_DISPOSITIONS
            ],
            "retained_components": RETAINED_COMPONENTS,
            "violation_step": (
                "CPU_opcode_fetch resets in place, then completes the same CPU_step"
            ),
            "program_state_tail": (
                "the fetch tail ends the program state and executes boot bytes 3E 07"
            ),
            "error_state_tail": (
                "the opcode fetch sees 3E; the immediate read returns E0 and clears "
                "flash_error while the FLASH_ERROR command step remains"
            ),
            "direct_seed_scope": (
                "the probe seeds internal state before direct CPU_reset and LCD-reset "
                "calls; it does not claim physical reset retention"
            ),
        },
        "native": observed,
    }
