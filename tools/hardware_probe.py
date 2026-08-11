"""Versioned result frames and TI variable files for physical hardware probes."""

from __future__ import annotations

from dataclasses import dataclass


TI_SIGNATURE = b"**TI83F*\x1a\x0a\x00"
PROBE_MAGIC = b"HWP1"
PROBE_FORMAT_VERSION = 1
APPVAR_TYPE = 0x15
PROBE_NAMES = {
    1: "md5-edge",
    2: "ram-alias",
    3: "asic-snapshot",
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
        if len(frame.payload) != 18:
            raise ProbeFormatError(
                f"RAM alias payload must contain 18 bytes, got {len(frame.payload)}"
            )
        original = frame.payload[0:6]
        observed = frame.payload[6:12]
        restored = frame.payload[12:18]
        patterns = bytes((0x11, 0x22, 0x33, 0x44, 0x55, 0x66))
        if observed == patterns:
            topology = "independent-selectors"
        elif observed == bytes((0x66,)) * 6:
            topology = "selectors-82-through-87-alias"
        else:
            topology = "mixed-or-unexpected"
        return {
            "selectors": [f"0x{selector:02X}" for selector in range(0x82, 0x88)],
            "original": original.hex().upper(),
            "observed": observed.hex().upper(),
            "restored": restored.hex().upper(),
            "restore_matches": restored == original,
            "topology_observation": topology,
        }
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
    return {"payload_hex": frame.payload.hex().upper()}


def probe_appvar_report(blob: bytes, *, path: str | None = None) -> dict[str, object]:
    """Return a JSON-serializable report for one exported probe AppVar."""

    variable, frame = decode_probe_appvar(blob)
    report: dict[str, object] = {
        "variable_name": variable.name,
        "archived": variable.archived,
        "format_version": frame.format_version,
        "probe_id": frame.probe_id,
        "probe_name": PROBE_NAMES.get(frame.probe_id, "unknown"),
        "asic_id": frame.asic_id,
        "asic_id_hex": f"0x{frame.asic_id:02X}",
        "status": frame.status,
        "status_hex": f"0x{frame.status:02X}",
        "payload_size": len(frame.payload),
        "payload_hex": frame.payload.hex().upper(),
        "measurements": decode_probe_measurements(frame),
    }
    if path is not None:
        report = {"path": path, **report}
    return report
