#!/usr/bin/env python3
"""Regression tests for reusable native Wabbitemu Flash-probe oracles."""

import unittest

from wabbitemu_flash_probe import (
    FlashProgramCase,
    parse_flash_program_case,
    validate_command_report,
    validate_failure_fixture_target,
    validate_flash_preflight_report,
    validate_worker_report,
)
from wabbitemu_headless import (
    WabbitemuFlashCommandReport,
    WabbitemuFlashPreflightReport,
    WabbitemuFlashWorkerReport,
    WabbitemuHeadlessError,
    parse_flash_preflight_report,
)


PREFLIGHT_NATIVE_REPORT = " ".join(
    (
        "mode=flash-preflight-probe status=0 preflight_address=0x02BF",
        "failure_address=0x02CE reset_address=0x0000 configured_sp=0xBFFE",
        "signature_size=18 source_signature_match=1 mapped_signature_match=1",
        "boot_steps=134845 boot_tstates=1746999 boot_pc=0x4223 boot_page=3F",
        "boot_flash_locked=1 max_probe_steps=10000 probe_steps=9",
        "harness_visits=1 preflight_visits=1 failure_visits=1 reset_visits=1",
        "return_visits=0 violation_resets=0 gate_locked_before_restart=1",
        "step_before_restart=read flash_changed_before_restart=0",
        "restart_reset_pc=0x0000 max_restart_steps=5000000",
        "restart_steps=134845 restart_tstates=1746999 restart_pc=0x4223",
        "restart_page=3F restart_ready=1 flash_changed_after_restart=0",
    )
)


def command_report(**changes) -> WabbitemuFlashCommandReport:
    values = {
        "flash_size": 0x100000,
        "flash_version": 3,
        "configured_flash_locked": False,
        "initial_step": "read",
        "autoselect_entry_step": "autoselect",
        "autoselect_maker": 1,
        "autoselect_device": 0xDA,
        "autoselect_protection": 0,
        "autoselect_reset_step": "read",
        "autoselect_array_byte": 0xFF,
        "partial_step_before_reset": "aa",
        "partial_reset_step": "read",
        "cfi_step": "read",
        "cfi_changed_bytes": 0,
        "suspend_window_step": "erase-55",
        "suspend_step": "read",
        "suspend_changed_bytes": 0,
        "resume_step": "read",
        "resume_changed_bytes": 0,
        "fast_entry_step": "fast",
        "fast_first_select_step": "fast-program",
        "fast_first_initial": 0xF0,
        "fast_first_requested": 0x50,
        "fast_first_stored": 0x50,
        "fast_after_first_step": "fast",
        "fast_second_select_step": "fast-program",
        "fast_second_initial": 0xAA,
        "fast_second_requested": 0xA0,
        "fast_second_stored": 0xA0,
        "fast_after_second_step": "fast",
        "fast_exit_select_step": "fast-exit",
        "fast_exit_step": "read",
        "sector_target_page": 0x08,
        "sector_target_address": 0x4100,
        "sector_start": 0x20000,
        "sector_size": 0x10000,
        "sector_step": "read",
        "sector_erased_bytes": 0x10000,
        "sector_changed_bytes": 0x10000,
        "sector_outside_changed_bytes": 0,
        "chip_step": "read",
        "chip_non_ff_before": 322_043,
        "chip_non_ff_after": 0,
        "chip_changed_bytes": 322_043,
        "chip_boot_before": 0,
        "chip_boot_after": 0xFF,
        "tstates": 0,
    }
    values.update(changes)
    return WabbitemuFlashCommandReport(**values)


def worker_report(**changes) -> WabbitemuFlashWorkerReport:
    values = {
        "target_page": 0x08,
        "target_offset": 0x0100,
        "target_address": 0x4100,
        "target_physical": 0x20100,
        "original_rom_byte": 0xFF,
        "initial": 0x50,
        "requested": 0xD0,
        "initial_toggle": 0,
        "boot_steps": 134_845,
        "boot_tstates": 1_746_999,
        "boot_pc": 0x4223,
        "boot_page": "3F",
        "boot_flash_locked": True,
        "boot_flash_lower": 0x08,
        "boot_flash_upper": 0x29,
        "configured_flash_locked": False,
        "source_page": 1,
        "source_address": 0x9D99,
        "harness_size": 4,
        "return_address": 0x9D98,
        "max_probe_steps": 10_000,
        "probe_steps": 347,
        "probe_tstates": 5_379,
        "bcall_visits": 1,
        "worker_entry_visits": 1,
        "program_write_visits": 1,
        "dq7_read_visits": 1,
        "final_dq7_read_visits": 1,
        "success_reset_visits": 0,
        "failure_reset_visits": 1,
        "return_visits": 1,
        "violation_resets": 0,
        "poll_reads": (0x20, 0x50),
        "stored": 0x50,
        "flash_step": "read",
        "flash_error": False,
        "flash_toggle": 0x40,
        "return_af": 0x3F2C,
        "return_bc": 0,
        "return_de": 0x4100,
        "return_hl": 0x9D99,
        "port06": 0x3F,
        "bank1_page": "3F",
        "flash_changed_bytes": 1,
        "target_sector_changed_bytes": 1,
        "protected_changed_bytes": 0,
        "outside_target_changed_bytes": 0,
        "final_pc": 0x9D98,
        "classification": "failure",
    }
    values.update(changes)
    return WabbitemuFlashWorkerReport(**values)


def preflight_report(**changes) -> WabbitemuFlashPreflightReport:
    values = {
        "status": 0,
        "preflight_address": 0x02BF,
        "failure_address": 0x02CE,
        "reset_address": 0,
        "configured_sp": 0xBFFE,
        "signature_size": 18,
        "source_signature_match": True,
        "mapped_signature_match": True,
        "boot_steps": 134_845,
        "boot_tstates": 1_746_999,
        "boot_pc": 0x4223,
        "boot_page": "3F",
        "boot_flash_locked": True,
        "max_probe_steps": 10_000,
        "probe_steps": 9,
        "harness_visits": 1,
        "preflight_visits": 1,
        "failure_visits": 1,
        "reset_visits": 1,
        "return_visits": 0,
        "violation_resets": 0,
        "gate_locked_before_restart": True,
        "step_before_restart": "read",
        "flash_changed_before_restart": 0,
        "restart_reset_pc": 0,
        "max_restart_steps": 5_000_000,
        "restart_steps": 134_845,
        "restart_tstates": 1_746_999,
        "restart_pc": 0x4223,
        "restart_page": "3F",
        "restart_ready": True,
        "flash_changed_after_restart": 0,
    }
    values.update(changes)
    return WabbitemuFlashPreflightReport(**values)


class WabbitemuFlashProbeTests(unittest.TestCase):
    def test_shared_case_parser_accepts_optional_toggle(self):
        self.assertEqual(
            FlashProgramCase(0x50, 0xD0, 0x40),
            parse_flash_program_case("0x50:0xD0:0x40"),
        )

    def test_command_oracle_validates_all_command_families(self):
        result = validate_command_report(command_report())

        self.assertEqual([0x01, 0xDA], result["source_model"]["autoselect_ids"])
        self.assertTrue(result["source_model"]["chip_erase_fills_complete_array"])

    def test_command_oracle_rejects_outside_sector_mutation(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_command_report(command_report(sector_outside_changed_bytes=1))

    def test_worker_oracle_validates_illegal_dq7_failure(self):
        result = validate_worker_report(
            FlashProgramCase(0x50, 0xD0),
            worker_report(),
        )

        self.assertEqual("failure", result["source_model"]["outcome"])
        self.assertEqual([0x20, 0x50], result["source_model"]["reads"])

    def test_worker_oracle_validates_illegal_lower_bit_success(self):
        result = validate_worker_report(
            FlashProgramCase(0x00, 0x01),
            worker_report(
                initial=0x00,
                requested=0x01,
                probe_steps=355,
                probe_tstates=5_425,
                success_reset_visits=1,
                failure_reset_visits=0,
                poll_reads=(0xA0, 0x00),
                stored=0x00,
                return_af=0x0044,
                return_de=0x4101,
                return_hl=0x9D9A,
                classification="success",
            ),
        )

        self.assertEqual("success", result["source_model"]["outcome"])

    def test_worker_oracle_rejects_wrong_return_path(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_worker_report(
                FlashProgramCase(0x50, 0xD0),
                worker_report(classification="success"),
            )

    def test_worker_oracle_allows_a_no_change_control(self):
        result = validate_worker_report(
            FlashProgramCase(0xFF, 0xFF),
            worker_report(
                initial=0xFF,
                requested=0xFF,
                probe_steps=348,
                probe_tstates=5_375,
                final_dq7_read_visits=0,
                success_reset_visits=1,
                failure_reset_visits=0,
                poll_reads=(0xFF,),
                stored=0xFF,
                flash_toggle=0,
                return_af=0x0044,
                return_de=0x4101,
                return_hl=0x9D9A,
                flash_changed_bytes=0,
                target_sector_changed_bytes=0,
                classification="success",
            ),
        )

        self.assertEqual(0, result["native"]["flash_changed_bytes"])

    def test_worker_oracle_requires_return_before_bound(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "step bound"):
            validate_worker_report(
                FlashProgramCase(0x50, 0xD0),
                worker_report(max_probe_steps=347),
            )

    def test_failure_target_guard_accepts_only_fixed_archive_sector(self):
        result = validate_failure_fixture_target(0x08, 0x0100, 0x20100)

        self.assertEqual([0x20000, 0x30000], result["sector"])
        self.assertFalse(result["source_image_written"])

    def test_failure_target_guard_rejects_certificate_page(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "fixed disposable"):
            validate_failure_fixture_target(0x3E, 0x0100, 0xF8100)

    def test_preflight_parser_and_oracle_require_numeric_zero_status(self):
        parsed = parse_flash_preflight_report(PREFLIGHT_NATIVE_REPORT)
        result = validate_flash_preflight_report(parsed)

        self.assertEqual(0, result["numeric_status"])
        self.assertEqual(0, result["source_model"]["flash_changes"])

    def test_preflight_oracle_rejects_no_restart_progress(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_flash_preflight_report(preflight_report(restart_steps=0))


if __name__ == "__main__":
    unittest.main()
