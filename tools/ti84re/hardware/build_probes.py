#!/usr/bin/env python3
"""Assemble and package physical TI-84 Plus hardware probes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ti84re.hardware.bus_timing import (
    BUS_TIMING_PROBE_CASES,
    BUS_TIMING_PROBE_MEASUREMENT_SIZE,
    PREFIX_M1_PROBE_CASES,
)
from ti84re.hardware.probe import (
    APPVAR_TYPE,
    KEYPAD_SETTLE_SAMPLE_COUNT,
    LINK_RAW_SAMPLE_COUNT,
    PROBE_FORMAT_VERSION,
    PROBE_MAGIC,
    USB_SNAPSHOT_PORTS,
)
from ti84re.tifiles.program import asmprgm_body, encode_program_file
from ti84re.hardware.timer import (
    PHYSICAL_TIMER_MEASUREMENT_SIZE,
    PHYSICAL_TIMER_STATE_PORTS,
)
from ti84re.paths import TOOLS

PROBE_DIR = TOOLS / "probes/hardware"
USER_MEM = 0x9D95
PROGRAM_LIMIT = 0xC000
PROBE_START = 0x9DB5
CREATE_APPVAR_COPY = b"\xEF\x6A\x4E\xE1\xC1\x13\x13\xED\xB0"
TIMING_PROBE_EXPECTED_INPUTS = {
    0x02: 2,
    0x03: 2,
    0x04: 3,
    0x15: 1,
    0x20: 2,
    0x29: 2,
    0x2A: 2,
    0x2B: 2,
    0x2C: 2,
    0x2E: 2,
    0x2F: 2,
    0x33: 2,
    0x34: 3,
    0x35: 8,
}
TIMING_PROBE_EXPECTED_OUTPUTS = {0x2E: 8, 0x33: 7, 0x34: 7, 0x35: 7}


@dataclass(frozen=True)
class ProbeDefinition:
    """Build and result schema for one calculator-side probe."""

    source_name: str
    program: str
    appvar: str
    probe_id: int
    payload_size: int
    defines: tuple[tuple[str, int], ...] = ()

    @property
    def source(self) -> Path:
        return PROBE_DIR / self.source_name


PROBES = {
    "md5-edge": ProbeDefinition(
        "md5-edge.asm", "HWPMD5", "HWPMD511", 1, 20
    ),
    "ram-alias": ProbeDefinition(
        "ram-alias.asm", "HWPRAM", "HWPRAM21", 2, 18
    ),
    "asic-snapshot": ProbeDefinition(
        "asic-snapshot.asm", "HWASIC", "HWPASIC1", 3, 11
    ),
    "usb-snapshot": ProbeDefinition(
        "usb-snapshot.asm",
        "HWPUSB",
        "HWPUSB01",
        5,
        len(USB_SNAPSHOT_PORTS),
    ),
    "battery-level": ProbeDefinition(
        "battery-level.asm", "HWBATT", "HWBATT01", 6, 30
    ),
    "battery-raw": ProbeDefinition(
        "battery-raw.asm", "HWBRAW", "HWBRAW01", 7, 30
    ),
    "link-raw": ProbeDefinition(
        "link-raw.asm", "HWLINK", "HWLINK01", 8,
        4 + LINK_RAW_SAMPLE_COUNT + 4 + 2,
    ),
    "keypad-settle": ProbeDefinition(
        "keypad-settle.asm", "HWKEYS", "HWKEYS01", 9,
        5 + 1 + KEYPAD_SETTLE_SAMPLE_COUNT + 5,
    ),
    "bus-timing": ProbeDefinition(
        "bus-timing.asm",
        "HWBUS",
        "HWBUS001",
        10,
        13
        + 1
        + len(BUS_TIMING_PROBE_CASES)
        * 2
        * BUS_TIMING_PROBE_MEASUREMENT_SIZE
        + 13,
    ),
    "prefix-m1": ProbeDefinition(
        "prefix-m1.asm",
        "HWPFX",
        "HWPFX001",
        11,
        13
        + 1
        + len(PREFIX_M1_PROBE_CASES)
        * 2
        * BUS_TIMING_PROBE_MEASUREMENT_SIZE
        + 13,
    ),
    "timer-physical": ProbeDefinition(
        "timer-physical.asm",
        "HWTMR",
        "HWTMR001",
        12,
        len(PHYSICAL_TIMER_STATE_PORTS) * 2
        + 1
        + PHYSICAL_TIMER_MEASUREMENT_SIZE,
    ),
    "rtc-rollover": ProbeDefinition(
        "rtc-rollover.asm", "HWPRTC", "HWPRTC01", 13, 19
    ),
    "mapper-overlays": ProbeDefinition(
        "mapper-overlays.asm", "HWPMAP", "HWPMAP01", 14, 47
    ),
    "lcd-controller": ProbeDefinition(
        "lcd-controller.asm", "HWPLCD", "HWPLCD01", 15, 43
    ),
    "interrupt-halt": ProbeDefinition(
        "interrupt-halt.asm", "HWPIRQ", "HWPIRQ01", 16, 21
    ),
    "exec-flash-07": ProbeDefinition(
        "execution-fetch.asm", "HWEF07", "HWEF0701", 4, 16,
        (("TARGET_KIND", 0), ("TARGET_SELECTOR", 0x07),
         ("SCAN_START", 0x4000), ("SCAN_LENGTH", 0x4000)),
    ),
    "exec-flash-08": ProbeDefinition(
        "execution-fetch.asm", "HWEF08", "HWEF0801", 4, 16,
        (("TARGET_KIND", 0), ("TARGET_SELECTOR", 0x08),
         ("SCAN_START", 0x4000), ("SCAN_LENGTH", 0x4000)),
    ),
    "exec-flash-09": ProbeDefinition(
        "execution-fetch.asm", "HWEF09", "HWEF0901", 4, 16,
        (("TARGET_KIND", 0), ("TARGET_SELECTOR", 0x09),
         ("SCAN_START", 0x4000), ("SCAN_LENGTH", 0x4000)),
    ),
    "exec-flash-29": ProbeDefinition(
        "execution-fetch.asm", "HWEF29", "HWEF2901", 4, 16,
        (("TARGET_KIND", 0), ("TARGET_SELECTOR", 0x29),
         ("SCAN_START", 0x4000), ("SCAN_LENGTH", 0x4000)),
    ),
    "exec-flash-2a": ProbeDefinition(
        "execution-fetch.asm", "HWEF2A", "HWEF2A01", 4, 16,
        (("TARGET_KIND", 0), ("TARGET_SELECTOR", 0x2A),
         ("SCAN_START", 0x4000), ("SCAN_LENGTH", 0x4000)),
    ),
    "exec-ram-81": ProbeDefinition(
        "execution-fetch.asm", "HWER81", "HWER8101", 4, 16,
        (("TARGET_KIND", 1), ("TARGET_SELECTOR", 0x81),
         ("SCAN_START", 0x4000), ("SCAN_LENGTH", 0x4000)),
    ),
    "exec-ram-82-chunk0": ProbeDefinition(
        "execution-fetch.asm", "HWER820", "HWER82A1", 4, 16,
        (("TARGET_KIND", 1), ("TARGET_SELECTOR", 0x82),
         ("SCAN_START", 0x4000), ("SCAN_LENGTH", 0x0400)),
    ),
    "exec-ram-82-chunk1": ProbeDefinition(
        "execution-fetch.asm", "HWER821", "HWER82B1", 4, 16,
        (("TARGET_KIND", 1), ("TARGET_SELECTOR", 0x82),
         ("SCAN_START", 0x4400), ("SCAN_LENGTH", 0x0400)),
    ),
    "exec-ram-83": ProbeDefinition(
        "execution-fetch.asm", "HWER83", "HWER8301", 4, 16,
        (("TARGET_KIND", 1), ("TARGET_SELECTOR", 0x83),
         ("SCAN_START", 0x4000), ("SCAN_LENGTH", 0x4000)),
    ),
    "exec-ram-84": ProbeDefinition(
        "execution-fetch.asm", "HWER84", "HWER8401", 4, 16,
        (("TARGET_KIND", 1), ("TARGET_SELECTOR", 0x84),
         ("SCAN_START", 0x4000), ("SCAN_LENGTH", 0x4000)),
    ),
}


def probe_definition(probe_name: str) -> ProbeDefinition:
    """Return one validated probe definition."""

    try:
        probe = PROBES[probe_name]
    except KeyError:
        choices = ", ".join(PROBES)
        raise ValueError(f"unknown probe {probe_name!r}; choose {choices}") from None
    if not 1 <= len(probe.program) <= 8:
        raise ValueError(f"program name for {probe_name} must be one through eight bytes")
    if len(probe.appvar) != 8:
        raise ValueError(f"result AppVar name for {probe_name} must be eight bytes")
    return probe


def initial_probe_payload(probe: ProbeDefinition) -> bytes:
    """Return the exact payload bytes expected at the end of an artifact."""

    if probe.probe_id in (14, 16):
        payload = bytearray(probe.payload_size)
        payload[9 if probe.probe_id == 14 else 6] = 0xFF
        return bytes(payload)
    if probe.probe_id != 4:
        return bytes(probe.payload_size)
    configuration = dict(probe.defines)
    payload = (
        bytes((configuration["TARGET_KIND"], configuration["TARGET_SELECTOR"]))
        + configuration["SCAN_START"].to_bytes(2, "little")
        + configuration["SCAN_LENGTH"].to_bytes(2, "little")
        + b"\xFF\xFF"
        + bytes(8)
    )
    if len(payload) != probe.payload_size:
        raise ValueError("execution-fetch definition has an invalid payload size")
    return payload


def validate_timing_probe_io(probe_name: str, machine_code: bytes) -> None:
    """Check shared timer-2 snapshot and restoration I/O counts."""

    for port, count in TIMING_PROBE_EXPECTED_INPUTS.items():
        if machine_code.count(bytes((0xDB, port))) != count:
            raise ValueError(
                f"{probe_name} must read port 0x{port:02X} exactly {count} times"
            )
    for port, count in TIMING_PROBE_EXPECTED_OUTPUTS.items():
        if machine_code.count(bytes((0xD3, port))) != count:
            raise ValueError(
                f"{probe_name} must write port 0x{port:02X} exactly {count} times"
            )


def validate_machine_code(probe_name: str, machine_code: bytes) -> None:
    """Check stable entry, result-frame, and AppVar-copy invariants."""

    probe = probe_definition(probe_name)
    if len(machine_code) < 3:
        raise ValueError(f"{probe_name} machine code is too short")
    if machine_code[0] != 0xC3:
        raise ValueError(f"{probe_name} must begin with JP start")
    entry = int.from_bytes(machine_code[1:3], "little")
    if entry != PROBE_START:
        raise ValueError(
            f"{probe_name} entry jump targets 0x{entry:04X}, expected 0x{PROBE_START:04X}"
        )
    if USER_MEM + len(machine_code) > PROGRAM_LIMIT:
        raise ValueError(f"{probe_name} extends beyond the 0xBFFF user-RAM bank")
    if CREATE_APPVAR_COPY not in machine_code:
        raise ValueError(
            f"{probe_name} does not skip the AppVar size word before copying"
        )
    appvar_marker = bytes((APPVAR_TYPE,)) + probe.appvar.encode("ascii")
    if machine_code.count(appvar_marker) != 1:
        raise ValueError(f"{probe_name} must contain its result AppVar name once")
    frame = (
        PROBE_MAGIC
        + bytes((PROBE_FORMAT_VERSION, probe.probe_id))
        + probe.payload_size.to_bytes(2, "little")
        + bytes(2)
        + initial_probe_payload(probe)
    )
    if not machine_code.endswith(frame):
        raise ValueError(
            f"{probe_name} does not end with its {probe.payload_size}-byte result frame"
        )
    if probe.probe_id == 4:
        configuration = dict(probe.defines)
        selector = configuration["TARGET_SELECTOR"]
        scan_start = configuration["SCAN_START"]
        scan_length = configuration["SCAN_LENGTH"]
        required = (
            (bytes((0x21, scan_start & 0xFF, scan_start >> 8)), "scan start"),
            (bytes((0x01, scan_length & 0xFF, scan_length >> 8)), "scan length"),
            (bytes.fromhex("E601"), "paired-mapping guard"),
        )
        for sequence, label in required:
            if sequence not in machine_code:
                raise ValueError(f"{probe_name} omits its {label}")
        selector_write = bytes((0x3E, selector, 0xD3, 0x06))
        if machine_code.count(selector_write) != 2:
            raise ValueError(f"{probe_name} must map and recheck its target selector")
        guarded_fetch = bytes.fromhex("D5E9")
        if machine_code.count(guarded_fetch) != 1:
            raise ValueError(f"{probe_name} must contain one guarded indirect fetch")
        create_call = bytes((0xCD, (USER_MEM + 3) & 0xFF, (USER_MEM + 3) >> 8))
        if (
            machine_code.count(create_call) != 1
            or machine_code.index(create_call) > machine_code.index(guarded_fetch)
        ):
            raise ValueError(f"{probe_name} must create its result before the fetch")
    if probe.probe_id == 5:
        for port in USB_SNAPSHOT_PORTS:
            direct_input = bytes((0xDB, port))
            if machine_code.count(direct_input) != 1:
                raise ValueError(
                    f"{probe_name} must read port 0x{port:02X} exactly once"
                )
    if probe.probe_id == 6:
        bcall = bytes.fromhex("EF2152")
        if machine_code.count(bcall) != 16:
            raise ValueError(
                f"{probe_name} must call _Chk_Batt_Level exactly 16 times"
            )
        for port in (0x04, 0x39, 0x3A):
            if machine_code.count(bytes((0xDB, port))) != 3:
                raise ValueError(
                    f"{probe_name} must read port 0x{port:02X} exactly three times"
                )
            if machine_code.count(bytes((0xD3, port))) != 1:
                raise ValueError(
                    f"{probe_name} must restore port 0x{port:02X} exactly once"
                )
        if machine_code.count(bytes.fromhex("FD7718")) != 1:
            raise ValueError(f"{probe_name} must restore traceFlags exactly once")
    if probe.probe_id == 7:
        local_calls = Counter(
            machine_code[index : index + 3]
            for index, opcode in enumerate(machine_code[:-2])
            if opcode == 0xCD
        )
        repeated_samplers = [
            call for call, count in local_calls.items() if count == 16
        ]
        if len(repeated_samplers) != 1:
            raise ValueError(
                f"{probe_name} must contain 16 identical sampler calls"
            )
        sampler_target = int.from_bytes(repeated_samplers[0][1:3], "little")
        if not USER_MEM <= sampler_target < USER_MEM + len(machine_code):
            raise ValueError(f"{probe_name} sampler call must target local code")
        for call, label in (
            (bytes.fromhex("CDEB0C"), "five-call delay worker"),
            (bytes.fromhex("CDED0C"), "cleanup delay"),
        ):
            if machine_code.count(call) != 1:
                raise ValueError(f"{probe_name} must contain one {label}")
        if bytes.fromhex("0605CDEB0C10") not in machine_code:
            raise ValueError(
                f"{probe_name} must loop over five calls to the delay worker"
            )
        expected_port_counts = {
            0x04: (3, 3),
            0x39: (4, 2),
            0x3A: (7, 5),
        }
        for port, (reads, writes) in expected_port_counts.items():
            if machine_code.count(bytes((0xDB, port))) != reads:
                raise ValueError(
                    f"{probe_name} must read port 0x{port:02X} exactly {reads} times"
                )
            if machine_code.count(bytes((0xD3, port))) != writes:
                raise ValueError(
                    f"{probe_name} must write port 0x{port:02X} exactly {writes} times"
                )
        for sequence, label in (
            (bytes.fromhex("F680D33A"), "GPIO bit-7 enable"),
            (bytes.fromhex("F610D33A3E40CDED0C"), "ROM cleanup pulse"),
            (bytes.fromhex("E6EFD33A"), "GPIO bit-4 clear"),
            (bytes.fromhex("E67FD33A"), "GPIO bit-7 clear"),
        ):
            if sequence not in machine_code:
                raise ValueError(f"{probe_name} omits its {label}")
        if machine_code.count(bytes.fromhex("FD7718")) != 1:
            raise ValueError(f"{probe_name} must restore traceFlags exactly once")
    if probe.probe_id == 8:
        expected_inputs = {0x00: 7, 0x02: 2, 0x03: 2, 0x04: 2, 0x20: 2}
        for port, count in expected_inputs.items():
            if machine_code.count(bytes((0xDB, port))) != count:
                raise ValueError(
                    f"{probe_name} must read port 0x{port:02X} exactly {count} times"
                )
        if machine_code.count(bytes.fromhex("D300")) != 9:
            raise ValueError(
                f"{probe_name} must contain eight sample writes and one cleanup write"
            )
        if machine_code.count(bytes.fromhex("3E03D30079D300")) != 4:
            raise ValueError(
                f"{probe_name} must precondition and drive four timed sample points"
            )
        for nop_count in (0, 1, 4, 16):
            sequence = (
                bytes.fromhex("3E03D30079D300")
                + bytes((0x00,)) * nop_count
                + bytes.fromhex("DB007723")
            )
            if machine_code.count(sequence) != 1:
                raise ValueError(
                    f"{probe_name} must contain one {nop_count}-NOP sample point"
                )
        if bytes.fromhex("0610") not in machine_code:
            raise ValueError(f"{probe_name} must repeat every point 16 times")
        initializes_write = bytes.fromhex("0E00") in machine_code
        stops_after_write_three = bytes.fromhex("0CCB51") in machine_code
        if not initializes_write or not stops_after_write_three:
            raise ValueError(f"{probe_name} must sweep link writes 0 through 3")
        if machine_code.count(bytes.fromhex("AFD300")) != 1:
            raise ValueError(f"{probe_name} must release both link lines once")
    if probe.probe_id == 9:
        expected_inputs = {0x01: 8, 0x02: 2, 0x03: 2, 0x04: 2, 0x15: 1, 0x20: 2}
        for port, count in expected_inputs.items():
            if machine_code.count(bytes((0xDB, port))) != count:
                raise ValueError(
                    f"{probe_name} must read port 0x{port:02X} exactly {count} times"
                )
        if machine_code.count(bytes.fromhex("D301")) != 10:
            raise ValueError(
                f"{probe_name} must contain nine sample/setup writes and one cleanup write"
            )
        if machine_code.count(bytes.fromhex("AFD30179D301")) != 4:
            raise ValueError(
                f"{probe_name} must precondition and select four timed sample points"
            )
        for nop_count in (0, 4, 16, 64):
            sequence = (
                bytes.fromhex("AFD30179D301")
                + bytes((0x00,)) * nop_count
                + bytes.fromhex("DB017723")
            )
            if machine_code.count(sequence) != 1:
                raise ValueError(
                    f"{probe_name} must contain one {nop_count}-NOP sample point"
                )
        if bytes.fromhex("0610") not in machine_code:
            raise ValueError(f"{probe_name} must repeat every point 16 times")
        if (
            bytes.fromhex("0EFE") not in machine_code
            or bytes.fromhex("CB01DA") not in machine_code
        ):
            raise ValueError(f"{probe_name} must rotate through all eight group writes")
        if bytes.fromhex("AFD301DB013C20") not in machine_code:
            raise ValueError(f"{probe_name} must wait for the launch key release")
        if bytes.fromhex("DB013C28") not in machine_code:
            raise ValueError(f"{probe_name} must wait for a held key or chord")
        if bytes.fromhex("11FFFF1B7AB320") not in machine_code:
            raise ValueError(f"{probe_name} must debounce the held chord")
        if machine_code.count(bytes.fromhex("3EFFD301")) != 1:
            raise ValueError(f"{probe_name} must unselect every keypad group once")
    if probe.probe_id == 10:
        validate_timing_probe_io(probe_name, machine_code)
        required_counts = (
            (bytes.fromhex("3E45D333AFD3343EFFD335"), 6, "timer setup"),
            (bytes.fromhex("010010"), 1, "4,096-iteration loop"),
            (bytes.fromhex("010040"), 5, "16,384-iteration loops"),
            (bytes.fromhex("CDE60C"), 1, "fixed-page helper call"),
            (bytes.fromhex("F5232BF1C9"), 1, "fixed-page helper signature"),
            (bytes.fromhex("16F0"), 1, "Flash reset-command byte"),
            (
                bytes.fromhex("DD7700DB34DD7701DB04DD7702"),
                1,
                "measurement result sequence",
            ),
            (bytes.fromhex("AFD333D334"), 1, "timer stop and acknowledge"),
        )
        for sequence, count, label in required_counts:
            if machine_code.count(sequence) != count:
                raise ValueError(
                    f"{probe_name} must contain its {label} exactly {count} times"
                )
    if probe.probe_id == 11:
        validate_timing_probe_io(probe_name, machine_code)
        required_counts = (
            (bytes.fromhex("3E45D333AFD3343EFFD335"), 6, "timer setup"),
            (bytes.fromhex("010030"), 6, "12,288-iteration loops"),
            (bytes.fromhex("000B78B120"), 1, "unprefixed loop body"),
            (bytes.fromhex("CB420B78B120"), 1, "CB-prefixed loop body"),
            (bytes.fromhex("ED440B78B120"), 1, "ED-prefixed loop body"),
            (bytes.fromhex("DD7C0B78B120"), 2, "DD-prefixed loop suffixes"),
            (bytes.fromhex("DDDD7C0B78B120"), 1, "repeated-DD loop body"),
            (bytes.fromhex("DDCB00460B78B120"), 1, "indexed-CB loop body"),
            (
                bytes.fromhex("DD7700DB34DD7701DB04DD7702"),
                1,
                "measurement result sequence",
            ),
            (bytes.fromhex("AFD333D334"), 1, "timer stop and acknowledge"),
        )
        for sequence, count, label in required_counts:
            if machine_code.count(sequence) != count:
                raise ValueError(
                    f"{probe_name} must contain its {label} exactly {count} times"
                )
    if probe.probe_id == 12:
        expected_inputs = {
            0x02: 2,
            0x03: 2,
            0x04: 8,
            0x15: 2,
            0x20: 3,
            0x2D: 2,
            0x2F: 2,
            0x30: 2,
            0x31: 6,
            0x32: 10,
            0x33: 2,
            0x34: 2,
            0x35: 9,
        }
        expected_outputs = {
            0x20: 2,
            0x2F: 2,
            0x30: 5,
            0x31: 7,
            0x32: 5,
            0x33: 5,
            0x34: 6,
            0x35: 6,
        }
        for port, count in expected_inputs.items():
            if machine_code.count(bytes((0xDB, port))) != count:
                raise ValueError(
                    f"{probe_name} must read port 0x{port:02X} exactly {count} times"
                )
        for port, count in expected_outputs.items():
            if machine_code.count(bytes((0xD3, port))) != count:
                raise ValueError(
                    f"{probe_name} must write port 0x{port:02X} exactly {count} times"
                )
        required_counts = (
            (
                bytes.fromhex(
                    "3E41D330AFD3313EFFD3323E45D333AFD3343EFFD335"
                ),
                1,
                "0x41 crystal-divisor case",
            ),
            (bytes.fromhex("3E4BD32F"), 1, "fixed port-0x2F setup"),
            (
                bytes.fromhex(
                    "3EE0D3303E01D3313EFAD3323E45D333AFD3343EFFD335"
                ),
                1,
                "0xE0 mode-3 case",
            ),
            (
                bytes.fromhex(
                    "3E45D330AFD331D3323E46D333AFD3343E1FD335"
                ),
                1,
                "counter-zero case",
            ),
            (
                bytes.fromhex(
                    "3E45D3303E01D3313E04D3323E45D333AFD3343E08D335"
                ),
                1,
                "first/second-expiry case",
            ),
            (bytes.fromhex("01FFFF"), 3, "bounded polling loops"),
        )
        for sequence, count, label in required_counts:
            if machine_code.count(sequence) != count:
                raise ValueError(
                    f"{probe_name} must contain its {label} exactly {count} times"
                )
    if probe.probe_id == 13:
        expected_inputs = {0x40: 2, 0x45: 3, 0x46: 2, 0x47: 2, 0x48: 2}
        for port, count in expected_inputs.items():
            if machine_code.count(bytes((0xDB, port))) != count:
                raise ValueError(
                    f"{probe_name} must read port 0x{port:02X} exactly {count} times"
                )
        for port in range(0x40, 0x49):
            if bytes((0xD3, port)) in machine_code:
                raise ValueError(
                    f"{probe_name} must not write RTC port 0x{port:02X}"
                )
        for sequence, label in (
            (bytes.fromhex("ED57E2"), "enabled-interrupt entry guard"),
            (bytes.fromhex("E60128"), "enabled-RTC entry guard"),
            (bytes.fromhex("DB45FEFF20"), "low-byte polling loop"),
            (bytes.fromhex("F3"), "rollover-window interrupt mask"),
            (bytes.fromhex("FB"), "interrupt restoration"),
            (bytes.fromhex("E5DDE1"), "AppVar-resident verification frame"),
            (bytes.fromhex("EF7249"), "verification-code display"),
        ):
            if sequence not in machine_code:
                raise ValueError(f"{probe_name} omits its {label}")
    if probe.probe_id == 14:
        for sequence, label in (
            (bytes.fromhex("3E13D327"), "port-0x27 0xFB40 boundary"),
            (bytes.fromhex("3E01D328"), "port-0x28 64-byte boundary"),
            (bytes.fromhex("3E07D304"), "paired-mode transition"),
            (bytes.fromhex("3E06D304"), "independent-mode restoration"),
            (bytes.fromhex("3E82D306"), "paired RAM backing"),
            (bytes.fromhex("3E81D307"), "stable paired-C mapping"),
            (bytes.fromhex("F5232BF1C9"), "fixed-page helper signature"),
            (bytes.fromhex("DD2A"), "AppVar-resident verification frame"),
        ):
            if sequence not in machine_code:
                raise ValueError(f"{probe_name} omits its {label}")
        if bytes.fromhex("EF7249") not in machine_code:
            raise ValueError(f"{probe_name} must display its verification code")
        if machine_code.find(bytes.fromhex("CD989D")) > machine_code.find(
            bytes.fromhex("323FFB")
        ):
            raise ValueError(f"{probe_name} must create its pending result first")
    if probe.probe_id == 15:
        for port in (0x02, 0x03, 0x20, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F):
            if bytes((0xD3, port)) in machine_code:
                raise ValueError(
                    f"{probe_name} must not write protected port 0x{port:02X}"
                )
        for sequence, label in (
            (bytes.fromhex("01FFFFDB02CB4F"), "bounded ASIC-ready poll"),
            (bytes.fromhex("3E07"), "column-increment command"),
            (bytes.fromhex("3E2E"), "column-14 start command"),
            (bytes.fromhex("0E3F"), "read-only column-31 command"),
            (bytes.fromhex("E5DDE1"), "AppVar-resident verification frame"),
            (bytes.fromhex("EF7249"), "verification-code display"),
        ):
            if sequence not in machine_code:
                raise ValueError(f"{probe_name} omits its {label}")
    if probe.probe_id == 16:
        for sequence, label in (
            (bytes.fromhex("ED5E"), "IM2 installation"),
            (bytes.fromhex("ED56"), "IM1 restoration"),
            (bytes.fromhex("76"), "HALT experiment"),
            (bytes.fromhex("ED4D"), "RETI handler return"),
            (bytes.fromhex("3E0AD303"), "powered-HALT watchdog mask"),
            (bytes.fromhex("3E45D3303E02D3313E01D332"), "programmable timer setup"),
            (bytes.fromhex("FDE5E1"), "IY context guard"),
            (bytes.fromhex("FDCB1646"), "canonical OS interrupt-mask restore"),
            (bytes.fromhex("1833DB04CB7F"), "OS IM1 vector signature"),
            (bytes.fromhex("DD2A"), "AppVar-resident verification frame"),
            (bytes.fromhex("EF7249"), "verification-code display"),
        ):
            if sequence not in machine_code:
                raise ValueError(f"{probe_name} omits its {label}")
        if machine_code.find(bytes.fromhex("CD989D")) > machine_code.find(
            bytes.fromhex("ED5E")
        ):
            raise ValueError(f"{probe_name} must create its pending result first")


def package_probe(
    probe_name: str, machine_code: bytes
) -> tuple[bytes, dict[str, object]]:
    """Package assembled bytes as an ``AsmPrgm`` link file."""

    probe = probe_definition(probe_name)
    validate_machine_code(probe_name, machine_code)
    program = encode_program_file(
        probe.program,
        asmprgm_body(machine_code),
        comment="Codex TI-BASIC trace sample",
    )
    metadata: dict[str, object] = {
        "probe": probe_name,
        "probe_id": probe.probe_id,
        "source": f"tools/probes/hardware/{probe.source_name}",
        "program": probe.program,
        "result_appvar": probe.appvar,
        "payload_size": probe.payload_size,
        "defines": {name: value for name, value in probe.defines},
        "machine_code_size": len(machine_code),
        "machine_code_sha256": hashlib.sha256(machine_code).hexdigest(),
        "program_file_size": len(program),
        "program_file_sha256": hashlib.sha256(program).hexdigest(),
    }
    return program, metadata


def assemble_machine_code(
    probe_name: str,
    *,
    spasm: str = "spasm",
) -> bytes:
    """Assemble and validate one named physical-probe machine image."""

    probe = probe_definition(probe_name)
    defines = [*probe.defines]
    defines.extend(
        (f"APPVAR_{index}", byte)
        for index, byte in enumerate(probe.appvar.encode("ascii"))
    )
    with tempfile.TemporaryDirectory(prefix="ti84-hwprobe-") as temp_dir:
        raw_path = Path(temp_dir) / f"{probe_name}.bin"
        completed = subprocess.run(
            [
                spasm,
                "-N",
                "-I",
                str(PROBE_DIR),
                *(f"-D{name}=${value:X}" for name, value in defines),
                str(probe.source),
                str(raw_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"SPASM failed for {probe_name}: {detail}")
        machine_code = raw_path.read_bytes()
    validate_machine_code(probe_name, machine_code)
    return machine_code


def assemble_probe(
    probe_name: str,
    *,
    spasm: str = "spasm",
) -> tuple[bytes, dict[str, object]]:
    """Assemble one named probe and return its ``.8xp`` plus metadata."""

    machine_code = assemble_machine_code(probe_name, spasm=spasm)
    return package_probe(probe_name, machine_code)


def build_probes(
    probe_names: list[str], output_dir: Path, *, spasm: str = "spasm"
) -> dict[str, object]:
    """Build probes into *output_dir* and return their stable manifest."""

    if output_dir.exists():
        raise ValueError(f"refusing to reuse existing output directory {output_dir}")
    artifacts = []
    for probe_name in probe_names:
        program, row = assemble_probe(probe_name, spasm=spasm)
        output_name = f"{row['program']}.8xp"
        row["output"] = output_name
        artifacts.append((program, row))
    output_dir.mkdir(parents=True)
    for program, row in artifacts:
        (output_dir / row["output"]).write_bytes(program)
    rows = [row for _program, row in artifacts]
    manifest: dict[str, object] = {"format": 1, "probes": rows}
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "probe",
        nargs="*",
        choices=PROBES,
        help="probe to build (default: all)",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--spasm", default="spasm")
    args = parser.parse_args()
    try:
        manifest = build_probes(
            list(args.probe or PROBES), args.output_dir, spasm=args.spasm
        )
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
