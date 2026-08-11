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
class WabbitemuMd5EdgeReport:
    """Stable fields emitted by the native MD5 edge-behavior probe."""

    reset_operand_reads: tuple[int, ...]
    reset_result: int
    one_write_result: int
    three_write_result: int
    four_write_result: int
    five_write_result: int
    raw_shift: int
    raw_mode: int
    masked_control_result: int
    loaded_operand_reads: tuple[int, ...]
    before_mutation_result: int
    after_mutation_result: int
    mixed_result: int
    tstates: int
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuKeypadReport:
    """Stable fields emitted by the native keypad and ON-edge probe."""

    single_mask: int
    single_read: int
    same_column_mask: int
    same_column_read: int
    rectangle_mask: int
    rectangle_read: int
    transitive_mask: int
    transitive_read: int
    unwired_mask: int
    unwired_read: int
    on_initial_status: int
    on_enabled_status: int
    on_press_before_eval: int
    on_press_after_eval: int
    on_held_after_ack: int
    on_held_after_eval: int
    on_release_before_eval: int
    on_release_after_eval: int
    on_second_press_before_eval: int
    on_second_press_after_eval: int
    tstates: int
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuTimerReport:
    """Stable fields emitted by the native timer and RTC edge probe."""

    crystal_source: int
    crystal_divisor: int
    crystal_elapsed_ticks: int
    crystal_reads: tuple[int, ...]
    crystal_status: int
    crystal_port4: int
    cpu_source: int
    cpu_divisor: int
    cpu_elapsed_tstates: int
    cpu_count_read: int
    cpu_status: int
    cpu_port4: int
    zero_elapsed_tstates: int
    zero_count_read: int
    zero_status: int
    zero_port4: int
    acknowledged_status: int
    acknowledged_port4: int
    halted_count_read: int
    halted_status: int
    interrupt_while_halted: bool
    interrupt_after_resume: bool
    rtc_initial: int
    rtc_committed: int
    rtc_running: int
    rtc_frozen: int
    rtc_late_disabled: int
    final_elapsed: int
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuAsicReport:
    """Stable fields emitted by the native ASIC-control edge probe."""

    initial_flash_locked: bool
    port02_locked: int
    port02_unlocked: int
    port15_ram_v0: int
    port15_ram_v2: int
    port39_active: bool
    port39_read_accepted: bool
    port39_read: int
    port3a_active: bool
    port3a_initial: int
    port3a_first_written: int
    port3a_first_read: int
    port3a_second_written: int
    port3a_second_read: int
    port21_active: bool
    port21_protected: bool
    locked_write_accepted: bool
    locked_read: int
    locked_internal_mode: int
    locked_model_bits: int
    mode3_write_accepted: bool
    mode3_written: int
    mode3_read: int
    mode3_internal_mode: int
    mode3_model_bits: int
    group3_write_accepted: bool
    group3_written: int
    group3_read: int
    group3_internal_mode: int
    group3_model_bits: int
    combined_write_accepted: bool
    combined_written: int
    combined_read: int
    combined_internal_mode: int
    combined_model_bits: int
    tstates: int
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuLcdReport:
    """Stable fields emitted by the native LCD and bus-timing edge probe."""

    configured_lcd_delay: int
    port12_active: bool
    port12_read_accepted: bool
    port12_read: int
    port13_active: bool
    port13_read_accepted: bool
    port13_read: int
    early_status: int
    boundary_status: int
    status_last_tstate: int
    early_write_cell: int
    early_write_column: int
    wrap_column14: int
    wrap_column15: int
    wrap_column0: int
    wrap_column1: int
    wrap_column2: int
    wrap_final_column: int
    direct_column15: int
    alias_column31: int
    alias_final_column: int
    latch_reads: tuple[int, ...]
    latch_read_tstates: int
    latch_last_tstate: int
    latch_final_column: int
    ready_field: int
    ready_hold: int
    ready_last_tstate: int
    ready_at_240: int
    ready_at_241: int
    accepted_status_read: int
    ready_after_read_last_tstate: int
    ready_after_read: int
    delay_register: int
    delay_before: int
    delay_after: int
    delayed_status: int
    flash_opcode_wait: bool
    flash_read_wait: bool
    flash_write_wait: bool
    ram_opcode_wait: bool
    ram_read_wait: bool
    ram_write_wait: bool
    requested_speed: int
    clamped_speed: int
    timer_version: int
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuSpeedReport:
    """Stable fields emitted by the native speed and delay-register probe."""

    port20_active: bool
    delay_ports_active: tuple[bool, ...]
    reset_speed: int
    reset_frequency: int
    reset_timer_version: int
    reset_delay_reads: tuple[int, ...]
    default_speed_reads: tuple[int, ...]
    default_frequencies: tuple[int, ...]
    extra_speed_reads: tuple[int, ...]
    extra_frequencies: tuple[int, ...]
    latch_written: tuple[int, ...]
    latch_reads: tuple[int, ...]
    wait_masks: tuple[int, ...]
    port2d_written: int
    port2d_read: int
    port2d_wait_unchanged: bool
    port2d_freq_unchanged: bool
    port2d_timer_version_unchanged: bool
    port2d_xtal_unchanged: bool
    port2d_lcd_active_unchanged: bool
    port2d_halt_unchanged: bool
    port2d_interrupt_unchanged: bool
    port2d_tstates_unchanged: bool
    tstates: int
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuProtectionPortReport:
    """Stable fields emitted by the native protected-boundary port probe."""

    port_active: tuple[bool, ...]
    port_protected: tuple[bool, ...]
    initial_flash_locked: bool
    initial_reads: tuple[int, ...]
    initial_flash_lower: int
    initial_flash_upper: int
    initial_port24: int
    initial_ram_lower: int
    initial_ram_upper: int
    locked_write_accepted: tuple[bool, ...]
    locked_reads: tuple[int, ...]
    configured_flash_locked: bool
    seeded_flash_lower: int
    seeded_flash_upper: int
    low_writes: tuple[int, ...]
    low_write_reads: tuple[int, ...]
    low_write_flash_lower: int
    low_write_flash_upper: int
    port24_written: int
    port24_read: int
    port24_flash_lower: int
    port24_flash_upper: int
    wrap_values: tuple[int, ...]
    ram_lower_reads: tuple[int, ...]
    ram_lower_internal: tuple[int, ...]
    ram_upper_reads: tuple[int, ...]
    ram_upper_internal: tuple[int, ...]
    tstates: int
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuResetReport:
    """Stable fields emitted by the native reset-retention probe."""

    reset_pc: int
    reset_sp: int
    reset_imode: int
    reset_interrupt: bool
    reset_ei_block: bool
    reset_iff1: bool
    reset_iff2: bool
    reset_halt: bool
    reset_io_flags: bool
    reset_prefix: int
    cpu_general_retained: bool
    reset_ram_lower: int
    reset_ram_upper: int
    reset_port27: int
    reset_port28: int
    reset_boot_mapped: bool
    reset_page0_changed: bool
    reset_banks_normal: bool
    protected_pages_clear: bool
    reset_pages: tuple[int, ...]
    reset_page_ram: tuple[bool, ...]
    retained: tuple[bool, ...]
    reset_flash_step: str
    reset_flash_locked: bool
    reset_flash_error: bool
    reset_flash_toggle: int
    reset_flash_write_byte: int
    reset_flash_delay: int
    reset_flash_lower: int
    reset_flash_upper: int
    reset_port24: int
    reset_prot_mode: int
    reset_selectors: tuple[int, ...]
    reset_ram_marker: int
    reset_timer_tstates: int
    reset_timer_freq: int
    reset_timer_version: int
    frontend_lcd_active: bool
    frontend_lcd_x: int
    frontend_lcd_y: int
    frontend_lcd_z: int
    frontend_lcd_contrast: int
    frontend_lcd_word_len: int
    frontend_lcd_last_read: int
    frontend_lcd_display_clear: bool
    frontend_lcd_last_tstate: int
    frontend_lcd_delay: int
    frontend_non_lcd_retained: bool
    program_violation_pc: int
    program_violation_af: int
    program_violation_bc: int
    program_violation_sp: int
    program_violation_tstates: int
    program_violation_flash_step: str
    program_violation_flash_error: bool
    error_violation_pc: int
    error_violation_af: int
    error_violation_bc: int
    error_violation_sp: int
    error_violation_tstates: int
    error_violation_flash_step: str
    error_violation_flash_error: bool
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuInterruptReport:
    """Stable fields emitted by the native interrupt-controller edge probe."""

    initial_mask: int
    stored_mask: int
    on_latch_before_ack: bool
    on_latch_after_ack: bool
    mask_after_on_ack: int
    rate0_timer1_ns: int
    rate1_timer1_ns: int
    rate2_timer1_ns: int
    rate3_timer1_ns: int
    rate3_timer2_ns: int
    rate3_timer2_offset_ns: int
    exact_boundary_status: int
    exact_boundary_interrupt: bool
    after_boundary_status: int
    after_boundary_interrupt: bool
    after_port3_ack_status: int
    before_port2_ack_status: int
    after_port2_ack_status: int
    completion_status: int
    low_power_lcd_active: bool
    restored_lcd_active: bool
    tstates: int
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuLinkReport:
    """Stable fields emitted by the native raw-link and assist edge probe."""

    port08_active: bool
    port09_active: bool
    port0a_active: bool
    port0b_active: bool
    port0b_read_accepted: bool
    port0b_read: int
    port0c_active: bool
    port0c_read_accepted: bool
    port0c_read: int
    port0d_active: bool
    initial_enable: int
    initial_status: int
    initial_in: int
    initial_out: int
    raw_reads: tuple[int, ...]
    raw_high_write: int
    raw_peer_read: int
    raw_peer_interrupt: bool
    idle_ready_status: int
    idle_ready_interrupt: bool
    idle_after_out_status: int
    assist_send_drives: tuple[int, ...]
    assist_send_status: int
    assist_send_interrupt: bool
    assist_send_out: int
    assist_send_after_out_status: int
    assist_receive_status: int
    assist_receive_interrupt: bool
    assist_receive_in: int
    assist_receive_after_in_status: int
    assist_error_status: int
    assist_error_interrupt: bool
    assist_error_after_read_status: int
    tstates: int
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuUsbReport:
    """Stable fields emitted by the native Fake USB edge probe."""

    port4a_active: bool
    port4c_active: bool
    port4d_active: bool
    port54_active: bool
    port54_read_accepted: bool
    port54_read: int
    port55_active: bool
    port56_active: bool
    port57_active: bool
    port5b_active: bool
    port80_active: bool
    initial_port4a: int
    initial_port4c: int
    initial_port4d: int
    initial_port55: int
    initial_port56: int
    initial_port57: int
    initial_port5b: int
    initial_port80: int
    initial_line_state: int
    initial_events: int
    initial_event_mask: int
    initial_line_interrupt: bool
    initial_protocol_interrupt: bool
    initial_stored_port4a: int
    initial_stored_port4c: int
    initial_stored_port54: int
    mask_ff_read: int
    mask_zero_read: int
    event_interrupt: bool
    event_line_interrupt: bool
    event_line_state: int
    event_events: int
    event_port4a: int
    event_port4d: int
    event_port55: int
    event_port56: int
    repeated_event_interrupt: bool
    repeated_events: int
    summary_none: int
    summary_line: int
    summary_protocol: int
    summary_both: int
    port5b_ff_read: int
    protocol_interrupt_enabled: bool
    port80_ff_read: int
    stored_dev_address: int
    port4c_ff_read: int
    stored_port4c: int
    port4d_false_pair: int
    port4d_true_pair: int
    port4a_true_condition: int
    port4a_false_condition: int
    tstates: int
    source_rom_sha256: str = ""
    binary_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WabbitemuMapperReport:
    """Stable fields emitted by the native memory-mapper edge probe."""

    port04_active: bool
    port05_active: bool
    port06_active: bool
    port07_active: bool
    port0e_active: bool
    port0f_active: bool
    port27_active: bool
    port28_active: bool
    initial_port04_status: int
    initial_port05: int
    initial_port06: int
    initial_port07: int
    initial_port0e: int
    initial_port0f: int
    initial_port27: int
    initial_port28: int
    initial_boot_mapped: bool
    initial_page0_changed: bool
    initial_fixed_page: int
    initial_a_page: int
    initial_b_page: int
    initial_c_page: int
    initial_a_ram: bool
    initial_b_ram: bool
    initial_c_ram: bool
    fixed_page_after_data_read: int
    page0_changed_after_data_read: bool
    fixed_page_after_opcode: int
    page0_changed_after_opcode: bool
    handoff_pc: int
    port05_ff_read: int
    port0e_ff_read: int
    port06_flash_read: int
    stored_port06_flash: int
    port0f_ff_read: int
    port07_flash_read: int
    stored_port07_flash: int
    port06_ram_ff_read: int
    stored_port06_ram: int
    port07_ram_fe_read: int
    stored_port07_ram: int
    paired_port04_status: int
    paired_port05: int
    paired_port06: int
    paired_port07: int
    paired_boot_mapped: bool
    paired_a_page: int
    paired_b_page: int
    paired_c_page: int
    paired_a_ram: bool
    paired_b_ram: bool
    paired_c_ram: bool
    port27_ff_read: int
    port28_one_read: int
    independent_8000: int
    independent_803f: int
    independent_8040: int
    independent_fb63: int
    independent_fb64: int
    independent_write_ram1: int
    independent_write_underlying_b: int
    independent_write_ram0: int
    independent_write_underlying_c: int
    independent_fetch_halted: bool
    paired_8000: int
    paired_803f: int
    paired_8040: int
    paired_fb63: int
    paired_fb64: int
    paired_fetch_halted: bool
    paired_write_ram1: int
    paired_write_underlying_b: int
    paired_write_ram0: int
    paired_write_underlying_c: int
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


def parse_md5_edge_report(line: str) -> WabbitemuMd5EdgeReport:
    """Parse one native MD5 edge-behavior report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    numeric = {
        "reset_result",
        "one_write_result",
        "three_write_result",
        "four_write_result",
        "five_write_result",
        "raw_shift",
        "raw_mode",
        "masked_control_result",
        "before_mutation_result",
        "after_mutation_result",
        "mixed_result",
        "tstates",
    }
    required = {"mode", "reset_operand_reads", "loaded_operand_reads", *numeric}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native MD5 edge report omits " + ", ".join(missing)
        )
    if fields["mode"] != "md5-edge-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native MD5 edge mode {fields['mode']!r}"
        )
    try:
        values = {name: int(fields[name], 0) for name in numeric}
        reset_reads = tuple(
            int(value, 16) for value in fields["reset_operand_reads"].split(",")
        )
        loaded_reads = tuple(
            int(value, 16) for value in fields["loaded_operand_reads"].split(",")
        )
        if len(reset_reads) != 4 or len(loaded_reads) != 4:
            raise ValueError("MD5 operand-read vectors must contain four bytes")
        return WabbitemuMd5EdgeReport(
            reset_operand_reads=reset_reads,
            loaded_operand_reads=loaded_reads,
            **values,
        )
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native MD5 edge report: {line.strip()}"
        ) from error


def parse_keypad_report(line: str) -> WabbitemuKeypadReport:
    """Parse one native keypad matrix and ON-edge report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    numeric = {
        "single_mask",
        "single_read",
        "same_column_mask",
        "same_column_read",
        "rectangle_mask",
        "rectangle_read",
        "transitive_mask",
        "transitive_read",
        "unwired_mask",
        "unwired_read",
        "on_initial_status",
        "on_enabled_status",
        "on_press_before_eval",
        "on_press_after_eval",
        "on_held_after_ack",
        "on_held_after_eval",
        "on_release_before_eval",
        "on_release_after_eval",
        "on_second_press_before_eval",
        "on_second_press_after_eval",
        "tstates",
    }
    required = {"mode", *numeric}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native keypad report omits " + ", ".join(missing)
        )
    if fields["mode"] != "keypad-edge-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native keypad mode {fields['mode']!r}"
        )
    try:
        values = {name: int(fields[name], 0) for name in numeric}
        byte_fields = numeric - {"tstates"}
        if any(not 0 <= values[name] <= 0xFF for name in byte_fields):
            raise ValueError("keypad report byte exceeds its range")
        return WabbitemuKeypadReport(**values)
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native keypad report: {line.strip()}"
        ) from error


def parse_timer_report(line: str) -> WabbitemuTimerReport:
    """Parse one native programmable-timer and RTC edge report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    numeric = {
        "crystal_source",
        "crystal_divisor",
        "crystal_elapsed_ticks",
        "crystal_status",
        "crystal_port4",
        "cpu_source",
        "cpu_divisor",
        "cpu_elapsed_tstates",
        "cpu_count_read",
        "cpu_status",
        "cpu_port4",
        "zero_elapsed_tstates",
        "zero_count_read",
        "zero_status",
        "zero_port4",
        "acknowledged_status",
        "acknowledged_port4",
        "halted_count_read",
        "halted_status",
        "rtc_initial",
        "rtc_committed",
        "rtc_running",
        "rtc_frozen",
        "rtc_late_disabled",
        "final_elapsed",
    }
    booleans = {"interrupt_while_halted", "interrupt_after_resume"}
    required = {"mode", "crystal_reads", *numeric, *booleans}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native timer report omits " + ", ".join(missing)
        )
    if fields["mode"] != "timer-edge-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native timer mode {fields['mode']!r}"
        )
    try:
        values: dict[str, object] = {
            name: int(fields[name], 0) for name in numeric
        }
        bool_values = {name: int(fields[name], 0) for name in booleans}
        if any(value not in (0, 1) for value in bool_values.values()):
            raise ValueError("timer interrupt fields must be zero or one")
        reads = tuple(int(value, 16) for value in fields["crystal_reads"].split(","))
        if len(reads) != 3 or any(not 0 <= value <= 0xFF for value in reads):
            raise ValueError("timer crystal-read vector must contain three bytes")
        values.update({name: bool(value) for name, value in bool_values.items()})
        return WabbitemuTimerReport(crystal_reads=reads, **values)
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native timer report: {line.strip()}"
        ) from error


def parse_asic_report(line: str) -> WabbitemuAsicReport:
    """Parse one native ASIC status, identity, protection, and GPIO report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    booleans = {
        "initial_flash_locked",
        "port39_active",
        "port39_read_accepted",
        "port3a_active",
        "port21_active",
        "port21_protected",
        "locked_write_accepted",
        "mode3_write_accepted",
        "group3_write_accepted",
        "combined_write_accepted",
    }
    numeric = {
        "port02_locked",
        "port02_unlocked",
        "port15_ram_v0",
        "port15_ram_v2",
        "port39_read",
        "port3a_initial",
        "port3a_first_written",
        "port3a_first_read",
        "port3a_second_written",
        "port3a_second_read",
        "locked_read",
        "locked_internal_mode",
        "locked_model_bits",
        "mode3_written",
        "mode3_read",
        "mode3_internal_mode",
        "mode3_model_bits",
        "group3_written",
        "group3_read",
        "group3_internal_mode",
        "group3_model_bits",
        "combined_written",
        "combined_read",
        "combined_internal_mode",
        "combined_model_bits",
        "tstates",
    }
    required = {"mode", *booleans, *numeric}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native ASIC report omits " + ", ".join(missing)
        )
    if fields["mode"] != "asic-edge-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native ASIC mode {fields['mode']!r}"
        )
    try:
        values: dict[str, object] = {
            name: int(fields[name], 0) for name in numeric
        }
        bool_values = {name: int(fields[name], 0) for name in booleans}
        if any(value not in (0, 1) for value in bool_values.values()):
            raise ValueError("ASIC report booleans must be zero or one")
        values.update({name: bool(value) for name, value in bool_values.items()})
        return WabbitemuAsicReport(**values)
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native ASIC report: {line.strip()}"
        ) from error


def parse_lcd_report(line: str) -> WabbitemuLcdReport:
    """Parse one native LCD controller and bus-timing edge report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    booleans = {
        "port12_active",
        "port12_read_accepted",
        "port13_active",
        "port13_read_accepted",
        "flash_opcode_wait",
        "flash_read_wait",
        "flash_write_wait",
        "ram_opcode_wait",
        "ram_read_wait",
        "ram_write_wait",
    }
    numeric = {
        "configured_lcd_delay",
        "port12_read",
        "port13_read",
        "early_status",
        "boundary_status",
        "status_last_tstate",
        "early_write_cell",
        "early_write_column",
        "wrap_column14",
        "wrap_column15",
        "wrap_column0",
        "wrap_column1",
        "wrap_column2",
        "wrap_final_column",
        "direct_column15",
        "alias_column31",
        "alias_final_column",
        "latch_read_tstates",
        "latch_last_tstate",
        "latch_final_column",
        "ready_field",
        "ready_hold",
        "ready_last_tstate",
        "ready_at_240",
        "ready_at_241",
        "accepted_status_read",
        "ready_after_read_last_tstate",
        "ready_after_read",
        "delay_register",
        "delay_before",
        "delay_after",
        "delayed_status",
        "requested_speed",
        "clamped_speed",
        "timer_version",
    }
    required = {"mode", "latch_reads", *booleans, *numeric}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native LCD report omits " + ", ".join(missing)
        )
    if fields["mode"] != "lcd-edge-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native LCD mode {fields['mode']!r}"
        )
    try:
        values: dict[str, object] = {
            name: int(fields[name], 0) for name in numeric
        }
        bool_values = {name: int(fields[name], 0) for name in booleans}
        if any(value not in (0, 1) for value in bool_values.values()):
            raise ValueError("LCD report booleans must be zero or one")
        reads = tuple(int(value, 16) for value in fields["latch_reads"].split(","))
        if len(reads) != 3 or any(not 0 <= value <= 0xFF for value in reads):
            raise ValueError("LCD latch-read vector must contain three bytes")
        values.update({name: bool(value) for name, value in bool_values.items()})
        return WabbitemuLcdReport(latch_reads=reads, **values)
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native LCD report: {line.strip()}"
        ) from error


def parse_speed_report(line: str) -> WabbitemuSpeedReport:
    """Parse one native CPU-speed and delay-register edge report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    booleans = {
        "port20_active",
        "port2d_wait_unchanged",
        "port2d_freq_unchanged",
        "port2d_timer_version_unchanged",
        "port2d_xtal_unchanged",
        "port2d_lcd_active_unchanged",
        "port2d_halt_unchanged",
        "port2d_interrupt_unchanged",
        "port2d_tstates_unchanged",
    }
    numeric = {
        "reset_speed",
        "reset_frequency",
        "reset_timer_version",
        "port2d_written",
        "port2d_read",
        "tstates",
    }
    vectors = {
        "delay_ports_active",
        "reset_delay_reads",
        "default_speed_reads",
        "default_frequencies",
        "extra_speed_reads",
        "extra_frequencies",
        "latch_written",
        "latch_reads",
        "wait_masks",
    }
    required = {"mode", *booleans, *numeric, *vectors}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native speed report omits " + ", ".join(missing)
        )
    if fields["mode"] != "speed-edge-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native speed mode {fields['mode']!r}"
        )
    try:
        values: dict[str, object] = {
            name: int(fields[name], 0) for name in numeric
        }
        bool_values = {name: int(fields[name], 0) for name in booleans}
        if any(value not in (0, 1) for value in bool_values.values()):
            raise ValueError("speed report booleans must be zero or one")
        delay_active_values = tuple(
            int(value, 0) for value in fields["delay_ports_active"].split(",")
        )
        if len(delay_active_values) != 7:
            raise ValueError("delay-port activity vector must contain seven bits")
        if any(value not in (0, 1) for value in delay_active_values):
            raise ValueError("delay-port activity values must be zero or one")
        delay_active = tuple(bool(value) for value in delay_active_values)
        byte_vectors = {
            name: tuple(int(value, 16) for value in fields[name].split(","))
            for name in (
                "reset_delay_reads",
                "latch_written",
                "latch_reads",
                "wait_masks",
            )
        }
        decimal_vectors = {
            name: tuple(int(value, 10) for value in fields[name].split(","))
            for name in (
                "default_speed_reads",
                "default_frequencies",
                "extra_speed_reads",
                "extra_frequencies",
            )
        }
        if any(
            len(byte_vectors[name]) != length
            for name, length in {
                "reset_delay_reads": 7,
                "latch_written": 7,
                "latch_reads": 7,
                "wait_masks": 4,
            }.items()
        ):
            raise ValueError("speed report contains a malformed byte vector")
        if any(len(vector) != 4 for vector in decimal_vectors.values()):
            raise ValueError("speed report contains a malformed mode vector")
        if any(
            not 0 <= value <= 0xFF
            for vector in byte_vectors.values()
            for value in vector
        ):
            raise ValueError("speed report byte vectors must contain bytes")
        values.update({name: bool(value) for name, value in bool_values.items()})
        values.update(byte_vectors)
        values.update(decimal_vectors)
        return WabbitemuSpeedReport(
            delay_ports_active=delay_active,
            **values,
        )
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native speed report: {line.strip()}"
        ) from error


def parse_protection_port_report(line: str) -> WabbitemuProtectionPortReport:
    """Parse one native protected-boundary register report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    boolean_scalars = {"initial_flash_locked", "configured_flash_locked"}
    numeric = {
        "initial_flash_lower",
        "initial_flash_upper",
        "initial_port24",
        "initial_ram_lower",
        "initial_ram_upper",
        "seeded_flash_lower",
        "seeded_flash_upper",
        "low_write_flash_lower",
        "low_write_flash_upper",
        "port24_written",
        "port24_read",
        "port24_flash_lower",
        "port24_flash_upper",
        "tstates",
    }
    vectors = {
        "port_active",
        "port_protected",
        "initial_reads",
        "locked_write_accepted",
        "locked_reads",
        "low_writes",
        "low_write_reads",
        "wrap_values",
        "ram_lower_reads",
        "ram_lower_internal",
        "ram_upper_reads",
        "ram_upper_internal",
    }
    required = {"mode", *boolean_scalars, *numeric, *vectors}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native protection-port report omits " + ", ".join(missing)
        )
    if fields["mode"] != "protection-port-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native protection-port mode {fields['mode']!r}"
        )
    try:
        values: dict[str, object] = {
            name: int(fields[name], 0) for name in numeric
        }
        boolean_values = {
            name: int(fields[name], 0) for name in boolean_scalars
        }
        if any(value not in (0, 1) for value in boolean_values.values()):
            raise ValueError("protection-port booleans must be zero or one")

        boolean_vectors = {}
        for name in ("port_active", "port_protected", "locked_write_accepted"):
            raw = tuple(int(value, 0) for value in fields[name].split(","))
            if len(raw) != 5 or any(value not in (0, 1) for value in raw):
                raise ValueError(f"{name} must contain five bits")
            boolean_vectors[name] = tuple(bool(value) for value in raw)

        lengths = {
            "initial_reads": 5,
            "locked_reads": 5,
            "low_writes": 2,
            "low_write_reads": 2,
            "wrap_values": 4,
            "ram_lower_reads": 4,
            "ram_lower_internal": 4,
            "ram_upper_reads": 4,
            "ram_upper_internal": 4,
        }
        integer_vectors = {
            name: tuple(int(value, 16) for value in fields[name].split(","))
            for name in lengths
        }
        if any(
            len(integer_vectors[name]) != length
            for name, length in lengths.items()
        ):
            raise ValueError("protection-port report contains a malformed vector")
        byte_vectors = {
            "initial_reads",
            "locked_reads",
            "low_writes",
            "low_write_reads",
            "wrap_values",
            "ram_lower_reads",
            "ram_upper_reads",
        }
        if any(
            not 0 <= value <= 0xFF
            for name in byte_vectors
            for value in integer_vectors[name]
        ):
            raise ValueError("protection-port byte vectors must contain bytes")
        if any(
            not 0 <= value <= 0xFFFF
            for name in ("ram_lower_internal", "ram_upper_internal")
            for value in integer_vectors[name]
        ):
            raise ValueError("protection-port internal vectors must contain words")
        values.update({name: bool(value) for name, value in boolean_values.items()})
        values.update(boolean_vectors)
        values.update(integer_vectors)
        return WabbitemuProtectionPortReport(**values)
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native protection-port report: {line.strip()}"
        ) from error


def parse_reset_report(line: str) -> WabbitemuResetReport:
    """Parse one native low-level, frontend, and violation-reset report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    booleans = {
        "reset_interrupt",
        "reset_ei_block",
        "reset_iff1",
        "reset_iff2",
        "reset_halt",
        "reset_io_flags",
        "cpu_general_retained",
        "reset_boot_mapped",
        "reset_page0_changed",
        "reset_banks_normal",
        "protected_pages_clear",
        "reset_flash_locked",
        "reset_flash_error",
        "frontend_lcd_active",
        "frontend_lcd_display_clear",
        "frontend_non_lcd_retained",
        "program_violation_flash_error",
        "error_violation_flash_error",
    }
    numeric = {
        "reset_pc",
        "reset_sp",
        "reset_imode",
        "reset_prefix",
        "reset_ram_lower",
        "reset_ram_upper",
        "reset_port27",
        "reset_port28",
        "reset_flash_toggle",
        "reset_flash_write_byte",
        "reset_flash_delay",
        "reset_flash_lower",
        "reset_flash_upper",
        "reset_port24",
        "reset_prot_mode",
        "reset_ram_marker",
        "reset_timer_tstates",
        "reset_timer_freq",
        "reset_timer_version",
        "frontend_lcd_x",
        "frontend_lcd_y",
        "frontend_lcd_z",
        "frontend_lcd_contrast",
        "frontend_lcd_word_len",
        "frontend_lcd_last_read",
        "frontend_lcd_last_tstate",
        "frontend_lcd_delay",
        "program_violation_pc",
        "program_violation_af",
        "program_violation_bc",
        "program_violation_sp",
        "program_violation_tstates",
        "error_violation_pc",
        "error_violation_af",
        "error_violation_bc",
        "error_violation_sp",
        "error_violation_tstates",
    }
    strings = {
        "reset_flash_step",
        "program_violation_flash_step",
        "error_violation_flash_step",
    }
    vectors = {"reset_pages", "reset_page_ram", "retained", "reset_selectors"}
    required = {"mode", *booleans, *numeric, *strings, *vectors}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native reset report omits " + ", ".join(missing)
        )
    if fields["mode"] != "reset-retention-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native reset mode {fields['mode']!r}"
        )
    try:
        values: dict[str, object] = {
            name: int(fields[name], 0) for name in numeric
        }
        boolean_values = {name: int(fields[name], 0) for name in booleans}
        if any(value not in (0, 1) for value in boolean_values.values()):
            raise ValueError("reset report booleans must be zero or one")

        reset_pages = tuple(
            int(value, 16) for value in fields["reset_pages"].split(",")
        )
        reset_selectors = tuple(
            int(value, 16) for value in fields["reset_selectors"].split(",")
        )
        if len(reset_pages) != 4 or len(reset_selectors) != 4:
            raise ValueError("reset page and selector vectors must contain four bytes")
        if any(
            not 0 <= value <= 0xFF
            for value in (*reset_pages, *reset_selectors)
        ):
            raise ValueError("reset page and selector vectors must contain bytes")

        boolean_vectors: dict[str, tuple[bool, ...]] = {}
        for name, length in (("reset_page_ram", 4), ("retained", 14)):
            raw = tuple(int(value, 0) for value in fields[name].split(","))
            if len(raw) != length or any(value not in (0, 1) for value in raw):
                raise ValueError(f"{name} must contain {length} bits")
            boolean_vectors[name] = tuple(bool(value) for value in raw)

        flash_steps = {
            fields["reset_flash_step"],
            fields["program_violation_flash_step"],
            fields["error_violation_flash_step"],
        }
        valid_flash_steps = {
            "read",
            "aa",
            "55",
            "program",
            "erase",
            "erase-aa",
            "erase-55",
            "fast",
            "fast-program",
            "fast-exit",
            "autoselect",
            "error",
            "unknown",
        }
        if not flash_steps <= valid_flash_steps:
            raise ValueError("reset report contains an unknown Flash step")

        values.update({name: bool(value) for name, value in boolean_values.items()})
        values.update({name: fields[name] for name in strings})
        values.update(boolean_vectors)
        return WabbitemuResetReport(
            reset_pages=reset_pages,
            reset_selectors=reset_selectors,
            **values,
        )
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native reset report: {line.strip()}"
        ) from error


def parse_interrupt_report(line: str) -> WabbitemuInterruptReport:
    """Parse one native standard-interrupt and low-power edge report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    booleans = {
        "on_latch_before_ack",
        "on_latch_after_ack",
        "exact_boundary_interrupt",
        "after_boundary_interrupt",
        "low_power_lcd_active",
        "restored_lcd_active",
    }
    numeric = {
        "initial_mask",
        "stored_mask",
        "mask_after_on_ack",
        "rate0_timer1_ns",
        "rate1_timer1_ns",
        "rate2_timer1_ns",
        "rate3_timer1_ns",
        "rate3_timer2_ns",
        "rate3_timer2_offset_ns",
        "exact_boundary_status",
        "after_boundary_status",
        "after_port3_ack_status",
        "before_port2_ack_status",
        "after_port2_ack_status",
        "completion_status",
        "tstates",
    }
    required = {"mode", *booleans, *numeric}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native interrupt report omits " + ", ".join(missing)
        )
    if fields["mode"] != "interrupt-edge-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native interrupt mode {fields['mode']!r}"
        )
    try:
        values: dict[str, object] = {
            name: int(fields[name], 0) for name in numeric
        }
        bool_values = {name: int(fields[name], 0) for name in booleans}
        if any(value not in (0, 1) for value in bool_values.values()):
            raise ValueError("interrupt report booleans must be zero or one")
        values.update({name: bool(value) for name, value in bool_values.items()})
        return WabbitemuInterruptReport(**values)
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native interrupt report: {line.strip()}"
        ) from error


def parse_link_report(line: str) -> WabbitemuLinkReport:
    """Parse one native raw-link and link-assist edge report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    booleans = {
        "port08_active",
        "port09_active",
        "port0a_active",
        "port0b_active",
        "port0b_read_accepted",
        "port0c_active",
        "port0c_read_accepted",
        "port0d_active",
        "raw_peer_interrupt",
        "idle_ready_interrupt",
        "assist_send_interrupt",
        "assist_receive_interrupt",
        "assist_error_interrupt",
    }
    numeric = {
        "port0b_read",
        "port0c_read",
        "initial_enable",
        "initial_status",
        "initial_in",
        "initial_out",
        "raw_high_write",
        "raw_peer_read",
        "idle_ready_status",
        "idle_after_out_status",
        "assist_send_status",
        "assist_send_out",
        "assist_send_after_out_status",
        "assist_receive_status",
        "assist_receive_in",
        "assist_receive_after_in_status",
        "assist_error_status",
        "assist_error_after_read_status",
        "tstates",
    }
    required = {"mode", "raw_reads", "assist_send_drives", *booleans, *numeric}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native link report omits " + ", ".join(missing)
        )
    if fields["mode"] != "link-edge-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native link mode {fields['mode']!r}"
        )
    try:
        values: dict[str, object] = {
            name: int(fields[name], 0) for name in numeric
        }
        bool_values = {name: int(fields[name], 0) for name in booleans}
        if any(value not in (0, 1) for value in bool_values.values()):
            raise ValueError("link report booleans must be zero or one")
        raw_reads = tuple(int(value, 16) for value in fields["raw_reads"].split(","))
        send_drives = tuple(
            int(value, 16) for value in fields["assist_send_drives"].split(",")
        )
        if len(raw_reads) != 16 or any(not 0 <= value <= 0xFF for value in raw_reads):
            raise ValueError("raw-link vector must contain sixteen bytes")
        if len(send_drives) != 8 or any(not 0 <= value <= 3 for value in send_drives):
            raise ValueError("assist-send vector must contain eight line masks")
        values.update({name: bool(value) for name, value in bool_values.items()})
        return WabbitemuLinkReport(
            raw_reads=raw_reads,
            assist_send_drives=send_drives,
            **values,
        )
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native link report: {line.strip()}"
        ) from error


def parse_usb_report(line: str) -> WabbitemuUsbReport:
    """Parse one native Fake USB registration and handler edge report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    booleans = {
        "port4a_active",
        "port4c_active",
        "port4d_active",
        "port54_active",
        "port54_read_accepted",
        "port55_active",
        "port56_active",
        "port57_active",
        "port5b_active",
        "port80_active",
        "initial_line_interrupt",
        "initial_protocol_interrupt",
        "event_interrupt",
        "event_line_interrupt",
        "repeated_event_interrupt",
        "protocol_interrupt_enabled",
    }
    numeric = {
        "port54_read",
        "initial_port4a",
        "initial_port4c",
        "initial_port4d",
        "initial_port55",
        "initial_port56",
        "initial_port57",
        "initial_port5b",
        "initial_port80",
        "initial_line_state",
        "initial_events",
        "initial_event_mask",
        "initial_stored_port4a",
        "initial_stored_port4c",
        "initial_stored_port54",
        "mask_ff_read",
        "mask_zero_read",
        "event_line_state",
        "event_events",
        "event_port4a",
        "event_port4d",
        "event_port55",
        "event_port56",
        "repeated_events",
        "summary_none",
        "summary_line",
        "summary_protocol",
        "summary_both",
        "port5b_ff_read",
        "port80_ff_read",
        "stored_dev_address",
        "port4c_ff_read",
        "stored_port4c",
        "port4d_false_pair",
        "port4d_true_pair",
        "port4a_true_condition",
        "port4a_false_condition",
        "tstates",
    }
    required = {"mode", *booleans, *numeric}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native USB report omits " + ", ".join(missing)
        )
    if fields["mode"] != "usb-edge-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native USB mode {fields['mode']!r}"
        )
    try:
        values: dict[str, object] = {
            name: int(fields[name], 0) for name in numeric
        }
        bool_values = {name: int(fields[name], 0) for name in booleans}
        if any(value not in (0, 1) for value in bool_values.values()):
            raise ValueError("USB report booleans must be zero or one")
        values.update({name: bool(value) for name, value in bool_values.items()})
        return WabbitemuUsbReport(**values)
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native USB report: {line.strip()}"
        ) from error


def parse_mapper_report(line: str) -> WabbitemuMapperReport:
    """Parse one native mapper registration, selector, and overlay report."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    booleans = {
        "port04_active",
        "port05_active",
        "port06_active",
        "port07_active",
        "port0e_active",
        "port0f_active",
        "port27_active",
        "port28_active",
        "initial_boot_mapped",
        "initial_page0_changed",
        "initial_a_ram",
        "initial_b_ram",
        "initial_c_ram",
        "page0_changed_after_data_read",
        "page0_changed_after_opcode",
        "paired_boot_mapped",
        "paired_a_ram",
        "paired_b_ram",
        "paired_c_ram",
        "independent_fetch_halted",
        "paired_fetch_halted",
    }
    numeric = {
        "initial_port04_status",
        "initial_port05",
        "initial_port06",
        "initial_port07",
        "initial_port0e",
        "initial_port0f",
        "initial_port27",
        "initial_port28",
        "initial_fixed_page",
        "initial_a_page",
        "initial_b_page",
        "initial_c_page",
        "fixed_page_after_data_read",
        "fixed_page_after_opcode",
        "handoff_pc",
        "port05_ff_read",
        "port0e_ff_read",
        "port06_flash_read",
        "stored_port06_flash",
        "port0f_ff_read",
        "port07_flash_read",
        "stored_port07_flash",
        "port06_ram_ff_read",
        "stored_port06_ram",
        "port07_ram_fe_read",
        "stored_port07_ram",
        "paired_port04_status",
        "paired_port05",
        "paired_port06",
        "paired_port07",
        "paired_a_page",
        "paired_b_page",
        "paired_c_page",
        "port27_ff_read",
        "port28_one_read",
        "independent_8000",
        "independent_803f",
        "independent_8040",
        "independent_fb63",
        "independent_fb64",
        "independent_write_ram1",
        "independent_write_underlying_b",
        "independent_write_ram0",
        "independent_write_underlying_c",
        "paired_8000",
        "paired_803f",
        "paired_8040",
        "paired_fb63",
        "paired_fb64",
        "paired_write_ram1",
        "paired_write_underlying_b",
        "paired_write_ram0",
        "paired_write_underlying_c",
        "tstates",
    }
    required = {"mode", *booleans, *numeric}
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native mapper report omits " + ", ".join(missing)
        )
    if fields["mode"] != "mapper-edge-probe":
        raise WabbitemuHeadlessError(
            f"unexpected native mapper mode {fields['mode']!r}"
        )
    try:
        values: dict[str, object] = {
            name: int(fields[name], 0) for name in numeric
        }
        bool_values = {name: int(fields[name], 0) for name in booleans}
        if any(value not in (0, 1) for value in bool_values.values()):
            raise ValueError("mapper report booleans must be zero or one")
        values.update({name: bool(value) for name, value in bool_values.items()})
        return WabbitemuMapperReport(**values)
    except (TypeError, ValueError) as error:
        raise WabbitemuHeadlessError(
            f"invalid native mapper report: {line.strip()}"
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


def run_md5_edge_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuMd5EdgeReport:
    """Run native MD5 edge cases through the pinned Wabbitemu core."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect MD5 edge fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--md5-edge-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native MD5 edge probe failed: {detail}")
    report = parse_md5_edge_report(completed.stdout)
    return WabbitemuMd5EdgeReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_keypad_edge_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuKeypadReport:
    """Run native keypad matrix and ON-edge cases through Wabbitemu."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect keypad fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--keypad-edge-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native keypad probe failed: {detail}")
    report = parse_keypad_report(completed.stdout)
    return WabbitemuKeypadReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_timer_edge_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuTimerReport:
    """Run native programmable-timer and RTC edges through Wabbitemu."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect timer fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--timer-edge-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native timer probe failed: {detail}")
    report = parse_timer_report(completed.stdout)
    return WabbitemuTimerReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_asic_edge_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuAsicReport:
    """Run native ASIC-control edges through Wabbitemu."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect ASIC fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--asic-edge-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native ASIC probe failed: {detail}")
    report = parse_asic_report(completed.stdout)
    return WabbitemuAsicReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_speed_edge_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuSpeedReport:
    """Run native CPU-speed and delay-register edges through Wabbitemu."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect speed fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--speed-edge-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native speed probe failed: {detail}")
    report = parse_speed_report(completed.stdout)
    return WabbitemuSpeedReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_protection_port_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuProtectionPortReport:
    """Run native protected-boundary register edges through Wabbitemu."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect protection-port fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--protection-port-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(
            f"native protection-port probe failed: {detail}"
        )
    report = parse_protection_port_report(completed.stdout)
    return WabbitemuProtectionPortReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_reset_retention_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuResetReport:
    """Run low-level, frontend, and violation reset cases through Wabbitemu."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect reset fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--reset-retention-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(
            f"native reset-retention probe failed: {detail}"
        )
    report = parse_reset_report(completed.stdout)
    return WabbitemuResetReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_lcd_edge_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuLcdReport:
    """Run native LCD controller and bus-timing edges through Wabbitemu."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect LCD fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--lcd-edge-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native LCD probe failed: {detail}")
    report = parse_lcd_report(completed.stdout)
    return WabbitemuLcdReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_interrupt_edge_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuInterruptReport:
    """Run native standard-interrupt and low-power edges through Wabbitemu."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect interrupt fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--interrupt-edge-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native interrupt probe failed: {detail}")
    report = parse_interrupt_report(completed.stdout)
    return WabbitemuInterruptReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_link_edge_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuLinkReport:
    """Run native raw-link and link-assist edges through Wabbitemu."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect link fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--link-edge-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native link probe failed: {detail}")
    report = parse_link_report(completed.stdout)
    return WabbitemuLinkReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_usb_edge_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuUsbReport:
    """Run native Fake USB registration and handler edges through Wabbitemu."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect USB fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--usb-edge-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native USB probe failed: {detail}")
    report = parse_usb_report(completed.stdout)
    return WabbitemuUsbReport(
        **{
            **report.to_dict(),
            "source_rom_sha256": file_sha256(source_rom),
            "binary_sha256": file_sha256(binary),
        }
    )


def run_mapper_edge_probe(
    binary: Path,
    source_rom: Path,
) -> WabbitemuMapperReport:
    """Run native mapper registration, selector, and overlay edges."""

    try:
        rom_size = source_rom.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(
            f"cannot inspect mapper fixture: {error}"
        ) from error
    if rom_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"source ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{rom_size:X}"
        )
    command = [str(binary), "--mapper-edge-probe", str(source_rom)]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native mapper probe failed: {detail}")
    report = parse_mapper_report(completed.stdout)
    return WabbitemuMapperReport(
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
