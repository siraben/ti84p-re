"""Versioned result frames and TI variable files for physical hardware probes."""

from __future__ import annotations

import binascii
import hashlib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from bus_timing import (
    BUS_TIMING_PROBE_CASES,
    BUS_TIMING_PROBE_MEASUREMENT_SIZE,
    PREFIX_M1_PROBE_CASES,
    decode_bus_timing_probe_measurements,
    decode_prefix_m1_probe_measurements,
)
from link_port import port_read_value
from ram_topology import decode_ram_alias_payload
from timer_hardware import (
    PHYSICAL_TIMER_MEASUREMENT_SIZE,
    PHYSICAL_TIMER_STATE_PORTS,
    decode_physical_timer_measurements,
)

TI_SIGNATURE = b"**TI83F*\x1a\x0a\x00"
PROBE_MAGIC = b"HWP1"
PROBE_FORMAT_VERSION = 1
APPVAR_TYPE = 0x15
USB_SNAPSHOT_PORTS = (
    0x49,
    0x4A,
    0x4B,
    0x4C,
    0x4D,
    0x4F,
    0x50,
    0x51,
    0x52,
    0x54,
    0x55,
    0x56,
    0x57,
    0x5A,
    0x5B,
)
LINK_RAW_WRITES = (0, 1, 2, 3)
LINK_RAW_DELAY_NOPS = (0, 1, 4, 16)
LINK_RAW_TRIALS = 16
LINK_RAW_SAMPLE_COUNT = (
    len(LINK_RAW_WRITES) * len(LINK_RAW_DELAY_NOPS) * LINK_RAW_TRIALS
)
KEYPAD_SETTLE_GROUP_WRITES = (0xFE, 0xFD, 0xFB, 0xF7, 0xEF, 0xDF, 0xBF, 0x7F)
KEYPAD_SETTLE_DELAY_NOPS = (0, 4, 16, 64)
KEYPAD_SETTLE_TRIALS = 16
KEYPAD_SETTLE_HOLD_LOOP_ITERATIONS = 0xFFFF
KEYPAD_SETTLE_HOLD_LOOP_BASE_T_STATES = (
    (KEYPAD_SETTLE_HOLD_LOOP_ITERATIONS - 1) * 26 + 21
)
KEYPAD_SETTLE_SAMPLE_COUNT = (
    len(KEYPAD_SETTLE_GROUP_WRITES)
    * len(KEYPAD_SETTLE_DELAY_NOPS)
    * KEYPAD_SETTLE_TRIALS
)
PROBE_NAMES = {
    1: "md5-edge",
    2: "ram-alias",
    3: "asic-snapshot",
    4: "execution-fetch",
    5: "usb-snapshot",
    6: "battery-level",
    7: "battery-raw",
    8: "link-raw",
    9: "keypad-settle",
    10: "bus-timing",
    11: "prefix-m1",
    12: "timer-physical",
    13: "rtc-rollover",
    14: "mapper-overlays",
    15: "lcd-controller",
    16: "interrupt-halt",
    17: "lcd-hidden-lab",
}


class ProbeFormatError(ValueError):
    """A probe frame or TI variable container is malformed."""


@dataclass(frozen=True)
class ProbeFrame:
    """One decoded calculator-side hardware measurement."""

    probe_id: int
    asic_id: int
    status: int
    payload: bytes
    format_version: int = PROBE_FORMAT_VERSION

    def encode(self) -> bytes:
        """Return the stable binary representation stored in an AppVar."""

        if self.format_version != PROBE_FORMAT_VERSION:
            raise ValueError(
                f"unsupported probe format version {self.format_version}"
            )
        if not 0 <= self.probe_id <= 0xFF:
            raise ValueError("probe ID must be a byte")
        if not 0 <= self.asic_id <= 0xFF or not 0 <= self.status <= 0xFF:
            raise ValueError("ASIC identity and status must be bytes")
        if len(self.payload) > 0xFFFF:
            raise ValueError("probe payload is too large")
        return (
            PROBE_MAGIC
            + bytes((self.format_version, self.probe_id))
            + len(self.payload).to_bytes(2, "little")
            + bytes((self.asic_id, self.status))
            + self.payload
        )


def probe_verification_code(frame: ProbeFrame) -> int:
    """Return the decimal code displayed after a guarded physical run."""

    return binascii.crc_hqx(frame.encode(), 0xFFFF)


@dataclass(frozen=True)
class TiVariable:
    """One variable entry decoded from a single-entry TI link file."""

    variable_type: int
    name: str
    version: int
    archived: bool
    data: bytes
    comment: str


def encode_ti_variable_file(
    variable_type: int,
    name: str,
    data: bytes,
    *,
    version: int = 0,
    archived: bool = False,
    comment: str = "Codex hardware probe",
) -> bytes:
    """Return a single-entry TI-83+/84+ variable file."""

    if not 0 <= variable_type <= 0xFF or not 0 <= version <= 0xFF:
        raise ValueError("variable type and version must be bytes")
    try:
        calc_name = name.upper().encode("ascii")
        comment_bytes = comment.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("variable name and comment must be ASCII") from error
    if not 1 <= len(calc_name) <= 8:
        raise ValueError("variable name must contain one through eight characters")
    if len(data) > 0xFFFF:
        raise ValueError("variable data is too large")
    entry = bytearray()
    entry += (13).to_bytes(2, "little")
    entry += len(data).to_bytes(2, "little")
    entry += bytes((variable_type,))
    entry += calc_name.ljust(8, b"\0")
    entry += bytes((version, 0x80 if archived else 0x00))
    entry += len(data).to_bytes(2, "little")
    entry += data
    header = TI_SIGNATURE + comment_bytes[:42].ljust(42, b" ")
    payload = header + len(entry).to_bytes(2, "little") + entry
    return payload + (sum(entry) & 0xFFFF).to_bytes(2, "little")


def encode_probe_appvar(name: str, frame: ProbeFrame) -> bytes:
    """Wrap a probe frame as an exported AppVar link file."""

    payload = frame.encode()
    return encode_ti_variable_file(
        APPVAR_TYPE,
        name,
        len(payload).to_bytes(2, "little") + payload,
    )


def decode_probe_frame(data: bytes) -> ProbeFrame:
    """Decode and validate one ``HWP1`` frame."""

    if len(data) < 10:
        raise ProbeFormatError("probe frame is shorter than its 10-byte header")
    if data[:4] != PROBE_MAGIC:
        raise ProbeFormatError("probe frame has the wrong magic")
    version = data[4]
    if version != PROBE_FORMAT_VERSION:
        raise ProbeFormatError(f"unsupported probe format version {version}")
    payload_size = int.from_bytes(data[6:8], "little")
    if len(data) != 10 + payload_size:
        raise ProbeFormatError(
            f"probe payload length says {payload_size}, got {len(data) - 10}"
        )
    return ProbeFrame(
        format_version=version,
        probe_id=data[5],
        asic_id=data[8],
        status=data[9],
        payload=data[10:],
    )


def decode_ti_variable_file(blob: bytes) -> TiVariable:
    """Decode a single-entry TI-83+/84+ variable file and verify its checksum."""

    if len(blob) < 57 or blob[:11] != TI_SIGNATURE:
        raise ProbeFormatError("not a TI-83+/84+ variable file")
    comment = blob[11:53].rstrip(b" \0").decode("ascii", errors="replace")
    entry_size = int.from_bytes(blob[53:55], "little")
    if len(blob) != 55 + entry_size + 2:
        raise ProbeFormatError("TI variable entry length does not match the file")
    entry = blob[55:-2]
    expected_checksum = int.from_bytes(blob[-2:], "little")
    if sum(entry) & 0xFFFF != expected_checksum:
        raise ProbeFormatError("TI variable checksum mismatch")
    if len(entry) < 17:
        raise ProbeFormatError("TI variable entry is truncated")
    header_size = int.from_bytes(entry[0:2], "little")
    if header_size != 13:
        raise ProbeFormatError(f"unsupported TI variable header size {header_size}")
    size_before = int.from_bytes(entry[2:4], "little")
    size_after = int.from_bytes(entry[15:17], "little")
    if size_before != size_after or len(entry) != 17 + size_after:
        raise ProbeFormatError("TI variable data lengths disagree")
    raw_name = entry[5:13].split(b"\0", 1)[0]
    try:
        name = raw_name.decode("ascii")
    except UnicodeDecodeError as error:
        raise ProbeFormatError("TI variable name is not ASCII") from error
    archive_flag = entry[14]
    if archive_flag not in (0x00, 0x80):
        raise ProbeFormatError(
            f"unsupported TI variable archive flag 0x{archive_flag:02X}"
        )
    return TiVariable(
        variable_type=entry[4],
        name=name,
        version=entry[13],
        archived=archive_flag == 0x80,
        data=entry[17:],
        comment=comment,
    )


def decode_probe_appvar(blob: bytes) -> tuple[TiVariable, ProbeFrame]:
    """Decode an exported probe AppVar, including its internal size word."""

    variable = decode_ti_variable_file(blob)
    if variable.variable_type != APPVAR_TYPE:
        raise ProbeFormatError(
            f"expected AppVar type 0x{APPVAR_TYPE:02X}, got 0x{variable.variable_type:02X}"
        )
    if len(variable.data) < 2:
        raise ProbeFormatError("AppVar is missing its internal size word")
    size = int.from_bytes(variable.data[:2], "little")
    payload = variable.data[2:]
    if size != len(payload):
        raise ProbeFormatError(
            f"AppVar size word says {size}, got {len(payload)} bytes"
        )
    return variable, decode_probe_frame(payload)


def _decode_restoring_samples(
    frame: ProbeFrame,
    *,
    payload_name: str,
    allowed_samples: range,
    samples_key: str,
    histogram_key: str,
    stable_key: str,
    post_key: str,
) -> tuple[dict[str, object], tuple[int, ...]]:
    """Decode the state-and-16-samples layout shared by battery probes."""

    if len(frame.payload) != 30:
        raise ProbeFormatError(
            f"{payload_name} payload must contain 30 bytes, "
            f"got {len(frame.payload)}"
        )
    samples = tuple(frame.payload[4:20])
    if any(value not in allowed_samples for value in samples):
        bounds = f"{allowed_samples.start} through {allowed_samples.stop - 1}"
        raise ProbeFormatError(f"{payload_name} samples must be in range {bounds}")
    counts = Counter(samples)
    pre = frame.payload[0:4]
    post = frame.payload[20:25]
    restored = frame.payload[25:29]
    report: dict[str, object] = {
        "pre": {
            "port_0x04": f"0x{pre[0]:02X}",
            "port_0x39": f"0x{pre[1]:02X}",
            "port_0x3A": f"0x{pre[2]:02X}",
            "trace_flags": f"0x{pre[3]:02X}",
            "status": f"0x{frame.status:02X}",
        },
        samples_key: list(samples),
        histogram_key: {
            str(value): counts.get(value, 0) for value in allowed_samples
        },
        stable_key: samples[0] if len(counts) == 1 else None,
        post_key: {
            "status": f"0x{post[0]:02X}",
            "port_0x04": f"0x{post[1]:02X}",
            "port_0x39": f"0x{post[2]:02X}",
            "port_0x3A": f"0x{post[3]:02X}",
            "trace_flags": f"0x{post[4]:02X}",
        },
        "restored": {
            "port_0x04": f"0x{restored[0]:02X}",
            "port_0x39": f"0x{restored[1]:02X}",
            "port_0x3A": f"0x{restored[2]:02X}",
            "trace_flags": f"0x{restored[3]:02X}",
            "status": f"0x{frame.payload[29]:02X}",
        },
        "cleanup_matches": restored == pre,
    }
    return report, samples


TIMING_PROBE_STATE_PORTS = (
    0x02,
    0x03,
    0x04,
    0x20,
    0x29,
    0x2A,
    0x2B,
    0x2C,
    0x2E,
    0x2F,
    0x33,
    0x34,
    0x35,
)


def _decode_timing_probe(
    frame: ProbeFrame,
    *,
    payload_name: str,
    case_count: int,
    outcome_names: dict[int, str],
    measurement_decoder: Callable[[bytes], dict[str, object]],
) -> dict[str, object]:
    """Decode the shared state, outcome, sample, and restoration layout."""

    measurement_size = case_count * 2 * BUS_TIMING_PROBE_MEASUREMENT_SIZE
    expected_size = len(TIMING_PROBE_STATE_PORTS) * 2 + 1 + measurement_size
    if len(frame.payload) != expected_size:
        raise ProbeFormatError(
            f"{payload_name} payload must contain {expected_size} bytes, "
            f"got {len(frame.payload)}"
        )
    pre = frame.payload[: len(TIMING_PROBE_STATE_PORTS)]
    outcome_code = frame.payload[len(TIMING_PROBE_STATE_PORTS)]
    measurement_start = len(TIMING_PROBE_STATE_PORTS) + 1
    measurement_end = measurement_start + measurement_size
    raw_measurements = frame.payload[measurement_start:measurement_end]
    post = frame.payload[measurement_end:]

    def port_report(values: bytes) -> dict[str, str]:
        return {
            f"0x{port:02X}": f"0x{value:02X}"
            for port, value in zip(TIMING_PROBE_STATE_PORTS, values, strict=True)
        }

    try:
        measurements = (
            measurement_decoder(raw_measurements) if outcome_code == 0 else None
        )
    except ValueError as error:
        raise ProbeFormatError(str(error)) from error
    return {
        "outcome_code": outcome_code,
        "outcome": outcome_names.get(outcome_code, f"unknown-{outcome_code}"),
        "pre": port_report(pre),
        "measurements": measurements,
        "post": port_report(post),
        "restored": {
            "port_0x2E": post[8] == pre[8],
            "timer_source": post[10] == pre[10],
            "timer_mode": post[11] == pre[11],
            "timer_counter": post[12] == pre[12],
        },
        "speed_unchanged": post[3] == pre[3],
        "timing_gates_unchanged": post[4:8] == pre[4:8],
    }


def _decode_physical_timer_probe(frame: ProbeFrame) -> dict[str, object]:
    """Decode the guarded programmable-timer physical-probe payload."""

    state_size = len(PHYSICAL_TIMER_STATE_PORTS)
    expected_size = state_size * 2 + 1 + PHYSICAL_TIMER_MEASUREMENT_SIZE
    if len(frame.payload) != expected_size:
        raise ProbeFormatError(
            "timer-physical payload must contain "
            f"{expected_size} bytes, got {len(frame.payload)}"
        )
    pre = frame.payload[:state_size]
    outcome_code = frame.payload[state_size]
    measurement_start = state_size + 1
    measurement_end = measurement_start + PHYSICAL_TIMER_MEASUREMENT_SIZE
    post = frame.payload[measurement_end:]

    def port_report(values: bytes) -> dict[str, str]:
        return {
            f"0x{port:02X}": f"0x{value:02X}"
            for port, value in zip(
                PHYSICAL_TIMER_STATE_PORTS, values, strict=True
            )
        }

    try:
        measurements = (
            decode_physical_timer_measurements(
                frame.payload[measurement_start:measurement_end]
            )
            if outcome_code == 0
            else None
        )
    except ValueError as error:
        raise ProbeFormatError(str(error)) from error
    outcome_names = {
        0: "completed",
        1: "timer-1-source-active",
        2: "timer-1-mode-active",
        3: "timer-2-source-active",
        4: "timer-2-mode-active",
        5: "timer-completion-pending",
        6: "measurement-timeout",
    }
    return {
        "outcome_code": outcome_code,
        "outcome": outcome_names.get(outcome_code, f"unknown-{outcome_code}"),
        "pre": port_report(pre),
        "measurements": measurements,
        "post": port_report(post),
        "restored": {
            "speed": post[4] == pre[4],
            "power_control": post[5] == pre[5],
            "port_0x2F": post[6] == pre[6],
            "timer_1": post[7:10] == pre[7:10],
            "timer_2": post[10:13] == pre[10:13],
            "interrupt_mask": post[1] == pre[1],
        },
    }


def decode_probe_measurements(frame: ProbeFrame) -> dict[str, object]:
    """Interpret the fixed payload for a known probe ID."""

    if frame.probe_id == 1:
        if len(frame.payload) != 20:
            raise ProbeFormatError(
                f"MD5 edge payload must contain 20 bytes, got {len(frame.payload)}"
            )

        def word(offset: int) -> str:
            value = int.from_bytes(frame.payload[offset : offset + 4], "little")
            return f"0x{value:08X}"

        return {
            "valid_result": word(0),
            "undefined_reads": frame.payload[4:8].hex().upper(),
            "fifth_write_result": word(8),
            "masked_controls_result": word(12),
            "mixed_result": word(16),
        }
    if frame.probe_id == 2:
        try:
            return decode_ram_alias_payload(frame.payload).to_dict()
        except ValueError as error:
            raise ProbeFormatError(str(error)) from error
    if frame.probe_id == 3:
        if len(frame.payload) != 11:
            raise ProbeFormatError(
                f"ASIC snapshot payload must contain 11 bytes, got {len(frame.payload)}"
            )
        ports = (0x04, 0x20, 0x21, 0x29, 0x2A, 0x2B, 0x2C, 0x2E, 0x2F, 0x39, 0x3A)
        return {
            "registers": {
                f"0x{port:02X}": f"0x{value:02X}"
                for port, value in zip(ports, frame.payload, strict=True)
            }
        }
    if frame.probe_id == 4:
        if len(frame.payload) != 16:
            raise ProbeFormatError(
                "execution-fetch payload must contain 16 bytes, "
                f"got {len(frame.payload)}"
            )
        kind_names = {0: "flash", 1: "ram"}
        outcome_names = {
            0: "pending-reset-or-interruption",
            1: "returned",
            2: "no-ret-found",
            3: "target-changed-before-fetch",
            4: "unsupported-paired-mapping",
        }
        kind = frame.payload[0]
        outcome = frame.payload[8]
        return {
            "target_kind": kind_names.get(kind, f"unknown-{kind}"),
            "target_selector": f"0x{frame.payload[1]:02X}",
            "scan_start": f"0x{int.from_bytes(frame.payload[2:4], 'little'):04X}",
            "scan_length": f"0x{int.from_bytes(frame.payload[4:6], 'little'):04X}",
            "target_address": f"0x{int.from_bytes(frame.payload[6:8], 'little'):04X}",
            "outcome": outcome_names.get(outcome, f"unknown-{outcome}"),
            "registers": {
                f"0x{port:02X}": f"0x{value:02X}"
                for port, value in zip(
                    (0x04, 0x06, 0x21, 0x22, 0x23, 0x25, 0x26),
                    frame.payload[9:16],
                    strict=True,
                )
            },
        }
    if frame.probe_id == 5:
        if len(frame.payload) != len(USB_SNAPSHOT_PORTS):
            raise ProbeFormatError(
                "USB snapshot payload must contain "
                f"{len(USB_SNAPSHOT_PORTS)} bytes, got {len(frame.payload)}"
            )
        return {
            "registers": {
                f"0x{port:02X}": f"0x{value:02X}"
                for port, value in zip(
                    USB_SNAPSHOT_PORTS, frame.payload, strict=True
                )
            }
        }
    if frame.probe_id == 6:
        report, _levels = _decode_restoring_samples(
            frame,
            payload_name="battery-level",
            allowed_samples=range(5),
            samples_key="level_samples",
            histogram_key="sample_histogram",
            stable_key="stable_level",
            post_key="post_bcall",
        )
        return report
    if frame.probe_id == 7:
        report, masks = _decode_restoring_samples(
            frame,
            payload_name="battery-raw",
            allowed_samples=range(16),
            samples_key="mask_samples",
            histogram_key="mask_histogram",
            stable_key="stable_mask",
            post_key="post_sequence",
        )
        selectors = (0x06, 0x46, 0x86, 0xC6)
        report["selector_pass_counts"] = {
            f"0x{selector:02X}": sum(
                bool(mask & (1 << bit)) for mask in masks
            )
            for bit, selector in enumerate(selectors)
        }
        return report
    if frame.probe_id == 8:
        expected_size = 4 + LINK_RAW_SAMPLE_COUNT + 4 + 2
        if len(frame.payload) != expected_size:
            raise ProbeFormatError(
                "link-raw payload must contain "
                f"{expected_size} bytes, got {len(frame.payload)}"
            )
        pre = frame.payload[:4]
        raw_samples = frame.payload[4 : 4 + LINK_RAW_SAMPLE_COUNT]
        post = frame.payload[4 + LINK_RAW_SAMPLE_COUNT : -2]
        cleanup_port00 = frame.payload[-2]
        final_status = frame.payload[-1]
        rows = []
        for write_index, write_value in enumerate(LINK_RAW_WRITES):
            expected = port_read_value(write_value, 0)
            for delay_index, delay_nops in enumerate(LINK_RAW_DELAY_NOPS):
                values = tuple(
                    raw_samples[
                        (
                            (write_index * LINK_RAW_TRIALS + trial)
                            * len(LINK_RAW_DELAY_NOPS)
                        )
                        + delay_index
                    ]
                    for trial in range(LINK_RAW_TRIALS)
                )
                counts = Counter(values)
                rows.append(
                    {
                        "write": write_value,
                        "delay_nops": delay_nops,
                        "samples": list(values),
                        "histogram": {
                            f"0x{value:02X}": count
                            for value, count in sorted(counts.items())
                        },
                        "stable_value": values[0] if len(counts) == 1 else None,
                        "expected_disconnected": expected,
                        "disconnected_match_count": values.count(expected),
                        "low_line_match_count": sum(
                            (value & 0x03) == (expected & 0x03)
                            for value in values
                        ),
                        "local_latch_match_count": sum(
                            ((value >> 4) & 0x03) == write_value
                            for value in values
                        ),
                    }
                )
        return {
            "pre": {
                "port_0x00": f"0x{pre[0]:02X}",
                "port_0x03": f"0x{pre[1]:02X}",
                "port_0x04": f"0x{pre[2]:02X}",
                "port_0x20": f"0x{pre[3]:02X}",
                "status": f"0x{frame.status:02X}",
            },
            "sample_order": "write-major, trial-major, delay-major",
            "trials_per_point": LINK_RAW_TRIALS,
            "points": rows,
            "disconnected_contract_matches": all(
                row["disconnected_match_count"] == LINK_RAW_TRIALS
                for row in rows
            ),
            "post": {
                "port_0x00": f"0x{post[0]:02X}",
                "port_0x03": f"0x{post[1]:02X}",
                "port_0x04": f"0x{post[2]:02X}",
                "port_0x20": f"0x{post[3]:02X}",
            },
            "cleanup": {
                "port_0x00": f"0x{cleanup_port00:02X}",
                "status": f"0x{final_status:02X}",
            },
            "pre_latch_was_idle": ((pre[0] >> 4) & 0x03) == 0,
            "cleanup_idle_matches": cleanup_port00 == port_read_value(0, 0),
        }
    if frame.probe_id == 9:
        expected_size = 5 + 1 + KEYPAD_SETTLE_SAMPLE_COUNT + 5
        if len(frame.payload) != expected_size:
            raise ProbeFormatError(
                "keypad-settle payload must contain "
                f"{expected_size} bytes, got {len(frame.payload)}"
            )
        pre = frame.payload[:5]
        trigger = frame.payload[5]
        raw_samples = frame.payload[6 : 6 + KEYPAD_SETTLE_SAMPLE_COUNT]
        post = frame.payload[-5:]
        rows = []
        delay_count = len(KEYPAD_SETTLE_DELAY_NOPS)
        for group_index, group_write in enumerate(KEYPAD_SETTLE_GROUP_WRITES):
            values_by_delay = []
            for delay_index in range(delay_count):
                values_by_delay.append(
                    tuple(
                        raw_samples[
                            (
                                (group_index * KEYPAD_SETTLE_TRIALS + trial)
                                * delay_count
                            )
                            + delay_index
                        ]
                        for trial in range(KEYPAD_SETTLE_TRIALS)
                    )
                )
            reference_values = values_by_delay[-1]
            for delay_nops, values in zip(
                KEYPAD_SETTLE_DELAY_NOPS, values_by_delay, strict=True
            ):
                counts = Counter(values)
                stable_value = values[0] if len(counts) == 1 else None
                reference_matches = sum(
                    value == reference
                    for value, reference in zip(
                        values, reference_values, strict=True
                    )
                )
                extra_low = sum(
                    value != reference and (value | reference) == reference
                    for value, reference in zip(
                        values, reference_values, strict=True
                    )
                )
                rows.append(
                    {
                        "group_write": group_write,
                        "selected_group": group_index,
                        "delay_nops": delay_nops,
                        "samples": list(values),
                        "histogram": {
                            f"0x{value:02X}": count
                            for value, count in sorted(counts.items())
                        },
                        "stable_value": stable_value,
                        "stable_pressed_columns": (
                            (~stable_value) & 0xFF
                            if stable_value is not None
                            else None
                        ),
                        "reference_64_nop_match_count": reference_matches,
                        "extra_low_vs_64_nop_count": extra_low,
                        "other_difference_vs_64_nop_count": (
                            KEYPAD_SETTLE_TRIALS
                            - reference_matches
                            - extra_low
                        ),
                    }
                )
        return {
            "pre": {
                "port_0x01": f"0x{pre[0]:02X}",
                "port_0x02": f"0x{pre[1]:02X}",
                "port_0x03": f"0x{pre[2]:02X}",
                "port_0x04": f"0x{pre[3]:02X}",
                "port_0x20": f"0x{pre[4]:02X}",
                "asic_id": f"0x{frame.asic_id:02X}",
                "status": f"0x{frame.status:02X}",
            },
            "trigger_all_groups_read": f"0x{trigger:02X}",
            "trigger_pressed_columns": (~trigger) & 0xFF,
            "sample_order": "group-major, trial-major, delay-major",
            "trials_per_point": KEYPAD_SETTLE_TRIALS,
            "pre_sample_hold_loop_iterations": KEYPAD_SETTLE_HOLD_LOOP_ITERATIONS,
            "pre_sample_hold_loop_base_t_states": (
                KEYPAD_SETTLE_HOLD_LOOP_BASE_T_STATES
            ),
            "points": rows,
            "post": {
                "port_0x01": f"0x{post[0]:02X}",
                "port_0x02": f"0x{post[1]:02X}",
                "port_0x03": f"0x{post[2]:02X}",
                "port_0x04": f"0x{post[3]:02X}",
                "port_0x20": f"0x{post[4]:02X}",
            },
            "entry_all_columns_high": pre[0] == 0xFF,
            "cleanup_all_columns_high": post[0] == 0xFF,
            "status_unchanged": post[1] == pre[1],
            "interrupt_ports_unchanged": post[2:4] == pre[2:4],
            "speed_unchanged": post[4] == pre[4],
        }
    if frame.probe_id == 10:
        return _decode_timing_probe(
            frame,
            payload_name="bus-timing",
            case_count=len(BUS_TIMING_PROBE_CASES),
            outcome_names={
                0: "completed",
                1: "timer-source-active",
                2: "timer-mode-active",
                3: "flash-gate-unlocked",
                4: "timing-gate-disabled",
                5: "helper-signature-mismatch",
            },
            measurement_decoder=decode_bus_timing_probe_measurements,
        )
    if frame.probe_id == 11:
        return _decode_timing_probe(
            frame,
            payload_name="prefix-M1",
            case_count=len(PREFIX_M1_PROBE_CASES),
            outcome_names={
                0: "completed",
                1: "timer-source-active",
                2: "timer-mode-active",
                3: "ram-timing-gate-disabled",
            },
            measurement_decoder=decode_prefix_m1_probe_measurements,
        )
    if frame.probe_id == 12:
        return _decode_physical_timer_probe(frame)
    if frame.probe_id == 13:
        if len(frame.payload) != 19:
            raise ProbeFormatError(
                "RTC rollover payload must contain 19 bytes, "
                f"got {len(frame.payload)}"
            )
        outcome_names = {
            0: "completed",
            1: "interrupts-disabled-on-entry",
            2: "missed-rollover-window",
            3: "rtc-disabled-on-entry",
        }
        last_ff = int.from_bytes(frame.payload[2:6], "big")
        first_after = int.from_bytes(frame.payload[6:10], "big")
        reverse_after = int.from_bytes(frame.payload[10:14], "little")
        followup = int.from_bytes(frame.payload[14:18], "big")
        outcome_code = frame.payload[1]
        return {
            "outcome_code": outcome_code,
            "outcome": outcome_names.get(
                outcome_code, f"unknown-{outcome_code}"
            ),
            "pre_control": f"0x{frame.payload[0]:02X}",
            "last_low_ff": f"0x{last_ff:08X}",
            "first_high_to_low_after": f"0x{first_after:08X}",
            "first_low_to_high_after": f"0x{reverse_after:08X}",
            "followup_high_to_low": f"0x{followup:08X}",
            "post_control": f"0x{frame.payload[18]:02X}",
            "control_unchanged": frame.payload[18] == frame.payload[0],
            "first_transition_coherent": (
                outcome_code == 0
                and first_after == ((last_ff + 1) & 0xFFFFFFFF)
            ),
            "later_reads_monotonic": (
                outcome_code == 0
                and first_after <= reverse_after <= followup
            ),
        }
    if frame.probe_id == 14:
        if len(frame.payload) != 47:
            raise ProbeFormatError(
                "mapper-overlay payload must contain 47 bytes, "
                f"got {len(frame.payload)}"
            )
        outcome_names = {
            0: "completed",
            1: "unexpected-port-05",
            2: "unexpected-port-06",
            3: "unexpected-port-07",
            4: "unexpected-port-0e",
            5: "unexpected-port-0f",
            6: "port-27-already-active",
            7: "port-28-already-active",
            8: "post-appvar-mapping-changed",
            9: "fixed-page-helper-signature-mismatch",
        }
        independent_reads = list(frame.payload[10:19])
        independent_writes = list(frame.payload[19:23])
        paired_reads = list(frame.payload[23:32])
        paired_writes = list(frame.payload[32:36])
        profiles = {
            "tilem": ([0xA1, 0xA2, 0xB3], [0xA1, 0xA2, 0xE3]),
            "wabbitemu": ([0xA1, 0xA2, 0xB3], [0xE1, 0xE2, 0xE3]),
            "mame-no-overlays": ([0xB1, 0xB2, 0xB3], [0xE1, 0xE2, 0xE3]),
        }
        profile = "mixed-or-physical"
        for name, (independent_prefix, paired_prefix) in profiles.items():
            if independent_reads[:3] == independent_prefix and paired_reads[:3] == paired_prefix:
                profile = name
                break
        pre = frame.payload[0:9]
        post = frame.payload[38:47]
        outcome_code = frame.payload[9]
        return {
            "outcome_code": outcome_code,
            "outcome": outcome_names.get(outcome_code, f"unknown-{outcome_code}"),
            "pre_ports_03_04_05_06_07_0e_0f_27_28": [f"0x{value:02X}" for value in pre],
            "independent_reads": [f"0x{value:02X}" for value in independent_reads],
            "independent_write_routing": [f"0x{value:02X}" for value in independent_writes],
            "paired_reads": [f"0x{value:02X}" for value in paired_reads],
            "paired_write_routing": [f"0x{value:02X}" for value in paired_writes],
            "paired_even_flash_b": f"0x{frame.payload[36]:02X}",
            "closest_emulator_profile": profile,
            "restore_flags": f"0x{frame.payload[37]:02X}",
            "all_marker_pages_restored": frame.payload[37] == 0x0F,
            "post_ports_03_04_05_06_07_0e_0f_27_28": [f"0x{value:02X}" for value in post],
            "readable_ports_restored": post[0] == pre[0] and post[2:] == pre[2:],
        }
    if frame.probe_id == 15:
        if len(frame.payload) == 43:
            outcome_names = {
                0: "completed",
                1: "controller-in-reset",
                2: "not-in-eight-bit-mode",
                3: "invalid-os-pointer-state",
                4: "asic-ready-timeout",
                6: "cell-restoration-failed",
            }
            ready = {
                "command_write": int.from_bytes(frame.payload[14:16], "little"),
                "data_read": int.from_bytes(frame.payload[16:18], "little"),
                "data_write": int.from_bytes(frame.payload[18:20], "little"),
            }
            cells = list(frame.payload[22:29])
            row_model = "mixed-or-physical"
            if cells[0] == 0xA6 and cells[2:4] == [0xA4, 0xA5]:
                row_model = "tilem-16-column"
            elif cells[0:3] == [0xA5, 0xA6, 0xA4]:
                row_model = "wabbitemu-15-column-wrap"
            elif cells[2] == 0xA4 and cells[4:6] == [0xA5, 0xA6]:
                row_model = "mame-15-byte-spill"
            pre_waits = frame.payload[4:11]
            post_waits = frame.payload[36:43]
            outcome_code = frame.payload[13]
            return {
                "schema": "legacy-hidden-column-v1",
                "outcome_code": outcome_code,
                "outcome": outcome_names.get(outcome_code, f"unknown-{outcome_code}"),
                "ready_zero_sample_counts": ready,
                "immediate_port_0x02": f"0x{frame.payload[20]:02X}",
                "immediate_status_0x10": f"0x{frame.payload[21]:02X}",
                "observed_cells": [f"0x{value:02X}" for value in cells],
                "direct_column_16": f"0x{frame.payload[29]:02X}",
                "direct_column_31": f"0x{frame.payload[30]:02X}",
                "row_model": row_model,
                "restore_ok": frame.payload[31] == 1,
                "wait_registers_unchanged": post_waits == pre_waits,
            }
        if len(frame.payload) != 42:
            raise ProbeFormatError(
                "LCD-controller payload must contain 42 or 43 bytes, "
                f"got {len(frame.payload)}"
            )
        outcome_names = {
            0: "completed",
            1: "controller-in-reset",
            2: "not-in-eight-bit-mode",
            3: "invalid-os-pointer-state",
            4: "asic-ready-timeout",
            5: "hidden-column-pointer-rejected",
            6: "cell-restoration-failed",
        }
        ready = {
            "command_write": int.from_bytes(frame.payload[14:16], "little"),
            "data_read": int.from_bytes(frame.payload[16:18], "little"),
            "data_write": int.from_bytes(frame.payload[18:20], "little"),
        }
        pre_waits = frame.payload[4:11]
        post_waits = frame.payload[35:42]
        outcome_code = frame.payload[13]
        immediate = {
            "command_write": {
                "port_0x02": f"0x{frame.payload[20]:02X}",
                "status_0x10": f"0x{frame.payload[21]:02X}",
            },
            "data_read": {
                "port_0x02": f"0x{frame.payload[22]:02X}",
                "status_0x10": f"0x{frame.payload[23]:02X}",
            },
            "data_write": {
                "port_0x02": f"0x{frame.payload[24]:02X}",
                "status_0x10": f"0x{frame.payload[25]:02X}",
            },
        }
        return {
            "schema": "visible-cell-v2",
            "outcome_code": outcome_code,
            "outcome": outcome_names.get(outcome_code, f"unknown-{outcome_code}"),
            "ready_zero_sample_counts": ready,
            "immediate_samples": immediate,
            "controller_busy_samples": {
                name: bool(frame.payload[offset] & 0x80)
                for name, offset in (("command_write", 21), ("data_read", 23),
                                     ("data_write", 25))
            },
            "visible_cell": {
                "before": f"0x{frame.payload[26]:02X}",
                "after_same_value_write": f"0x{frame.payload[27]:02X}",
                "after_restore": f"0x{frame.payload[28]:02X}",
                "matches": frame.payload[26] == frame.payload[27] == frame.payload[28],
            },
            "entry_movement_command": f"0x{frame.payload[29]:02X}",
            "restore_ok": frame.payload[30] == 1,
            "movement_status_restored": (
                frame.payload[29] == 0x04 + (frame.payload[33] & 0x03)
            ),
            "wait_registers_unchanged": post_waits == pre_waits,
        }
    if frame.probe_id == 16:
        if len(frame.payload) != 21:
            raise ProbeFormatError(
                "interrupt-HALT payload must contain 21 bytes, "
                f"got {len(frame.payload)}"
            )
        outcome_names = {
            0: "completed",
            1: "interrupt-source-pending-on-entry",
            2: "on-key-held-on-entry",
            3: "timer-source-active",
            4: "timer-mode-active",
            5: "interrupts-disabled-on-entry",
            6: "unexpected-handler-count",
            7: "post-appvar-guard-failed",
            8: "unsupported-os-context",
            9: "im1-vector-signature-mismatch",
            10: "usb-source-active",
        }
        wake_status = frame.payload[8]
        wake_class = "unknown"
        if wake_status & 0x20 and not wake_status & 0x02:
            wake_class = "programmable-timer"
        elif wake_status & 0x02:
            wake_class = "standard-timer-watchdog"
        outcome_code = frame.payload[6]
        return {
            "outcome_code": outcome_code,
            "outcome": outcome_names.get(outcome_code, f"unknown-{outcome_code}"),
            "handler_count": frame.payload[7],
            "handler_status_0x04": f"0x{wake_status:02X}",
            "handler_mode_0x31": f"0x{frame.payload[9]:02X}",
            "handler_counter_0x32": f"0x{frame.payload[10]:02X}",
            "wake_class": wake_class,
            "after_status_0x04": f"0x{frame.payload[11]:02X}",
            "restore_ok": frame.payload[20] == 1,
            "i_register_restored": frame.payload[19] == frame.payload[5],
        }
    if frame.probe_id == 17:
        if len(frame.payload) != 2335:
            raise ProbeFormatError(
                "hidden-LCD laboratory payload must contain 2335 bytes, "
                f"got {len(frame.payload)}"
            )
        outcome_names = {
            0: "pending-reset-or-interruption",
            1: "completed",
            2: "compile-time-acknowledgement-mismatch",
            3: "ASIC-identity-mismatch",
            4: "OS-signature-mismatch",
            5: "controller-reset-active",
            6: "controller-not-in-eight-bit-mode",
            7: "unsafe-OS-pointer-state",
            8: "LCD-ready-timeout",
            9: "restoration-mismatch",
        }
        before = frame.payload[31:799]
        direct = frame.payload[799:1567]
        wrap = frame.payload[1567:2335]
        direct_differences = [
            index for index, (old, new) in enumerate(zip(before, direct, strict=True))
            if old != new
        ]
        wrap_differences = [
            index for index, (old, new) in enumerate(zip(before, wrap, strict=True))
            if old != new
        ]
        outcome_code = frame.payload[0]
        reported_direct_changes = int.from_bytes(frame.payload[8:10], "little")
        reported_wrap_changes = int.from_bytes(frame.payload[10:12], "little")
        visible_restore_mismatches = int.from_bytes(frame.payload[12:14], "little")
        hidden_restore_mismatches = frame.payload[14]
        return {
            "schema": "recovery-gated-hidden-column-v1",
            "outcome_code": outcome_code,
            "outcome": outcome_names.get(outcome_code, f"unknown-{outcome_code}"),
            "last_completed_stage": frame.payload[1],
            "entry": {
                "controller_status": f"0x{frame.payload[2]:02X}",
                "movement_command": f"0x{frame.payload[3]:02X}",
                "curY": f"0x{frame.payload[4]:02X}",
                "curXRow": f"0x{frame.payload[5]:02X}",
                "read_latch": f"0x{frame.payload[6]:02X}",
                "visible_cell": f"0x{frame.payload[7]:02X}",
            },
            "direct_hidden_columns": {
                "before": list(frame.payload[15:19]),
                "after": list(frame.payload[19:23]),
                "reported_visible_change_count": reported_direct_changes,
                "calculated_visible_change_count": len(direct_differences),
                "change_count_matches": reported_direct_changes == len(direct_differences),
                "visible_difference_indices": direct_differences,
            },
            "increment_from_column_14": {
                "hidden_after": list(frame.payload[23:27]),
                "reported_visible_change_count": reported_wrap_changes,
                "calculated_visible_change_count": len(wrap_differences),
                "change_count_matches": reported_wrap_changes == len(wrap_differences),
                "visible_difference_indices": wrap_differences,
            },
            "restoration": {
                "hidden_after": list(frame.payload[27:31]),
                "visible_mismatch_count": visible_restore_mismatches,
                "hidden_mismatch_count": hidden_restore_mismatches,
                "matches": (
                    outcome_code == 1
                    and visible_restore_mismatches == 0
                    and hidden_restore_mismatches == 0
                ),
            },
        }
    return {"payload_hex": frame.payload.hex().upper()}


def probe_appvar_report(blob: bytes, *, path: str | None = None) -> dict[str, object]:
    """Return a JSON-serializable report for one exported probe AppVar."""

    from compact_probe_code import encode_compact_probe_code

    variable, frame = decode_probe_appvar(blob)
    frame_bytes = frame.encode()
    compact_code = encode_compact_probe_code(frame_bytes)
    report: dict[str, object] = {
        "variable_name": variable.name,
        "variable_version": variable.version,
        "archived": variable.archived,
        "container_comment": variable.comment,
        "appvar_file_size": len(blob),
        "appvar_file_sha256": hashlib.sha256(blob).hexdigest(),
        "format_version": frame.format_version,
        "frame_size": len(frame_bytes),
        "frame_hex": frame_bytes.hex().upper(),
        "frame_sha256": hashlib.sha256(frame_bytes).hexdigest(),
        "compact_state_code": compact_code,
        "compact_state_code_length": len(compact_code),
        "probe_id": frame.probe_id,
        "probe_name": PROBE_NAMES.get(frame.probe_id, "unknown"),
        "asic_id": frame.asic_id,
        "asic_id_hex": f"0x{frame.asic_id:02X}",
        "status": frame.status,
        "status_hex": f"0x{frame.status:02X}",
        "payload_size": len(frame.payload),
        "payload_hex": frame.payload.hex().upper(),
        "measurements": decode_probe_measurements(frame),
        "verification_code_decimal": probe_verification_code(frame),
        "verification_code_hex": f"0x{probe_verification_code(frame):04X}",
    }
    if path is not None:
        report = {"path": path, **report}
    return report
