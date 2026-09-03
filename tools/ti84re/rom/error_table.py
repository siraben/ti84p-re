"""Decode the TI-84 Plus OS error-message pointer table from a ROM image."""

from __future__ import annotations

from dataclasses import dataclass

from ti84re.rom.image import RomFormatError, RomImage


ERROR_MESSAGE_PAGE = 0x07
ERROR_MESSAGE_POINTER_TABLE = 0x6ACC
ERROR_MESSAGE_LIMIT = 0x3A
ERROR_MESSAGE_FALLBACK = 0x6C5A
ERROR_MESSAGE_SPECIAL_FALLBACKS = frozenset((0x36, 0x37, 0x39))


@dataclass(frozen=True)
class ErrorMessage:
    """One raw error code and the message selected by the OS display path."""

    raw_code: int
    code: int
    editable: bool
    pointer_entry: int | None
    message_address: int
    message: str
    fallback: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "raw_code": self.raw_code,
            "code": self.code,
            "editable": self.editable,
            "pointer_entry": self.pointer_entry,
            "message_location": (
                f"{ERROR_MESSAGE_PAGE:02X}:{self.message_address:04X}"
            ),
            "message": self.message,
            "fallback": self.fallback,
        }


def read_c_string(
    rom: RomImage,
    page: int,
    address: int,
    *,
    max_length: int = 256,
) -> str:
    """Read one ASCII-compatible, null-terminated string within a ROM page."""

    if max_length <= 0:
        raise ValueError("maximum string length must be positive")
    available = 0x4000 - (address & 0x3FFF)
    data = rom.bytes_at(page, address, min(max_length, available))
    terminator = data.find(b"\x00")
    if terminator < 0:
        raise RomFormatError(
            f"string at {page:02X}:{address:04X} has no terminator within "
            f"{len(data)} bytes"
        )
    return data[:terminator].decode("ascii", errors="replace")


def error_message(rom: RomImage, raw_code: int) -> ErrorMessage:
    """Resolve a raw ``_JError`` code through the OS's display table."""

    if not 0 <= raw_code <= 0xFF:
        raise ValueError("raw error code must be between 0 and 255")
    code = raw_code & 0x7F
    fallback = (
        code >= ERROR_MESSAGE_LIMIT or code in ERROR_MESSAGE_SPECIAL_FALLBACKS
    )
    if fallback:
        pointer_entry = None
        message_address = ERROR_MESSAGE_FALLBACK
    else:
        table_index = (code - 1) & 0xFF
        pointer_entry = ERROR_MESSAGE_POINTER_TABLE + 2 * table_index
        message_address = rom.u16le(ERROR_MESSAGE_PAGE, pointer_entry)
    return ErrorMessage(
        raw_code=raw_code,
        code=code,
        editable=bool(raw_code & 0x80),
        pointer_entry=pointer_entry,
        message_address=message_address,
        message=read_c_string(rom, ERROR_MESSAGE_PAGE, message_address),
        fallback=fallback,
    )
