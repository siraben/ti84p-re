#!/usr/bin/env python3
"""Regression tests for physical hardware-probe result containers."""

import hashlib
import unittest


from ti84re.hardware.probe import (
    KEYPAD_SETTLE_DELAY_NOPS,
    KEYPAD_SETTLE_GROUP_WRITES,
    KEYPAD_SETTLE_HOLD_LOOP_BASE_T_STATES,
    KEYPAD_SETTLE_HOLD_LOOP_ITERATIONS,
    KEYPAD_SETTLE_TRIALS,
    LINK_RAW_DELAY_NOPS,
    LINK_RAW_TRIALS,
    LINK_RAW_WRITES,
    ProbeFormatError,
    ProbeFrame,
    decode_probe_appvar,
    decode_probe_frame,
    decode_probe_measurements,
    probe_verification_code,
    decode_ti_variable_file,
    encode_probe_appvar,
    encode_ti_variable_file,
    probe_appvar_report,
)
from ti84re.link.port import port_read_value


class HardwareProbeTests(unittest.TestCase):
    def test_probe_frame_round_trip(self):
        frame = ProbeFrame(probe_id=2, asic_id=0x55, status=0xE3, payload=b"\x10\x20")

        self.assertEqual(frame, decode_probe_frame(frame.encode()))

    def test_probe_appvar_round_trip_checks_both_containers(self):
        frame = ProbeFrame(probe_id=1, asic_id=0x45, status=0xE7, payload=b"result")

        variable, decoded = decode_probe_appvar(encode_probe_appvar("HWPMD51", frame))

        self.assertEqual("HWPMD51", variable.name)
        self.assertEqual(0x15, variable.variable_type)
        self.assertEqual(frame, decoded)

    def test_report_retains_complete_container_and_frame_identities(self):
        frame = ProbeFrame(
            probe_id=3,
            asic_id=0x45,
            status=0xE3,
            payload=bytes.fromhex("06013317272F3B454BF0A5"),
        )
        blob = encode_probe_appvar("HWPASIC1", frame)

        report = probe_appvar_report(blob)

        self.assertEqual(len(blob), report["appvar_file_size"])
        self.assertEqual(hashlib.sha256(blob).hexdigest(), report["appvar_file_sha256"])
        self.assertEqual(frame.encode().hex().upper(), report["frame_hex"])
        self.assertEqual(
            hashlib.sha256(frame.encode()).hexdigest(), report["frame_sha256"]
        )
        self.assertEqual(0, report["variable_version"])
        self.assertEqual("Codex hardware probe", report["container_comment"])

    def test_generic_ti_program_container_remains_compatible(self):
        body = b"\x01\x00\xC9"

        variable = decode_ti_variable_file(
            encode_ti_variable_file(0x05, "ASMRET", body, comment="fixture")
        )

        self.assertEqual(0x05, variable.variable_type)
        self.assertEqual("ASMRET", variable.name)
        self.assertEqual(body, variable.data)

    def test_archived_variable_uses_ti_archive_flag(self):
        encoded = encode_ti_variable_file(0x05, "ARCHIVE", b"x", archived=True)

        self.assertEqual(0x80, encoded[55 + 14])
        self.assertTrue(decode_ti_variable_file(encoded).archived)

    def test_rejects_ti_checksum_corruption(self):
        encoded = bytearray(
            encode_probe_appvar(
                "HWPRAM1",
                ProbeFrame(probe_id=2, asic_id=0x45, status=0xE3, payload=b"x"),
            )
        )
        encoded[-1] ^= 1

        with self.assertRaisesRegex(ProbeFormatError, "checksum"):
            decode_probe_appvar(bytes(encoded))

    def test_rejects_frame_length_mismatch(self):
        encoded = bytearray(
            ProbeFrame(probe_id=1, asic_id=0x45, status=0xE3, payload=b"abc").encode()
        )
        encoded[6:8] = (4).to_bytes(2, "little")

        with self.assertRaisesRegex(ProbeFormatError, "length"):
            decode_probe_frame(bytes(encoded))

    def test_rejects_unsupported_encode_version(self):
        frame = ProbeFrame(
            probe_id=1,
            asic_id=0x45,
            status=0xE3,
            payload=b"",
            format_version=2,
        )

        with self.assertRaisesRegex(ValueError, "version 2"):
            frame.encode()

    def test_md5_measurements_decode_little_endian_words(self):
        payload = (
            bytes.fromhex("B417D1D6")
            + bytes.fromhex("00000000")
            + bytes.fromhex("01020304")
            + bytes.fromhex("10203040")
            + bytes.fromhex("AABBCCDD")
        )

        report = decode_probe_measurements(
            ProbeFrame(probe_id=1, asic_id=0x55, status=0xE3, payload=payload)
        )

        self.assertEqual("0xD6D117B4", report["valid_result"])
        self.assertEqual("00000000", report["undefined_reads"])
        self.assertEqual("0x04030201", report["fifth_write_result"])

    def test_ram_measurements_report_alias_and_restore(self):
        original = bytes.fromhex("102030405060")
        payload = original + bytes((0x66,)) * 6 + original
        frame = ProbeFrame(probe_id=2, asic_id=0x55, status=0xE3, payload=payload)

        report = probe_appvar_report(encode_probe_appvar("HWPRAM21", frame))

        self.assertEqual("ram-alias", report["probe_name"])
        self.assertEqual(0x55, report["asic_id"])
        self.assertEqual("0x55", report["asic_id_hex"])
        self.assertEqual(
            "selectors-82-through-87-alias",
            report["measurements"]["topology_observation"],
        )
        self.assertTrue(report["measurements"]["restore_matches"])
        self.assertEqual(
            [["0x82", "0x83", "0x84", "0x85", "0x86", "0x87"]],
            report["measurements"]["alias_groups"],
        )

    def test_ram_measurements_report_partial_alias_groups(self):
        original = bytes.fromhex("102030405060")
        observed = bytes.fromhex("222244445566")
        frame = ProbeFrame(
            probe_id=2,
            asic_id=0x45,
            status=0xE3,
            payload=original + observed + original,
        )

        report = decode_probe_measurements(frame)

        self.assertEqual("partial-selector-aliases", report["topology_observation"])
        self.assertEqual(
            [["0x82", "0x83"], ["0x84", "0x85"], ["0x86"], ["0x87"]],
            report["alias_groups"],
        )

    def test_known_probe_rejects_wrong_payload_size(self):
        frame = ProbeFrame(probe_id=2, asic_id=0x55, status=0xE3, payload=b"x")

        with self.assertRaisesRegex(ProbeFormatError, "18 bytes"):
            decode_probe_measurements(frame)

    def test_asic_snapshot_maps_payload_bytes_to_ports(self):
        payload = bytes.fromhex("06013317272F3B454BF0A5")
        frame = ProbeFrame(probe_id=3, asic_id=0x45, status=0xE3, payload=payload)

        report = decode_probe_measurements(frame)

        self.assertEqual("0x06", report["registers"]["0x04"])
        self.assertEqual("0x01", report["registers"]["0x20"])
        self.assertEqual("0xF0", report["registers"]["0x39"])
        self.assertEqual("0xA5", report["registers"]["0x3A"])

    def test_execution_fetch_decodes_target_outcome_and_registers(self):
        payload = bytes.fromhex(
            "01820004000434420107821008292026"
        )
        frame = ProbeFrame(probe_id=4, asic_id=0x45, status=0xE3, payload=payload)

        report = decode_probe_measurements(frame)

        self.assertEqual("ram", report["target_kind"])
        self.assertEqual("0x82", report["target_selector"])
        self.assertEqual("0x0400", report["scan_start"])
        self.assertEqual("0x0400", report["scan_length"])
        self.assertEqual("0x4234", report["target_address"])
        self.assertEqual("returned", report["outcome"])
        self.assertEqual("0x07", report["registers"]["0x04"])
        self.assertEqual("0x08", report["registers"]["0x22"])

    def test_usb_snapshot_maps_payload_bytes_to_ports(self):
        payload = bytes(range(0x10, 0x1F))
        frame = ProbeFrame(probe_id=5, asic_id=0x45, status=0xE3, payload=payload)

        report = decode_probe_measurements(frame)

        self.assertEqual("0x10", report["registers"]["0x49"])
        self.assertEqual("0x17", report["registers"]["0x51"])
        self.assertEqual("0x18", report["registers"]["0x52"])
        self.assertEqual("0x1E", report["registers"]["0x5B"])

    def test_battery_probe_reports_stability_and_cleanup(self):
        pre = bytes.fromhex("06F08020")
        levels = bytes((3,)) * 16
        post = bytes.fromhex("E306F09000")
        restored = pre
        final_status = bytes.fromhex("E3")
        frame = ProbeFrame(
            probe_id=6,
            asic_id=0x45,
            status=0xE3,
            payload=pre + levels + post + restored + final_status,
        )

        report = decode_probe_measurements(frame)

        self.assertEqual(3, report["stable_level"])
        self.assertEqual(16, report["sample_histogram"]["3"])
        self.assertTrue(report["cleanup_matches"])
        self.assertEqual("0xF0", report["restored"]["port_0x39"])

    def test_battery_probe_rejects_invalid_level(self):
        payload = bytes(4) + bytes((5,)) + bytes(15) + bytes(10)
        frame = ProbeFrame(probe_id=6, asic_id=0x45, status=0xE3, payload=payload)

        with self.assertRaisesRegex(ProbeFormatError, "range 0 through 4"):
            decode_probe_measurements(frame)

    def test_raw_battery_probe_reports_masks_selectors_and_cleanup(self):
        pre = bytes.fromhex("06F08020")
        masks = bytes((0x0D,)) * 16
        post = bytes.fromhex("E306F09000")
        frame = ProbeFrame(
            probe_id=7,
            asic_id=0x45,
            status=0xE3,
            payload=pre + masks + post + pre + bytes.fromhex("E3"),
        )

        report = decode_probe_measurements(frame)

        self.assertEqual(0x0D, report["stable_mask"])
        self.assertEqual(16, report["mask_histogram"]["13"])
        self.assertEqual(
            {"0x06": 16, "0x46": 0, "0x86": 16, "0xC6": 16},
            report["selector_pass_counts"],
        )
        self.assertTrue(report["cleanup_matches"])

    def test_raw_battery_probe_reports_unstable_masks_and_cleanup_mismatch(self):
        pre = bytes.fromhex("06F08020")
        masks = bytes((0x01, 0x03)) * 8
        post = bytes.fromhex("E306F09000")
        restored = bytes.fromhex("06F08021")
        frame = ProbeFrame(
            probe_id=7,
            asic_id=0x45,
            status=0xE3,
            payload=pre + masks + post + restored + bytes.fromhex("E3"),
        )

        report = decode_probe_measurements(frame)

        self.assertIsNone(report["stable_mask"])
        self.assertEqual(8, report["mask_histogram"]["1"])
        self.assertEqual(8, report["mask_histogram"]["3"])
        self.assertFalse(report["cleanup_matches"])

    def test_raw_battery_probe_rejects_invalid_mask(self):
        payload = bytes(4) + bytes((0x10,)) + bytes(15) + bytes(10)
        frame = ProbeFrame(probe_id=7, asic_id=0x45, status=0xE3, payload=payload)

        with self.assertRaisesRegex(ProbeFormatError, "range 0 through 15"):
            decode_probe_measurements(frame)

    def test_raw_link_probe_reports_disconnected_truth_table_and_cleanup(self):
        pre = bytes.fromhex("030B0601")
        samples = bytes(
            port_read_value(write, 0)
            for write in LINK_RAW_WRITES
            for _trial in range(LINK_RAW_TRIALS)
            for _delay in LINK_RAW_DELAY_NOPS
        )
        post = bytes.fromhex("300B0601")
        frame = ProbeFrame(
            probe_id=8,
            asic_id=0x45,
            status=0xE3,
            payload=pre + samples + post + bytes.fromhex("03E3"),
        )

        report = decode_probe_measurements(frame)

        self.assertEqual(16, len(report["points"]))
        self.assertEqual(0, report["points"][0]["write"])
        self.assertEqual(0, report["points"][0]["delay_nops"])
        self.assertEqual(0x03, report["points"][0]["stable_value"])
        self.assertEqual(0x12, report["points"][4]["stable_value"])
        self.assertTrue(report["disconnected_contract_matches"])
        self.assertTrue(report["pre_latch_was_idle"])
        self.assertTrue(report["cleanup_idle_matches"])

    def test_raw_link_probe_reports_sample_and_cleanup_mismatches(self):
        samples = bytearray(
            port_read_value(write, 0)
            for write in LINK_RAW_WRITES
            for _trial in range(LINK_RAW_TRIALS)
            for _delay in LINK_RAW_DELAY_NOPS
        )
        samples[0] = 0x02
        post = bytes.fromhex("300B0601")
        frame = ProbeFrame(
            probe_id=8,
            asic_id=0x45,
            status=0xE3,
            payload=bytes.fromhex("130B0601")
            + samples
            + post
            + bytes.fromhex("13E3"),
        )

        report = decode_probe_measurements(frame)

        self.assertFalse(report["disconnected_contract_matches"])
        self.assertEqual(15, report["points"][0]["disconnected_match_count"])
        self.assertIsNone(report["points"][0]["stable_value"])
        self.assertFalse(report["pre_latch_was_idle"])
        self.assertFalse(report["cleanup_idle_matches"])

    def test_raw_link_probe_rejects_wrong_payload_size(self):
        frame = ProbeFrame(probe_id=8, asic_id=0x45, status=0xE3, payload=b"x")

        with self.assertRaisesRegex(ProbeFormatError, "266 bytes"):
            decode_probe_measurements(frame)

    def test_physical_timer_probe_decodes_models_and_restoration(self):
        pre = bytes.fromhex("E300084401034B000000000000")
        crystal = bytes((255, 255, 143, 32)) * 4
        mode3 = b"".join(
            bytes(row)
            for row in (
                (0, 0, 254, 64, 250, 52, 34, 1, 8),
                (1, 1, 254, 64, 250, 7, 86, 1, 8),
                (2, 1, 254, 64, 250, 7, 86, 1, 8),
                (3, 1, 254, 64, 250, 7, 86, 1, 8),
            )
        )
        zero = bytes((0, 31, 31, 0, 4, 0x68))
        expiry = bytes((250, 5, 0x68, 240, 5, 0x68))
        frame = ProbeFrame(
            probe_id=12,
            asic_id=0x44,
            status=0xE3,
            payload=pre + bytes((0,)) + crystal + mode3 + zero + expiry + pre,
        )

        report = decode_probe_measurements(frame)

        self.assertEqual("completed", report["outcome"])
        self.assertEqual(
            "wabbitemu-and-mame-divisor-32",
            report["measurements"]["crystal_divisor"]["closer_to"],
        )
        self.assertTrue(all(report["restored"].values()))

    def test_physical_timer_probe_rejects_wrong_payload_size(self):
        frame = ProbeFrame(probe_id=12, asic_id=0x44, status=0xE3, payload=b"x")

        with self.assertRaisesRegex(ProbeFormatError, "91 bytes"):
            decode_probe_measurements(frame)

    def test_physical_timer_probe_names_measurement_timeout(self):
        frame = ProbeFrame(
            probe_id=12,
            asic_id=0x44,
            status=0xE3,
            payload=bytes(13) + bytes((6,)) + bytes(64) + bytes(13),
        )

        report = decode_probe_measurements(frame)

        self.assertEqual("measurement-timeout", report["outcome"])
        self.assertIsNone(report["measurements"])

    def test_rtc_rollover_probe_decodes_coherent_transition(self):
        frame = ProbeFrame(
            probe_id=13,
            asic_id=0x55,
            status=0xE3,
            payload=(
                bytes.fromhex("0100")
                + bytes.fromhex("00FFFFFF")
                + bytes.fromhex("01000000")
                + bytes.fromhex("00000001")
                + bytes.fromhex("01000000")
                + bytes.fromhex("01")
            ),
        )

        report = decode_probe_measurements(frame)

        self.assertEqual("completed", report["outcome"])
        self.assertEqual("0x00FFFFFF", report["last_low_ff"])
        self.assertEqual("0x01000000", report["first_high_to_low_after"])
        self.assertTrue(report["first_transition_coherent"])
        self.assertTrue(report["later_reads_monotonic"])
        self.assertTrue(report["control_unchanged"])

    def test_rtc_rollover_probe_rejects_wrong_payload_size(self):
        frame = ProbeFrame(probe_id=13, asic_id=0x55, status=0xE3, payload=b"x")

        with self.assertRaisesRegex(ProbeFormatError, "19 bytes"):
            decode_probe_measurements(frame)

    def test_keypad_settle_probe_reports_rows_and_reference_differences(self):
        samples = bytearray()
        for group_index, _group_write in enumerate(KEYPAD_SETTLE_GROUP_WRITES):
            reference = 0xFF ^ (1 << group_index)
            for trial in range(KEYPAD_SETTLE_TRIALS):
                for delay_nops in KEYPAD_SETTLE_DELAY_NOPS:
                    value = reference
                    if group_index == 0 and trial == 0 and delay_nops == 0:
                        value &= 0xFC
                    samples.append(value)
        frame = ProbeFrame(
            probe_id=9,
            asic_id=0x45,
            status=0xE3,
            payload=(
                bytes.fromhex("FFE30B0601FE")
                + samples
                + bytes.fromhex("FFE30B0601")
            ),
        )

        report = decode_probe_measurements(frame)

        self.assertEqual(32, len(report["points"]))
        self.assertEqual(0xFE, report["points"][0]["group_write"])
        self.assertEqual(0, report["points"][0]["delay_nops"])
        self.assertIsNone(report["points"][0]["stable_value"])
        self.assertEqual(
            15, report["points"][0]["reference_64_nop_match_count"]
        )
        self.assertEqual(1, report["points"][0]["extra_low_vs_64_nop_count"])
        self.assertEqual(0, report["points"][0]["other_difference_vs_64_nop_count"])
        self.assertEqual(0xFE, report["points"][3]["stable_value"])
        self.assertEqual(0x01, report["points"][3]["stable_pressed_columns"])
        self.assertEqual(0x01, report["trigger_pressed_columns"])
        self.assertEqual(
            KEYPAD_SETTLE_HOLD_LOOP_ITERATIONS,
            report["pre_sample_hold_loop_iterations"],
        )
        self.assertEqual(
            KEYPAD_SETTLE_HOLD_LOOP_BASE_T_STATES,
            report["pre_sample_hold_loop_base_t_states"],
        )
        self.assertTrue(report["entry_all_columns_high"])
        self.assertTrue(report["cleanup_all_columns_high"])
        self.assertTrue(report["status_unchanged"])
        self.assertTrue(report["interrupt_ports_unchanged"])
        self.assertTrue(report["speed_unchanged"])

    def test_keypad_settle_probe_reports_cleanup_and_state_mismatches(self):
        samples = bytes(
            0xFF
            for _group_write in KEYPAD_SETTLE_GROUP_WRITES
            for _trial in range(KEYPAD_SETTLE_TRIALS)
            for _delay in KEYPAD_SETTLE_DELAY_NOPS
        )
        frame = ProbeFrame(
            probe_id=9,
            asic_id=0x45,
            status=0xE3,
            payload=(
                bytes.fromhex("FEE30B0601FE")
                + samples
                + bytes.fromhex("FDE20A0400")
            ),
        )

        report = decode_probe_measurements(frame)

        self.assertFalse(report["entry_all_columns_high"])
        self.assertFalse(report["cleanup_all_columns_high"])
        self.assertFalse(report["status_unchanged"])
        self.assertFalse(report["interrupt_ports_unchanged"])
        self.assertFalse(report["speed_unchanged"])

    def test_keypad_settle_probe_rejects_wrong_payload_size(self):
        frame = ProbeFrame(probe_id=9, asic_id=0x45, status=0xE3, payload=b"x")

        with self.assertRaisesRegex(ProbeFormatError, "523 bytes"):
            decode_probe_measurements(frame)

    def test_bus_timing_probe_reports_measurements_and_restoration(self):
        pre = bytes.fromhex("E30B080117272F3B454B0000AA")
        deltas = (7, 6, 6, 22, 11, 6)
        measurements = b"".join(
            bytes((0xF5, 0, 0x08, 0xF5 - delta, 0, 0x08))
            for delta in deltas
        )
        frame = ProbeFrame(
            probe_id=10,
            asic_id=0x45,
            status=0xE3,
            payload=pre + b"\0" + measurements + pre,
        )

        report = decode_probe_measurements(frame)

        self.assertEqual("completed", report["outcome"])
        self.assertEqual("0x45", report["pre"]["0x2E"])
        self.assertEqual(7, report["measurements"]["cases"][0]["added_timer_ticks"])
        self.assertTrue(all(report["restored"].values()))
        self.assertTrue(report["speed_unchanged"])
        self.assertTrue(report["timing_gates_unchanged"])

    def test_bus_timing_probe_reports_guard_abort_without_measurements(self):
        pre = bytes.fromhex("E30B080117272F3B454B0000AA")
        frame = ProbeFrame(
            probe_id=10,
            asic_id=0x45,
            status=0xE3,
            payload=pre + bytes((4,)) + bytes(36) + pre,
        )

        report = decode_probe_measurements(frame)

        self.assertEqual("timing-gate-disabled", report["outcome"])
        self.assertIsNone(report["measurements"])

    def test_bus_timing_probe_rejects_wrong_payload_size(self):
        frame = ProbeFrame(probe_id=10, asic_id=0x45, status=0xE3, payload=b"x")

        with self.assertRaisesRegex(ProbeFormatError, "63 bytes"):
            decode_probe_measurements(frame)

    def test_prefix_m1_probe_reports_model_discriminator_and_restoration(self):
        pre = bytes.fromhex("E30B080117272F3B454B0000AA")
        deltas = (21, 25, 25, 25, 29, 25)
        measurements = b"".join(
            bytes((0xE0, 0, 0x08, 0xE0 - delta, 0, 0x08))
            for delta in deltas
        )
        frame = ProbeFrame(
            probe_id=11,
            asic_id=0x45,
            status=0xE3,
            payload=pre + b"\0" + measurements + pre,
        )

        report = decode_probe_measurements(frame)

        self.assertEqual("completed", report["outcome"])
        self.assertEqual(
            "z80-and-tilem-two-m1",
            report["measurements"]["indexed_cb_discriminator"]["closer_to"],
        )
        self.assertTrue(all(report["restored"].values()))

    def test_prefix_m1_probe_reports_guard_abort_without_measurements(self):
        pre = bytes.fromhex("E30B080117272F3B454B0000AA")
        frame = ProbeFrame(
            probe_id=11,
            asic_id=0x45,
            status=0xE3,
            payload=pre + bytes((3,)) + bytes(36) + pre,
        )

        report = decode_probe_measurements(frame)

        self.assertEqual("ram-timing-gate-disabled", report["outcome"])
        self.assertIsNone(report["measurements"])

    def test_prefix_m1_probe_rejects_wrong_payload_size(self):
        frame = ProbeFrame(probe_id=11, asic_id=0x45, status=0xE3, payload=b"x")

        with self.assertRaisesRegex(ProbeFormatError, "63 bytes"):
            decode_probe_measurements(frame)

    def test_mapper_probe_decodes_tilem_routing_and_restoration(self):
        pre = bytes.fromhex("0B08003F8100000000")
        independent = bytes.fromhex("A1A2B3414445464748")
        independent_writes = bytes.fromhex("B1C141D1")
        paired = bytes.fromhex("A1A2E3414445464748")
        paired_writes = bytes.fromhex("E1C241D2")
        frame = ProbeFrame(
            probe_id=14,
            asic_id=0x45,
            status=0xE3,
            payload=(
                pre
                + b"\0"
                + independent
                + independent_writes
                + paired
                + paired_writes
                + bytes((0x7B, 0x0F))
                + pre
            ),
        )

        report = decode_probe_measurements(frame)

        self.assertEqual("completed", report["outcome"])
        self.assertEqual("tilem", report["closest_emulator_profile"])
        self.assertTrue(report["all_marker_pages_restored"])
        self.assertTrue(report["readable_ports_restored"])

    def test_lcd_probe_decodes_legacy_hidden_column_models(self):
        pre = bytes.fromhex("C308630314272F3B01444B2080")
        post = bytes.fromhex("C308630314272F3B01444B")
        models = {
            "tilem-16-column": bytes.fromhex("A600A4A5000000"),
            "wabbitemu-15-column-wrap": bytes.fromhex("A5A6A400000000"),
            "mame-15-byte-spill": bytes.fromhex("0000A400A5A600"),
        }
        for expected, cells in models.items():
            with self.subTest(model=expected):
                payload = (
                    pre
                    + b"\0"
                    + bytes.fromhex("010002000300")
                    + bytes.fromhex("0080")
                    + cells
                    + bytes.fromhex("000001")
                    + post
                )
                report = decode_probe_measurements(
                    ProbeFrame(15, 0x45, 0xE3, payload)
                )
                self.assertEqual(expected, report["row_model"])
                self.assertTrue(report["restore_ok"])

    def test_lcd_probe_decodes_visible_cell_and_busy_samples(self):
        pre = bytes.fromhex("C308630314272F3B01444B2080")
        post = bytes.fromhex("C308630314272F3B01444B")
        payload = (
            pre
            + b"\0"
            + bytes.fromhex("010002000300")
            + bytes.fromhex("00E3006300E3")
            + bytes.fromhex("AAAAAA0701")
            + post
        )

        report = decode_probe_measurements(ProbeFrame(15, 0x45, 0xE3, payload))

        self.assertEqual("visible-cell-v2", report["schema"])
        self.assertTrue(report["visible_cell"]["matches"])
        self.assertTrue(report["restore_ok"])
        self.assertTrue(report["movement_status_restored"])
        self.assertEqual(
            {"command_write": True, "data_read": False, "data_write": True},
            report["controller_busy_samples"],
        )

    def test_exact_lcd_emulator_frames_keep_displayed_codes_and_restoration(self):
        cases = {
            "tilem": (
                "48575031010F2A0045E1E108430114272F3B01444A20800002000200"
                "0200E1C3E1C3E1C30000000701E30A430114272F3B01444A",
                21731,
            ),
            "wabbitemu": (
                "48575031010F2A0044E1E108630117272F3B02454B20800004000000"
                "0300E180E363E1800000000701E30A630117272F3B02454B",
                23959,
            ),
        }

        for emulator, (frame_hex, expected_code) in cases.items():
            with self.subTest(emulator=emulator):
                frame = decode_probe_frame(bytes.fromhex(frame_hex))
                report = decode_probe_measurements(frame)

                self.assertEqual(expected_code, probe_verification_code(frame))
                self.assertEqual("completed", report["outcome"])
                self.assertTrue(report["visible_cell"]["matches"])
                self.assertTrue(report["restore_ok"])
                self.assertTrue(report["movement_status_restored"])
                self.assertTrue(report["wait_registers_unchanged"])

    def test_interrupt_probe_classifies_watchdog_wake(self):
        payload = bytes.fromhex(
            "0B08000000AA00012A06000800000B08000000AA01"
        )
        report = decode_probe_measurements(ProbeFrame(16, 0x45, 0xE3, payload))

        self.assertEqual("completed", report["outcome"])
        self.assertEqual("standard-timer-watchdog", report["wake_class"])
        self.assertTrue(report["restore_ok"])
        self.assertTrue(report["i_register_restored"])

    def test_verification_code_is_exposed_in_appvar_report(self):
        frame = ProbeFrame(16, 0x45, 0xE3, bytes(21))
        blob = encode_probe_appvar("HWPIRQ01", frame)

        report = probe_appvar_report(blob)

        self.assertEqual(probe_verification_code(frame), report["verification_code_decimal"])
        self.assertEqual(
            f"0x{probe_verification_code(frame):04X}",
            report["verification_code_hex"],
        )


if __name__ == "__main__":
    unittest.main()
