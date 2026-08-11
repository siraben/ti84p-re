"""Reusable builders for TI-83+/84+ program link files."""

from __future__ import annotations

from hardware_probe import encode_ti_variable_file


PROGRAM_TYPE = 0x05


def encode_program_file(
    name: str,
    body: bytes | bytearray | list[int],
    *,
    comment: str = "Codex generated program",
) -> bytes:
    """Return an unarchived ``.8xp`` containing one tokenized program."""

    body_bytes = bytes(body)
    if len(body_bytes) > 0xFFFD:
        raise ValueError("program body is too large for a TI variable file")
    data = len(body_bytes).to_bytes(2, "little") + body_bytes
    return encode_ti_variable_file(
        PROGRAM_TYPE,
        name,
        data,
        comment=comment,
    )


def filled_program_body(
    size: int,
    *,
    fill_byte: int = 0x31,
    last_byte: int | None = 0x3F,
) -> bytes:
    """Build a deterministic body for storage and archive-boundary probes."""

    if not 0 <= size <= 0xFFFD:
        raise ValueError("program body is too large or has a negative size")
    if not 0 <= fill_byte <= 0xFF:
        raise ValueError("fill byte must fit in one byte")
    if last_byte is not None and not 0 <= last_byte <= 0xFF:
        raise ValueError("last byte must fit in one byte")
    if size == 0:
        return b""
    body = bytearray((fill_byte,)) * size
    if last_byte is not None:
        body[-1] = last_byte
    return bytes(body)
