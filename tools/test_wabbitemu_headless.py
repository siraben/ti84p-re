#!/usr/bin/env python3
"""Regression tests for the pinned Wabbitemu headless adapter."""

from pathlib import Path
import unittest

from wabbitemu_headless import (
    COMPILE_SOURCES,
    WabbitemuHeadlessError,
    build_command,
    parse_execution_report,
    parse_flash_command_report,
    parse_flash_program_report,
    parse_flash_worker_report,
    parse_gate_transition,
    parse_gate_write,
    parse_ram_execution_report,
    parse_run_report,
    validate_retail_flash_path,
)


class WabbitemuHeadlessTests(unittest.TestCase):
    def test_build_command_keeps_portability_shims_and_pinned_units_explicit(self):
        source = Path("/source/wabbitemu")
        command = build_command(
            source,
            Path("tools/wabbitemu_headless.cpp"),
            Path("/tmp/wabbitemu-headless"),
            cxx="c++",
        )

        self.assertEqual("c++", command[0])
        self.assertIn("-D_LINUX", command)
        self.assertIn("-D__pragma(x)=", command)
        self.assertEqual(
            [str(source / relative) for relative in COMPILE_SOURCES],
            [item for item in command if item.startswith(str(source)) and item.endswith(".c")],
        )
        self.assertEqual(["-lm", "-o", "/tmp/wabbitemu-headless"], command[-3:])

    def test_parses_native_status_without_treating_pc_as_decimal(self):
        report = parse_run_report(
            "steps=20000000 tstates=239914310 pc=0x03A5 halted=1 "
            "changed_bytes=74 input_fnv1a64=be3f4298bf704659 "
            "output_fnv1a64=3a55a4a28ab5f67b wake=pressed-released "
            "settled=yes visits=3C:7BC7,3C:7C1F,3C:7C43,3C:7D30 "
            "gate_writes=3C:7228:01:1>0,3C:66E2:00:0>1 "
            "gate_transitions=3C:7228:1>0,3C:66E2:0>1 "
            "unlocked_write_bcall_visits=2 unlocked_erase_bcall_visits=0 "
            "unlocked_program_worker_entry_visits=2 "
            "unlocked_program_write_visits=74 "
            "unlocked_program_success_reset_visits=2 "
            "unlocked_program_failure_reset_visits=0\n"
        )

        self.assertEqual(0x03A5, report.pc)
        self.assertEqual(74, report.changed_bytes)
        self.assertTrue(report.halted)
        self.assertTrue(report.settled)
        self.assertEqual(("3C:7BC7", "3C:7C1F", "3C:7C43", "3C:7D30"), report.visits)
        self.assertEqual(
            ("3C:7228:1>0", "3C:66E2:0>1"),
            tuple(event.native_text() for event in report.gate_transitions),
        )
        self.assertEqual(
            ("3C:7228:01:1>0", "3C:66E2:00:0>1"),
            tuple(event.native_text() for event in report.gate_writes),
        )
        self.assertEqual(2, report.unlocked_write_bcall_visits)
        self.assertEqual(74, report.unlocked_program_write_visits)

    def test_parses_typed_gate_events_for_flash_and_ram(self):
        write = parse_gate_write("3D:60A6:01:1>0")
        transition = parse_gate_transition("RAM:01:8100:0>1")

        self.assertEqual((0x3D, 0x60A6, 1), (write.page, write.address, write.value))
        self.assertFalse(write.ram)
        self.assertEqual("RAM:01:8100:0>1", transition.native_text())
        self.assertTrue(transition.ram)

    def test_validates_complete_retail_flash_path(self):
        report = parse_run_report(
            "steps=1 tstates=1 pc=0 halted=0 changed_bytes=1 "
            "input_fnv1a64=0 output_fnv1a64=1 wake=pressed-released "
            "settled=yes visits=- "
            "gate_writes=3D:60A6:01:1>0,3D:5CEF:00:0>1 "
            "gate_transitions=3D:60A6:1>0,3D:5CEF:0>1 "
            "unlocked_write_bcall_visits=2 unlocked_erase_bcall_visits=1 "
            "unlocked_program_worker_entry_visits=2 "
            "unlocked_program_write_visits=3 "
            "unlocked_program_success_reset_visits=2 "
            "unlocked_program_failure_reset_visits=0"
        )

        validate_retail_flash_path(report)

    def test_rejects_incomplete_retail_flash_path(self):
        report = parse_run_report(
            "steps=1 tstates=1 pc=0 halted=0 changed_bytes=0 "
            "input_fnv1a64=0 output_fnv1a64=0 wake=pressed-released "
            "settled=yes visits=- gate_writes=- gate_transitions=- "
            "unlocked_write_bcall_visits=0 unlocked_erase_bcall_visits=0 "
            "unlocked_program_worker_entry_visits=0 "
            "unlocked_program_write_visits=0 "
            "unlocked_program_success_reset_visits=0 "
            "unlocked_program_failure_reset_visits=0"
        )

        with self.assertRaisesRegex(WabbitemuHeadlessError, "unlock and relock"):
            validate_retail_flash_path(report)

    def test_rejects_incomplete_native_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_run_report("steps=1 settled=no")

    def test_parses_guarded_execution_status(self):
        report = parse_execution_report(
            "mode=execution-probe page=0x08 boot_steps=1234 "
            "boot_tstates=5678 boot_pc=0x4208 boot_page=3F "
            "flash_locked=1 flash_lower=0x08 flash_upper=0x29 "
            "ram_lower=0x4000 ram_upper=0x83FF ram_mode=0 "
            "injected_page=0x01 injected_address=0x9D95 probe_size=75 "
            "call_address=0x9DBD return_address=0x9DC0 probe_steps=32 "
            "call_visits=1 target_visits=1 target_followup_visits=0 "
            "return_visits=0 violation_resets=1 marker=0xA0 "
            "classification=violation-reset\n"
        )

        self.assertEqual(0x08, report.page)
        self.assertEqual(0x9DBD, report.call_address)
        self.assertEqual("3F", report.boot_page)
        self.assertTrue(report.flash_locked)
        self.assertEqual("violation-reset", report.classification)
        self.assertEqual(1, report.violation_resets)

    def test_rejects_wrong_or_incomplete_execution_mode(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "unexpected"):
            parse_execution_report(
                "mode=recovery page=0 boot_steps=0 boot_tstates=0 boot_pc=0 "
                "boot_page=0 flash_locked=0 flash_lower=0 flash_upper=0 "
                "ram_lower=0 ram_upper=0 ram_mode=0 injected_page=0 "
                "injected_address=0 probe_size=1 call_address=0 return_address=0 "
                "probe_steps=0 call_visits=0 target_visits=0 "
                "target_followup_visits=0 return_visits=0 violation_resets=0 "
                "marker=0 classification=indeterminate"
            )
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_execution_report("mode=execution-probe page=0x08")

    def test_parses_native_flash_program_status(self):
        report = parse_flash_program_report(
            "mode=flash-program-probe target_page=0x08 target_offset=0x0100 "
            "target_address=0x4100 target_physical=0x20100 "
            "original_rom_byte=0xFF initial=0x50 requested=0xD0 "
            "configured_flash_locked=0 initial_toggle=0x00 command_writes=4 "
            "stored=0x50 step_after_write=read error_after_write=1 "
            "toggle_after_write=0x00 first_read=0x20 error_after_first=0 "
            "toggle_after_first=0x40 second_read=0x50 error_after_second=0 "
            "toggle_after_second=0x40 tstates=0\n"
        )

        self.assertEqual(0x20100, report.target_physical)
        self.assertEqual(0x50, report.stored)
        self.assertTrue(report.error_after_write)
        self.assertEqual((0x20, 0x50), (report.first_read, report.second_read))

    def test_rejects_incomplete_flash_program_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_flash_program_report(
                "mode=flash-program-probe target_page=0x08"
            )

    def test_parses_native_flash_command_status(self):
        report = parse_flash_command_report(
            "mode=flash-command-probe flash_size=0x100000 flash_version=3 "
            "configured_flash_locked=0 initial_step=read "
            "autoselect_entry_step=autoselect autoselect_maker=0x01 "
            "autoselect_device=0xDA autoselect_protection=0x00 "
            "autoselect_reset_step=read autoselect_array_byte=0xFF "
            "partial_step_before_reset=aa partial_reset_step=read "
            "cfi_step=read cfi_changed_bytes=0 suspend_window_step=erase-55 "
            "suspend_step=read suspend_changed_bytes=0 resume_step=read "
            "resume_changed_bytes=0 fast_entry_step=fast "
            "fast_first_select_step=fast-program fast_first_initial=0xF0 "
            "fast_first_requested=0x50 fast_first_stored=0x50 "
            "fast_after_first_step=fast fast_second_select_step=fast-program "
            "fast_second_initial=0xAA fast_second_requested=0xA0 "
            "fast_second_stored=0xA0 fast_after_second_step=fast "
            "fast_exit_select_step=fast-exit fast_exit_step=read "
            "sector_target_page=0x08 sector_target_address=0x4100 "
            "sector_start=0x20000 sector_size=0x10000 sector_step=read "
            "sector_erased_bytes=65536 sector_changed_bytes=65536 "
            "sector_outside_changed_bytes=0 chip_step=read "
            "chip_non_ff_before=322043 chip_non_ff_after=0 "
            "chip_changed_bytes=322043 chip_boot_before=0x00 "
            "chip_boot_after=0xFF tstates=0\n"
        )

        self.assertEqual((0x01, 0xDA, 0), (
            report.autoselect_maker,
            report.autoselect_device,
            report.autoselect_protection,
        ))
        self.assertEqual(0x10000, report.sector_changed_bytes)
        self.assertEqual(report.chip_non_ff_before, report.chip_changed_bytes)

    def test_rejects_incomplete_flash_command_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_flash_command_report(
                "mode=flash-command-probe flash_size=0x100000"
            )

    def test_parses_native_flash_worker_status(self):
        report = parse_flash_worker_report(
            "mode=flash-worker-probe target_page=0x08 target_offset=0x0100 "
            "target_address=0x4100 target_physical=0x20100 "
            "original_rom_byte=0xFF initial=0x50 requested=0xD0 "
            "initial_toggle=0x00 boot_steps=134845 boot_tstates=1746999 "
            "boot_pc=0x4223 boot_page=3F boot_flash_locked=1 "
            "boot_flash_lower=0x08 boot_flash_upper=0x29 "
            "configured_flash_locked=0 source_page=0x01 "
            "source_address=0x9D99 harness_size=4 return_address=0x9D98 "
            "max_probe_steps=10000 probe_steps=347 probe_tstates=5379 "
            "bcall_visits=1 worker_entry_visits=1 program_write_visits=1 "
            "dq7_read_visits=1 final_dq7_read_visits=1 "
            "success_reset_visits=0 failure_reset_visits=1 return_visits=1 "
            "violation_resets=0 poll_reads=20,50 stored=0x50 "
            "flash_step=read flash_error=0 flash_toggle=0x40 "
            "return_af=0x3F2C return_bc=0x0000 return_de=0x4100 "
            "return_hl=0x9D99 port06=0x3F bank1_page=3F "
            "final_pc=0x9D98 classification=failure\n"
        )

        self.assertEqual((0x20, 0x50), report.poll_reads)
        self.assertEqual(0x3F2C, report.return_af)
        self.assertEqual("failure", report.classification)

    def test_rejects_incomplete_flash_worker_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_flash_worker_report(
                "mode=flash-worker-probe target_page=0x08"
            )

    def test_parses_guarded_ram_execution_status(self):
        report = parse_ram_execution_report(
            "mode=ram-execution-probe target_page=0x05 target_offset=0x3FF0 "
            "target_address=0x7FF0 target_physical=0x17FF0 "
            "boot_steps=134845 boot_tstates=1746999 boot_pc=0x4223 "
            "boot_page=3F boot_ram_lower=0x4000 boot_ram_upper=0x83FF "
            "boot_ram_mode=0 configured_lower_chunk=0x10 "
            "configured_upper_chunk=0x20 configured_ram_lower=0x4000 "
            "configured_ram_upper=0x83FF configured_ram_mode=1 "
            "source_page=0x01 source_address=0x9D95 probe_size=42 "
            "call_address=0x9DB2 return_address=0x9DB5 probe_steps=31 "
            "call_visits=1 target_visits=1 target_followup_visits=0 "
            "return_visits=0 violation_resets=1 expected_marker=0x4D "
            "marker=0xA0 classification=violation-reset\n"
        )

        self.assertEqual(5, report.target_page)
        self.assertEqual(0x17FF0, report.target_physical)
        self.assertEqual(1, report.configured_ram_mode)
        self.assertEqual("violation-reset", report.classification)

    def test_rejects_incomplete_ram_execution_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_ram_execution_report(
                "mode=ram-execution-probe target_page=0x05"
            )


if __name__ == "__main__":
    unittest.main()
