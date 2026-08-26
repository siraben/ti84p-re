#!/usr/bin/env python3
"""Encode and decode reversible compact text for complete HWP1 frames."""

from __future__ import annotations

import argparse
import binascii
import json

from hardware_probe import ProbeFormatError, decode_probe_frame, decode_probe_measurements

PREFIX = "HWPZ1-"
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
DECODE = {character: index for index, character in enumerate(ALPHABET)}
DECODE.update({"O": 0, "I": 1, "L": 1})
ESCAPE = 0xFF


class CompactProbeCodeError(ValueError):
    """A compact physical-probe code is malformed or corrupt."""


def rle_compress(data: bytes) -> bytes:
    """Compress bytes with deterministic escape-run encoding."""

    output = bytearray()
    index = 0
    while index < len(data):
        value = data[index]
        count = 1
        while (
            index + count < len(data)
            and data[index + count] == value
            and count < 0xFF
        ):
            count += 1
        if value == ESCAPE or count >= 3:
            output += bytes((ESCAPE, count, value))
        else:
            output += bytes((value,)) * count
        index += count
    return bytes(output)


def rle_decompress(data: bytes, expected_size: int) -> bytes:
    """Expand escape-run bytes and enforce the declared frame size."""

    output = bytearray()
    index = 0
    while index < len(data):
        value = data[index]
        index += 1
        if value != ESCAPE:
            output.append(value)
        else:
            if index + 2 > len(data):
                raise CompactProbeCodeError("truncated escape-run record")
            count, value = data[index : index + 2]
            index += 2
            if count == 0:
                raise CompactProbeCodeError("escape-run count is zero")
            output += bytes((value,)) * count
        if len(output) > expected_size:
            raise CompactProbeCodeError("expanded frame exceeds its declared size")
    if len(output) != expected_size:
        raise CompactProbeCodeError(
            f"expanded frame has {len(output)} bytes, expected {expected_size}"
        )
    return bytes(output)


def base32_encode(data: bytes) -> str:
    """Encode bytes with unpadded Crockford Base32."""

    output: list[str] = []
    buffer = 0
    bits = 0
    for value in data:
        buffer = (buffer << 8) | value
        bits += 8
        while bits >= 5:
            bits -= 5
            output.append(ALPHABET[(buffer >> bits) & 0x1F])
            buffer &= (1 << bits) - 1
    if bits:
        output.append(ALPHABET[(buffer << (5 - bits)) & 0x1F])
    return "".join(output)


def base32_decode(text: str) -> bytes:
    """Decode Crockford Base32 and reject nonzero trailing padding bits."""

    buffer = 0
    bits = 0
    output = bytearray()
    for character in text.upper():
        if character in " -\t\r\n":
            continue
        try:
            value = DECODE[character]
        except KeyError as error:
            raise CompactProbeCodeError(
                f"invalid compact-code character {character!r}"
            ) from error
        buffer = (buffer << 5) | value
        bits += 5
        while bits >= 8:
            bits -= 8
            output.append((buffer >> bits) & 0xFF)
            buffer &= (1 << bits) - 1
    if bits >= 5:
        raise CompactProbeCodeError("compact code has a noncanonical symbol count")
    if buffer:
        raise CompactProbeCodeError("compact code has nonzero trailing bits")
    return bytes(output)


def encode_compact_probe_code(frame: bytes) -> str:
    """Return one reversible, checksummed compact code for an HWP1 frame."""

    decode_probe_frame(frame)
    if len(frame) > 0xFFFF:
        raise ValueError("HWP1 frame is too large for compact-code version 1")
    crc = binascii.crc_hqx(frame, 0xFFFF)
    envelope = (
        len(frame).to_bytes(2, "little")
        + crc.to_bytes(2, "little")
        + rle_compress(frame)
    )
    return PREFIX + base32_encode(envelope)


def decode_compact_probe_code(code: str) -> bytes:
    """Recover and validate the exact HWP1 frame encoded by *code*."""

    normalized = code.strip()
    if not normalized.upper().startswith(PREFIX):
        raise CompactProbeCodeError(f"compact code must begin with {PREFIX}")
    envelope = base32_decode(normalized[len(PREFIX) :])
    if len(envelope) < 4:
        raise CompactProbeCodeError("compact-code envelope is shorter than four bytes")
    expected_size = int.from_bytes(envelope[:2], "little")
    expected_crc = int.from_bytes(envelope[2:4], "little")
    frame = rle_decompress(envelope[4:], expected_size)
    actual_crc = binascii.crc_hqx(frame, 0xFFFF)
    if actual_crc != expected_crc:
        raise CompactProbeCodeError(
            f"frame CRC is 0x{actual_crc:04X}, expected 0x{expected_crc:04X}"
        )
    try:
        decode_probe_frame(frame)
    except ProbeFormatError as error:
        raise CompactProbeCodeError(f"decoded frame is invalid: {error}") from error
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", help="HWPZ1 compact code; whitespace is ignored")
    args = parser.parse_args()
    try:
        frame_bytes = decode_compact_probe_code(args.code)
        frame = decode_probe_frame(frame_bytes)
    except CompactProbeCodeError as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "frame_hex": frame_bytes.hex().upper(),
                "probe_id": frame.probe_id,
                "asic_id": frame.asic_id,
                "status": frame.status,
                "payload_hex": frame.payload.hex().upper(),
                "measurements": decode_probe_measurements(frame),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
