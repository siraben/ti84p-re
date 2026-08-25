#!/usr/bin/env python3
"""Regression tests for physical hardware-probe program packaging."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_hardware_probes import (
    CREATE_APPVAR_COPY,
    DISPLAY_BCALLS,
    DISPLAY_CRC_SIGNATURE,
    DISPLAY_IFF_GUARD,
    PROBE_START,
    PROBES,
    build_probes,
    initial_probe_payload,
    package_probe,
    validate_machine_code,
)
from hardware_probe import (
    APPVAR_TYPE,
    PROBE_FORMAT_VERSION,
    PROBE_MAGIC,
    decode_ti_variable_file,
)
from ti_program import asmprgm_body
from tibasic_samples import T


def fixture_machine_code(probe_name: str) -> bytes:
    """Return minimal bytes that satisfy the probe build contract."""

    probe = PROBES[probe_name]
    frame = (
        PROBE_MAGIC
        + bytes((PROBE_FORMAT_VERSION, probe.probe_id))
        + probe.payload_size.to_bytes(2, "little")
        + bytes(2)
        + initial_probe_payload(probe)
    )
    return (
        bytes((0xC3, PROBE_START & 0xFF, PROBE_START >> 8))
        + CREATE_APPVAR_COPY
        + DISPLAY_IFF_GUARD
        + DISPLAY_CRC_SIGNATURE
        + b"".join(DISPLAY_BCALLS)
        + b"\0"
        + (probe.appvar if probe.probe_id == 4 else probe.program).encode("ascii")
        + b" CODE \0"
        + bytes((APPVAR_TYPE,))
        + probe.appvar.encode("ascii")
        + b"\0"
        + frame
    )


def fixture_raw_battery_machine_code() -> bytes:
    """Return synthetic bytes satisfying the raw-probe structural contract."""

    base = fixture_machine_code("battery-raw")
    frame_size = 10 + PROBES["battery-raw"].payload_size
    sampler = bytes.fromhex("CD009E") * 16
    delay = bytes.fromhex("0605CDEB0C10FB")
    gpio = (
        bytes.fromhex("F680D33A")
        + bytes.fromhex("F610D33A3E40CDED0C")
        + bytes.fromhex("E6EFD33A")
        + bytes.fromhex("E67FD33A")
    )
    ports = (
        bytes.fromhex("DB04") * 3
        + bytes.fromhex("D304") * 3
        + bytes.fromhex("DB39") * 4
        + bytes.fromhex("D339") * 2
        + bytes.fromhex("DB3A") * 7
        + bytes.fromhex("D33A")
    )
    return (
        base[:-frame_size]
        + sampler
        + delay
        + gpio
        + ports
        + bytes.fromhex("FD7718")
        + base[-frame_size:]
    )


class HardwareProbeBuilderTests(unittest.TestCase):
    def test_asmprgm_body_wraps_uppercase_hex(self):
        body = asmprgm_body(bytes.fromhex("C3B59D"))

        self.assertEqual(
            bytes((
                T["2byte"],
                T["asmprgm"],
                T["enter"],
                T["C"],
                T["3"],
                T["B"],
                T["5"],
                T["9"],
                T["D"],
                T["enter"],
            )),
            body,
        )

    def test_probe_definitions_use_stable_names_and_ids(self):
        self.assertEqual(
            {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16},
            {probe.probe_id for probe in PROBES.values()},
        )
        for probe in PROBES.values():
            self.assertLessEqual(len(probe.program), 8)
            self.assertEqual(8, len(probe.appvar))
            self.assertTrue(probe.source.is_file())

    def test_execution_probe_definitions_cover_flash_and_ram_boundaries(self):
        execution = {
            name: dict(probe.defines)
            for name, probe in PROBES.items()
            if probe.probe_id == 4
        }

        self.assertEqual(10, len(execution))
        self.assertEqual(0x08, execution["exec-flash-08"]["TARGET_SELECTOR"])
        self.assertEqual(0x0400, execution["exec-ram-82-chunk0"]["SCAN_LENGTH"])
        self.assertEqual(0x4400, execution["exec-ram-82-chunk1"]["SCAN_START"])

    def test_every_probe_source_calls_the_shared_display_after_result_creation(self):
        source_names = {probe.source_name for probe in PROBES.values()}

        for source_name in source_names:
            with self.subTest(source=source_name):
                text = (Path(__file__).parent / "hardware-probes" / source_name).read_text()
                self.assertIn('#include "display.inc"', text)
                self.assertIn("call display_", text)

    def test_default_lcd_probe_rejects_hidden_columns_and_restores_after_status(self):
        text = (
            Path(__file__).parent / "hardware-probes" / "lcd-controller.asm"
        ).read_text()

        self.assertIn("cp $2C\n    jp nc,abort_hidden_column", text)
        self.assertIn("ld (pointer_safe),a", text)
        self.assertIn(
            "ld a,(pointer_safe)\n    or a\n    jr z,capture_post", text
        )
        self.assertIn("ld a,(payload_cell_before)\n    call safe_lcd_data_write", text)
        self.assertIn(
            "call wait_lcd_ready\n    jr c,safe_lcd_command_timeout", text
        )
        self.assertIn("call wait_lcd_ready\n    ret c", text)
        self.assertIn(
            "call wait_lcd_ready\n    jr c,safe_lcd_data_write_timeout", text
        )
        self.assertIn(
            "ld a,(lcd_timeout)\n    or a\n    jr nz,lcd_ready_prior_timeout", text
        )
        self.assertIn(
            "A status read can move the pointer on replacement controllers", text
        )
        self.assertNotIn("probe_cells:", text)
        self.assertNotIn("payload_direct_column", text)
        self.assertNotIn("$2E\n    call safe_lcd_command", text)
        self.assertNotIn("$3F\n    call safe_lcd_command", text)

    def test_display_include_guards_bcalls_and_uses_appvar_frame_helper(self):
        text = (Path(__file__).parent / "hardware-probes" / "display.inc").read_text()

        self.assertIn("ld a,i\n    ret po", text)
        self.assertIn("display_created_probe_code:", text)
        self.assertIn("sbc hl,bc", text)
        self.assertIn("pop ix", text)

    def test_packaged_program_decodes_to_original_machine_code(self):
        machine_code = fixture_machine_code("md5-edge")

        program, metadata = package_probe("md5-edge", machine_code)
        variable = decode_ti_variable_file(program)
        body_size = int.from_bytes(variable.data[:2], "little")
        body = variable.data[2:]
        recovered = bytes.fromhex(body[3:-1].decode("ascii"))

        self.assertEqual(0x05, variable.variable_type)
        self.assertEqual("HWPMD5", variable.name)
        self.assertEqual(len(body), body_size)
        self.assertEqual(bytes((T["2byte"], T["asmprgm"], T["enter"])), body[:3])
        self.assertEqual(T["enter"], body[-1])
        self.assertEqual(machine_code, recovered)
        self.assertEqual("tools/hardware-probes/md5-edge.asm", metadata["source"])
        self.assertEqual(20, metadata["payload_size"])

    def test_packaging_is_deterministic(self):
        machine_code = fixture_machine_code("ram-alias")

        first = package_probe("ram-alias", machine_code)
        second = package_probe("ram-alias", machine_code)

        self.assertEqual(first, second)

    def test_rejects_entry_without_jump(self):
        machine_code = bytearray(fixture_machine_code("md5-edge"))
        machine_code[0] = 0x00

        with self.assertRaisesRegex(ValueError, "begin with JP"):
            validate_machine_code("md5-edge", bytes(machine_code))

    def test_rejects_wrong_result_frame(self):
        machine_code = bytearray(fixture_machine_code("ram-alias"))
        machine_code[-1] = 1

        with self.assertRaisesRegex(ValueError, "result frame"):
            validate_machine_code("ram-alias", bytes(machine_code))

    def test_rejects_copy_that_overwrites_appvar_size(self):
        machine_code = fixture_machine_code("md5-edge").replace(
            CREATE_APPVAR_COPY, CREATE_APPVAR_COPY[:-2] + b"\0\0"
        )

        with self.assertRaisesRegex(ValueError, "size word"):
            validate_machine_code("md5-edge", machine_code)

    def test_execution_probe_requires_guarded_fetch_sequences(self):
        with self.assertRaisesRegex(ValueError, "omits|must"):
            validate_machine_code(
                "exec-flash-08",
                fixture_machine_code("exec-flash-08"),
            )

    def test_usb_probe_requires_every_direct_port_read(self):
        with self.assertRaisesRegex(ValueError, "must read port 0x49"):
            validate_machine_code(
                "usb-snapshot",
                fixture_machine_code("usb-snapshot"),
            )

    def test_rtc_probe_requires_read_only_rollover_sampling(self):
        with self.assertRaisesRegex(ValueError, "must read port 0x40"):
            validate_machine_code(
                "rtc-rollover",
                fixture_machine_code("rtc-rollover"),
            )

    def test_battery_probe_requires_bcall_samples_and_restoration(self):
        with self.assertRaisesRegex(ValueError, "call _Chk_Batt_Level"):
            validate_machine_code(
                "battery-level",
                fixture_machine_code("battery-level"),
            )

    def test_raw_battery_probe_requires_repeated_sampler(self):
        with self.assertRaisesRegex(ValueError, "16 identical sampler calls"):
            validate_machine_code(
                "battery-raw",
                fixture_machine_code("battery-raw"),
            )

    def test_raw_battery_probe_accepts_complete_structure(self):
        validate_machine_code(
            "battery-raw",
            fixture_raw_battery_machine_code(),
        )

    def test_raw_battery_probe_requires_delay_loop(self):
        machine_code = fixture_raw_battery_machine_code().replace(
            bytes.fromhex("0605CDEB0C10FB"),
            bytes.fromhex("0604CDEB0C10FB"),
        )

        with self.assertRaisesRegex(ValueError, "five calls"):
            validate_machine_code("battery-raw", machine_code)

    def test_raw_battery_probe_requires_cleanup_delay(self):
        machine_code = fixture_raw_battery_machine_code().replace(
            bytes.fromhex("CDED0C"), bytes.fromhex("CDEC0C")
        )

        with self.assertRaisesRegex(ValueError, "cleanup delay"):
            validate_machine_code("battery-raw", machine_code)

    def test_raw_link_probe_requires_samples_and_cleanup(self):
        with self.assertRaisesRegex(ValueError, "read port 0x00"):
            validate_machine_code(
                "link-raw",
                fixture_machine_code("link-raw"),
            )

    def test_keypad_settle_probe_requires_samples_and_cleanup(self):
        with self.assertRaisesRegex(ValueError, "read port 0x01"):
            validate_machine_code(
                "keypad-settle",
                fixture_machine_code("keypad-settle"),
            )

    def test_bus_timing_probe_requires_guarded_measurement_structure(self):
        with self.assertRaisesRegex(ValueError, "read port 0x02"):
            validate_machine_code(
                "bus-timing",
                fixture_machine_code("bus-timing"),
            )

    def test_prefix_m1_probe_requires_guarded_measurement_structure(self):
        with self.assertRaisesRegex(ValueError, "read port 0x02"):
            validate_machine_code(
                "prefix-m1",
                fixture_machine_code("prefix-m1"),
            )

    def test_physical_timer_probe_requires_guarded_measurement_structure(self):
        with self.assertRaisesRegex(ValueError, "read port 0x02"):
            validate_machine_code(
                "timer-physical",
                fixture_machine_code("timer-physical"),
            )

    def test_builder_refuses_existing_output_directory(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "refusing to reuse"),
        ):
            build_probes([], Path(directory))


if __name__ == "__main__":
    unittest.main()
