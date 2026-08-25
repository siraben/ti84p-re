#!/usr/bin/env python3
"""Regression tests for the pinned Wabbitemu headless adapter."""

import unittest
from pathlib import Path

from ti84re.emulators.wabbitemu.headless import (
    COMPILE_SOURCES,
    WabbitemuHeadlessError,
    build_command,
    parse_asic_report,
    parse_execution_report,
    parse_flash_command_report,
    parse_flash_program_report,
    parse_flash_worker_report,
    parse_gate_transition,
    parse_gate_write,
    parse_interrupt_report,
    parse_keypad_report,
    parse_lcd_report,
    parse_link_report,
    parse_mapper_report,
    parse_md5_edge_report,
    parse_prefix_m1_report,
    parse_protection_port_report,
    parse_ram_execution_report,
    parse_run_report,
    parse_speed_report,
    parse_timer_physical_report,
    parse_timer_report,
    parse_usb_report,
    parse_usb_rom_case_report,
    parse_usb_rom_receive_report,
    parse_usb_rom_reports,
    validate_retail_flash_path,
)
from ti84re.emulators.wabbitemu.mapper_probe import expected_mapper_values


class WabbitemuHeadlessTests(unittest.TestCase):
    def test_build_command_keeps_portability_shims_and_pinned_units_explicit(self):
        source = Path("/source/wabbitemu")
        command = build_command(
            source,
            Path("tools/probes/wabbitemu/wabbitemu_headless.cpp"),
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

    def test_parses_native_md5_edge_status(self):
        report = parse_md5_edge_report(
            "mode=md5-edge-probe reset_operand_reads=00,00,00,00 "
            "reset_result=0x00000000 one_write_result=0x11000000 "
            "three_write_result=0x33221100 four_write_result=0x44332211 "
            "five_write_result=0x55443322 raw_shift=0xFF raw_mode=0xFF "
            "masked_control_result=0x00000004 "
            "loaded_operand_reads=00,00,00,00 "
            "before_mutation_result=0xD6D117B4 "
            "after_mutation_result=0x343F9701 mixed_result=0x343F97B4 "
            "tstates=0\n"
        )

        self.assertEqual((0, 0, 0, 0), report.reset_operand_reads)
        self.assertEqual(0x55443322, report.five_write_result)
        self.assertEqual(0x343F97B4, report.mixed_result)

    def test_rejects_incomplete_md5_edge_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_md5_edge_report("mode=md5-edge-probe reset_result=0")

    def test_parses_native_keypad_status(self):
        report = parse_keypad_report(
            "mode=keypad-edge-probe single_mask=0xFE single_read=0xFE "
            "same_column_mask=0xFC same_column_read=0xFE "
            "rectangle_mask=0xFE rectangle_read=0xFC "
            "transitive_mask=0xFE transitive_read=0xFC "
            "unwired_mask=0x7F unwired_read=0xFF "
            "on_initial_status=0x08 on_enabled_status=0x08 "
            "on_press_before_eval=0x00 on_press_after_eval=0x01 "
            "on_held_after_ack=0x00 on_held_after_eval=0x00 "
            "on_release_before_eval=0x08 on_release_after_eval=0x08 "
            "on_second_press_before_eval=0x00 "
            "on_second_press_after_eval=0x01 tstates=0\n"
        )

        self.assertEqual(0xFC, report.transitive_read)
        self.assertEqual(0xFF, report.unwired_read)
        self.assertEqual(0x01, report.on_second_press_after_eval)

    def test_rejects_incomplete_keypad_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_keypad_report("mode=keypad-edge-probe single_read=0xFE")

    def test_parses_native_timer_status(self):
        report = parse_timer_report(
            "mode=timer-edge-probe crystal_source=0x41 crystal_divisor=32 "
            "crystal_elapsed_ticks=320 crystal_reads=02,01,03 "
            "crystal_status=0x04 crystal_port4=0x28 cpu_source=0x80 "
            "cpu_divisor=1 cpu_elapsed_tstates=4 cpu_count_read=0x03 "
            "cpu_status=0x04 cpu_port4=0x28 zero_elapsed_tstates=257 "
            "zero_count_read=0x00 zero_status=0x04 zero_port4=0x28 "
            "acknowledged_status=0x00 acknowledged_port4=0x08 "
            "halted_count_read=0x01 halted_status=0x06 "
            "interrupt_while_halted=0 interrupt_after_resume=1 "
            "rtc_initial=0x00000000 rtc_committed=0x12345678 "
            "rtc_running=0x12345682 rtc_frozen=0x12345682 "
            "rtc_late_disabled=0x12345682 final_elapsed=100\n"
        )

        self.assertEqual((2, 1, 3), report.crystal_reads)
        self.assertEqual(0x04, report.zero_status)
        self.assertFalse(report.interrupt_while_halted)
        self.assertTrue(report.interrupt_after_resume)

    def test_rejects_incomplete_timer_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_timer_report("mode=timer-edge-probe crystal_divisor=32")

    def test_parses_native_asic_status(self):
        report = parse_asic_report(
            "mode=asic-edge-probe initial_flash_locked=1 "
            "port02_locked=0xE3 port02_unlocked=0xE7 "
            "port15_ram_v0=0x44 port15_ram_v2=0x55 "
            "port39_active=0 port39_read_accepted=0 port39_read=0xFF "
            "port3a_active=1 port3a_initial=0x00 "
            "port3a_first_written=0xA5 port3a_first_read=0xA5 "
            "port3a_second_written=0x5A port3a_second_read=0x5A "
            "port21_active=1 port21_protected=1 locked_write_accepted=0 "
            "locked_read=0x00 locked_internal_mode=0 locked_model_bits=0 "
            "mode3_write_accepted=1 mode3_written=0x30 mode3_read=0x00 "
            "mode3_internal_mode=3 mode3_model_bits=0 "
            "group3_write_accepted=1 group3_written=0x03 group3_read=0x03 "
            "group3_internal_mode=0 group3_model_bits=3 "
            "combined_write_accepted=1 combined_written=0x33 "
            "combined_read=0x03 combined_internal_mode=3 "
            "combined_model_bits=3 tstates=0\n"
        )

        self.assertEqual(0x44, report.port15_ram_v0)
        self.assertFalse(report.port39_active)
        self.assertEqual(3, report.combined_internal_mode)
        self.assertEqual(0x03, report.combined_read)

    def test_rejects_incomplete_asic_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_asic_report("mode=asic-edge-probe port02_locked=0xE3")

    def test_parses_native_lcd_status(self):
        report = parse_lcd_report(
            "mode=lcd-edge-probe configured_lcd_delay=60 "
            "port12_active=0 port12_read_accepted=0 port12_read=0xFF "
            "port13_active=0 port13_read_accepted=0 port13_read=0xFF "
            "early_status=0x80 boundary_status=0x23 status_last_tstate=60 "
            "early_write_cell=0x00 early_write_column=0 "
            "wrap_column14=0xA0 wrap_column15=0x00 wrap_column0=0xA1 "
            "wrap_column1=0xA2 wrap_column2=0xA3 wrap_final_column=3 "
            "direct_column15=0xB5 alias_column31=0xBF alias_final_column=0 "
            "latch_reads=00,12,34 latch_read_tstates=1380 "
            "latch_last_tstate=1320 latch_final_column=3 "
            "ready_field=3 ready_hold=240 ready_last_tstate=2000 "
            "ready_at_240=0xE1 ready_at_241=0xE3 "
            "accepted_status_read=0x63 ready_after_read_last_tstate=2000 "
            "ready_after_read=0xE3 delay_register=0x27 delay_before=3000 "
            "delay_after=3009 delayed_status=0x63 "
            "flash_opcode_wait=1 flash_read_wait=0 flash_write_wait=1 "
            "ram_opcode_wait=0 ram_read_wait=0 ram_write_wait=1 "
            "requested_speed=3 clamped_speed=1 timer_version=0\n"
        )

        self.assertEqual(0x23, report.boundary_status)
        self.assertEqual((0, 0x12, 0x34), report.latch_reads)
        self.assertFalse(report.port12_active)
        self.assertTrue(report.flash_opcode_wait)

    def test_rejects_incomplete_lcd_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_lcd_report("mode=lcd-edge-probe configured_lcd_delay=60")

    def test_parses_native_speed_status(self):
        report = parse_speed_report(
            "mode=speed-edge-probe port20_active=1 "
            "delay_ports_active=1,1,1,1,1,1,1 "
            "reset_speed=0 reset_frequency=6000000 reset_timer_version=0 "
            "reset_delay_reads=00,00,00,00,00,00,00 "
            "default_speed_reads=0,1,1,1 "
            "default_frequencies=6000000,15000000,15000000,15000000 "
            "extra_speed_reads=0,1,2,3 "
            "extra_frequencies=6000000,15000000,20000000,25000000 "
            "latch_written=A9,AA,AB,AC,AD,AE,AF "
            "latch_reads=A9,AA,AB,AC,AD,AE,AF "
            "wait_masks=00,07,38,3F "
            "port2d_written=0x5A port2d_read=0x5A "
            "port2d_wait_unchanged=1 port2d_freq_unchanged=1 "
            "port2d_timer_version_unchanged=1 port2d_xtal_unchanged=1 "
            "port2d_lcd_active_unchanged=1 port2d_halt_unchanged=1 "
            "port2d_interrupt_unchanged=1 port2d_tstates_unchanged=1 "
            "tstates=0\n"
        )

        self.assertEqual((0, 1, 1, 1), report.default_speed_reads)
        self.assertEqual((0x00, 0x07, 0x38, 0x3F), report.wait_masks)
        self.assertTrue(report.port2d_xtal_unchanged)

    def test_rejects_incomplete_speed_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_speed_report("mode=speed-edge-probe port20_active=1")

    def test_parses_native_protection_port_status(self):
        report = parse_protection_port_report(
            "mode=protection-port-probe "
            "port_active=1,1,1,1,1 port_protected=1,1,1,1,1 "
            "initial_flash_locked=1 initial_reads=10,30,00,00,00 "
            "initial_flash_lower=0x0010 initial_flash_upper=0x0030 "
            "initial_port24=0x00 initial_ram_lower=0x0000 "
            "initial_ram_upper=0x03FF locked_write_accepted=0,0,0,0,0 "
            "locked_reads=10,30,00,00,00 configured_flash_locked=0 "
            "seeded_flash_lower=0x01A5 seeded_flash_upper=0x02B6 "
            "low_writes=CC,DD low_write_reads=CC,DD "
            "low_write_flash_lower=0x01CC low_write_flash_upper=0x02DD "
            "port24_written=0xFF port24_read=0xFF "
            "port24_flash_lower=0x00CC port24_flash_upper=0x00DD "
            "wrap_values=3F,40,41,FF ram_lower_reads=3F,00,01,3F "
            "ram_lower_internal=FC00,0000,0400,FC00 "
            "ram_upper_reads=3F,00,01,3F "
            "ram_upper_internal=FFFF,03FF,07FF,FFFF tstates=0\n"
        )

        self.assertEqual((False,) * 5, report.locked_write_accepted)
        self.assertEqual((0xCC, 0xDD), report.low_write_reads)
        self.assertEqual((0xFFFF, 0x03FF, 0x07FF, 0xFFFF), report.ram_upper_internal)

    def test_rejects_incomplete_protection_port_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_protection_port_report(
                "mode=protection-port-probe port_active=1,1,1,1,1"
            )

    def test_parses_native_interrupt_status(self):
        report = parse_interrupt_report(
            "mode=interrupt-edge-probe initial_mask=0x00 stored_mask=0xFF "
            "on_latch_before_ack=1 on_latch_after_ack=0 "
            "mask_after_on_ack=0xFE rate0_timer1_ns=1953125 "
            "rate1_timer1_ns=4405286 rate2_timer1_ns=6329114 "
            "rate3_timer1_ns=9259259 rate3_timer2_ns=4629630 "
            "rate3_timer2_offset_ns=2314815 exact_boundary_status=0x08 "
            "exact_boundary_interrupt=0 after_boundary_status=0x0A "
            "after_boundary_interrupt=1 after_port3_ack_status=0x08 "
            "before_port2_ack_status=0x0A after_port2_ack_status=0x08 "
            "completion_status=0xE8 "
            "low_power_lcd_active=0 restored_lcd_active=1 tstates=0\n"
        )

        self.assertEqual(0xFF, report.stored_mask)
        self.assertEqual(9_259_259, report.rate3_timer1_ns)
        self.assertFalse(report.exact_boundary_interrupt)
        self.assertTrue(report.after_boundary_interrupt)

    def test_rejects_incomplete_interrupt_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_interrupt_report("mode=interrupt-edge-probe initial_mask=0")

    def test_parses_native_link_status(self):
        report = parse_link_report(
            "mode=link-edge-probe port08_active=1 port09_active=1 "
            "port0a_active=1 port0b_active=0 port0b_read_accepted=0 "
            "port0b_read=0xFF port0c_active=0 port0c_read_accepted=0 "
            "port0c_read=0xFF port0d_active=1 initial_enable=0x80 "
            "initial_status=0x00 initial_in=0x00 initial_out=0x00 "
            "raw_reads=03,02,01,00,12,12,10,10,21,20,21,20,30,30,30,30 "
            "raw_high_write=0x21 raw_peer_read=0x02 raw_peer_interrupt=0 "
            "idle_ready_status=0x22 idle_ready_interrupt=1 "
            "idle_after_out_status=0x00 "
            "assist_send_drives=02,01,02,01,01,02,01,02 "
            "assist_send_status=0x22 assist_send_interrupt=1 "
            "assist_send_out=0xA5 assist_send_after_out_status=0x00 "
            "assist_receive_status=0x11 assist_receive_interrupt=1 "
            "assist_receive_in=0xA5 assist_receive_after_in_status=0x00 "
            "assist_error_status=0x4C assist_error_interrupt=1 "
            "assist_error_after_read_status=0x08 tstates=0\n"
        )

        self.assertEqual(16, len(report.raw_reads))
        self.assertEqual((2, 1, 2, 1, 1, 2, 1, 2), report.assist_send_drives)
        self.assertEqual(0xA5, report.assist_receive_in)
        self.assertFalse(report.raw_peer_interrupt)

    def test_rejects_incomplete_link_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_link_report("mode=link-edge-probe port08_active=1")

    def test_parses_native_usb_status(self):
        report = parse_usb_report(
            "mode=usb-edge-probe port4a_active=1 port4c_active=1 "
            "port4d_active=1 port54_active=0 port54_read_accepted=0 "
            "port54_read=0xFF port55_active=1 port56_active=1 "
            "port57_active=1 port5b_active=1 port80_active=1 "
            "initial_port4a=0x04 initial_port4c=0x22 initial_port4d=0xA5 "
            "initial_port55=0x1F initial_port56=0x50 initial_port57=0x00 "
            "initial_port5b=0x00 initial_port80=0x00 "
            "initial_line_state=0xA5 initial_events=0x50 "
            "initial_event_mask=0x00 initial_line_interrupt=0 "
            "initial_protocol_interrupt=0 initial_stored_port4a=0x00 "
            "initial_stored_port4c=0x00 initial_stored_port54=0x00 "
            "mask_ff_read=0xFF mask_zero_read=0x00 event_interrupt=1 "
            "event_line_interrupt=1 event_line_state=0xE5 event_events=0x58 "
            "event_port4a=0x0C event_port4d=0xE5 event_port55=0x1B "
            "event_port56=0x58 repeated_event_interrupt=1 repeated_events=0x58 "
            "summary_none=0x1F summary_line=0x1B summary_protocol=0x0F "
            "summary_both=0x0B port5b_ff_read=0x01 "
            "protocol_interrupt_enabled=1 port80_ff_read=0x7F "
            "stored_dev_address=0x7F port4c_ff_read=0x2A "
            "stored_port4c=0x08 port4d_false_pair=0xA7 "
            "port4d_true_pair=0xE7 port4a_true_condition=0x09 "
            "port4a_false_condition=0x0C tstates=0\n"
        )

        self.assertFalse(report.port54_active)
        self.assertEqual(0xE5, report.event_line_state)
        self.assertEqual((0x1F, 0x1B, 0x0F, 0x0B), (
            report.summary_none,
            report.summary_line,
            report.summary_protocol,
            report.summary_both,
        ))

    def test_rejects_incomplete_usb_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_usb_report("mode=usb-edge-probe port4a_active=1")

    def test_parses_controlled_usb_rom_case(self):
        report = parse_usb_rom_case_report(
            "mode=usb-rom-probe case=init-success handshake=1 frame=1 "
            "boot_steps=134845 boot_tstates=1746999 probe_steps=5923 "
            "probe_tstates=62196 init_visits=1 reset_helper_visits=1 "
            "timeout_tick_visits=2 cleanup_visits=0 "
            "receive_boundary_visits=0 return_visits=1 violation_resets=0 "
            "flash_changed_bytes=0 input_4c=2 input_4d=0 input_8c=1 "
            "output_4a=1 output_4b=1 output_4c=2 output_54=3 output_57=1 "
            "output_87=1 output_89=1 output_8b=1 output_92=1 "
            "final_a=0x01 final_f=0x00 final_pc=0x9D98 completed=1 "
            "writes=5780,4C00,5402"
        )

        self.assertEqual("init-success", report.case)
        self.assertEqual(((0x57, 0x80), (0x4C, 0), (0x54, 2)), report.writes)
        self.assertEqual(0x9D98, report.final_pc)
        self.assertTrue(report.completed)

    def test_parses_each_controlled_usb_rom_case_once(self):
        base = (
            "mode=usb-rom-probe case={case} handshake=1 frame=1 "
            "boot_steps=1 boot_tstates=2 probe_steps=3 probe_tstates=4 "
            "init_visits=1 reset_helper_visits=1 timeout_tick_visits=2 "
            "cleanup_visits=0 receive_boundary_visits=0 return_visits=1 "
            "violation_resets=0 flash_changed_bytes=0 input_4c=2 input_4d=0 "
            "input_8c=1 output_4a=1 output_4b=1 output_4c=2 output_54=3 "
            "output_57=1 output_87=1 output_89=1 output_8b=1 output_92=1 "
            "final_a=1 final_f=0 final_pc=0x9D98 completed=1 writes=5780"
        )
        cases = (
            "init-success",
            "handshake-timeout",
            "frame-timeout",
            "attempt-event-40",
        )
        output = "\n".join(base.format(case=case) for case in cases)

        reports = parse_usb_rom_reports(output)

        self.assertEqual(cases, tuple(report.case for report in reports))

    def test_parses_controlled_usb_receive_report(self):
        report = parse_usb_rom_receive_report(
            "mode=usb-rom-receive-probe boot_steps=134845 "
            "boot_tstates=1746999 probe_steps=78862 probe_tstates=927502 "
            "init_visits=1 receive_entry_visits=1 control_start_visits=1 "
            "ack_parse_visits=1 stream_receive_visits=1 "
            "record_dispatch_visits=1 progress_visits=1 "
            "progress_state_seeded=1 receive_iy=0x89F0 "
            "power_gate_value=0x08 page_check_visits=1 "
            "page_check_value=0x3E invalid_page_visits=1 cleanup_visits=1 "
            "stop_visits=1 violation_resets=0 flash_changed_bytes=0 "
            "rx_packet_count=3 rx_bytes=24 rx_consumed=3 "
            "tx_packet_count=2 tx_bytes=26 script_error=0 final_pc=0x5000 "
            "completed=1 rx_packets=0000000205;E000;"
            "0000000C0400000000000500003E000000 "
            "tx_packets=0000000E040000000800030000010400000000;"
            "0000000205E000"
        )

        self.assertEqual(0x3E, report.page_check_value)
        self.assertEqual(3, len(report.rx_packets))
        self.assertEqual(19, len(report.tx_packets[0]))
        self.assertTrue(report.completed)

    def test_rejects_usb_receive_packet_count_drift(self):
        line = (
            "mode=usb-rom-receive-probe boot_steps=1 boot_tstates=2 "
            "probe_steps=3 probe_tstates=4 init_visits=1 "
            "receive_entry_visits=1 control_start_visits=1 ack_parse_visits=1 "
            "stream_receive_visits=1 record_dispatch_visits=1 "
            "progress_visits=1 progress_state_seeded=1 receive_iy=0x89F0 "
            "power_gate_value=8 page_check_visits=1 page_check_value=0x3E "
            "invalid_page_visits=1 cleanup_visits=1 stop_visits=1 "
            "violation_resets=0 flash_changed_bytes=0 rx_packet_count=2 "
            "rx_bytes=5 rx_consumed=1 tx_packet_count=0 tx_bytes=0 "
            "script_error=0 final_pc=0x5000 completed=1 "
            "rx_packets=0000000000 tx_packets=-"
        )
        with self.assertRaisesRegex(WabbitemuHeadlessError, "invalid"):
            parse_usb_rom_receive_report(line)

    def test_rejects_missing_or_duplicate_controlled_usb_rom_case(self):
        base = (
            "mode=usb-rom-probe case={case} handshake=1 frame=1 boot_steps=1 "
            "boot_tstates=2 probe_steps=3 probe_tstates=4 init_visits=1 "
            "reset_helper_visits=1 timeout_tick_visits=2 cleanup_visits=0 "
            "receive_boundary_visits=0 return_visits=1 violation_resets=0 "
            "flash_changed_bytes=0 input_4c=2 input_4d=0 input_8c=1 "
            "output_4a=1 output_4b=1 output_4c=2 output_54=3 output_57=1 "
            "output_87=1 output_89=1 output_8b=1 output_92=1 final_a=1 "
            "final_f=0 final_pc=0x9D98 completed=1 writes=5780"
        )
        incomplete = "\n".join(
            base.format(case=case)
            for case in (
                "init-success",
                "handshake-timeout",
                "frame-timeout",
                "frame-timeout",
            )
        )

        with self.assertRaisesRegex(WabbitemuHeadlessError, "exactly once"):
            parse_usb_rom_reports(incomplete)

    def test_parses_native_mapper_status(self):
        values = expected_mapper_values()
        tokens = ["mode=mapper-edge-probe"]
        for name, value in values.items():
            rendered = str(int(value)) if isinstance(value, bool) else hex(value)
            tokens.append(f"{name}={rendered}")

        report = parse_mapper_report(" ".join(tokens))

        self.assertEqual(0x3F, report.fixed_page_after_data_read)
        self.assertEqual(0, report.fixed_page_after_opcode)
        self.assertEqual((2, 2, 3), (
            report.paired_a_page,
            report.paired_b_page,
            report.paired_c_page,
        ))
        self.assertTrue(report.paired_fetch_halted)

    def test_rejects_incomplete_mapper_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_mapper_report("mode=mapper-edge-probe port04_active=1")

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
            "flash_changed_bytes=1 target_sector_changed_bytes=1 "
            "protected_changed_bytes=0 outside_target_changed_bytes=0 "
            "final_pc=0x9D98 classification=failure\n"
        )

        self.assertEqual((0x20, 0x50), report.poll_reads)
        self.assertEqual(0x3F2C, report.return_af)
        self.assertEqual(0, report.protected_changed_bytes)
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

    def test_parses_native_prefix_m1_status(self):
        frame_hex = "AA" * 73
        report = parse_prefix_m1_report(
            "mode=prefix-m1-probe probe_size=587 boot_steps=1234 "
            "boot_tstates=5678 max_probe_steps=1500000 probe_steps=4321 "
            "probe_tstates=8765 call_address=0x9FDC violation_resets=0 "
            f"outcome=0 completed=1 frame_hex={frame_hex} final_pc=0x9FDC"
        )

        self.assertTrue(report.completed)
        self.assertEqual(587, report.probe_size)
        self.assertEqual(0x9FDC, report.call_address)
        self.assertEqual(frame_hex, report.frame_hex)

    def test_rejects_incomplete_prefix_m1_status(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "omits"):
            parse_prefix_m1_report("mode=prefix-m1-probe probe_size=587")

    def test_rejects_wrong_prefix_m1_frame_length(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "invalid"):
            parse_prefix_m1_report(
                "mode=prefix-m1-probe probe_size=587 boot_steps=1 "
                "boot_tstates=2 max_probe_steps=3 probe_steps=4 "
                "probe_tstates=5 call_address=0x9FDC violation_resets=0 "
                "outcome=0 completed=1 frame_hex=AA final_pc=0x9FDC"
            )

    def test_parses_native_physical_timer_status(self):
        frame_hex = "BB" * 101
        report = parse_timer_physical_report(
            "mode=timer-physical-probe probe_size=831 boot_steps=1234 "
            "boot_tstates=5678 max_probe_steps=3000000 probe_steps=4321 "
            "probe_tstates=8765 call_address=0xA07A violation_resets=0 "
            f"outcome=0 completed=1 frame_hex={frame_hex} final_pc=0xA07A"
        )

        self.assertTrue(report.completed)
        self.assertEqual(831, report.probe_size)
        self.assertEqual(0xA07A, report.call_address)
        self.assertEqual(frame_hex, report.frame_hex)


if __name__ == "__main__":
    unittest.main()
