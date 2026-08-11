#!/usr/bin/env python3
"""Regression tests for physical hardware-probe program packaging."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_hardware_probes import (
    CREATE_APPVAR_COPY,
    PROBES,
    PROBE_START,
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
from tibasic_samples import T
from ti_program import asmprgm_body


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
        + b"\0"
        + bytes((APPVAR_TYPE,))
        + probe.appvar.encode("ascii")
        + b"\0"
        + frame
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
        self.assertEqual({1, 2, 3, 4, 5}, {probe.probe_id for probe in PROBES.values()})
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

    def test_builder_refuses_existing_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "refusing to reuse"):
                build_probes([], Path(directory))


if __name__ == "__main__":
    unittest.main()
