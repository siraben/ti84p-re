"""Reusable builders for TI-83+/84+ program link files."""

from __future__ import annotations

from ti84re.hardware.probe import encode_ti_variable_file


PROGRAM_TYPE = 0x05
ASM_PRGM_PREFIX = bytes((0xBB, 0x6C, 0x3F))
ASM_CALL_PREFIX = bytes((0xBB, 0x6A, 0x5F))
STATEMENT_END = 0x3F


def asmprgm_body(machine_code: bytes) -> bytes:
    """Wrap Z80 machine code in the tokenized ``AsmPrgm`` hex format."""

    if not machine_code:
        raise ValueError("assembly program machine code is empty")
    return (
        ASM_PRGM_PREFIX
        + machine_code.hex().upper().encode("ascii")
        + bytes((STATEMENT_END,))
    )


def asm_call_body(program_name: str) -> bytes:
    """Return a tokenized one-line ``Asm(prgmNAME)`` BASIC wrapper."""

    normalized = program_name.upper()
    if (
        not 1 <= len(normalized) <= 8
        or not normalized.isascii()
        or not normalized.isalnum()
        or not normalized[0].isalpha()
    ):
        raise ValueError(
            "assembly program name must start with a letter and contain one through "
            "eight alphanumeric characters"
        )
    return (
        ASM_CALL_PREFIX
        + normalized.encode("ascii")
        + bytes((0x11, STATEMENT_END))
    )


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
