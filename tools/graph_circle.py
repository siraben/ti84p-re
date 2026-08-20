#!/usr/bin/env python3
"""ROM-grounded models and trace reduction for TI-OS circle drawing.

The page-3B ``_DrawCirc2`` body is mostly floating-point orchestration.  This
module translates the byte-copy ABI at 3B:72F3, exposes the finite segment
schedule around it, and decodes the seven trigonometric coefficients consumed
by the loop.  The optional trace reducer records one ``_CircCmd`` interval and
its ordered ``_CLine`` inputs.  A direct ``_GrphCirc`` caller needs a separate
interval boundary and is deliberately rejected by this reducer.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Iterable

from file_hashes import file_sha256
from hardware_trace import make_banker
from rom_image import RomImage
from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from tilem_trace_resolve import IDX_IY, iter_records, read_header, resolve_instruction


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "tools" / "rom.bin"
TILEM_SOURCE = "https://github.com/siraben/tilem-headless"
TILEM_COMMIT = "d1bdc58dd321ae462a701e556fcb62bb925a78b1"
TILEM_BINARY_SHA256 = "cdd257c57b918b8f0b05df6e49f249d4f0461a7c1ed2d9b87fe76fc3d2b0e1ee"

TIFLOAT_SIZE = 9
OP1 = 0x8478
OP2 = 0x8483
OP3 = 0x848E
OP4 = 0x8499
PLOT_SCREEN = range(0x9340, 0x9640)

DRAW_CIRC2_PAGE = 0x3B
DRAW_CIRC2_ENTRY = 0x7171
PAIR_HELPER_ENTRY = 0x72F3
PAIR_HELPER_END = 0x730E
TAIL_HELPER_ENTRY = 0x730E
POINTER_HELPERS_END = 0x7331
COEFFICIENT_PAGE = 0x35
COEFFICIENT_TABLE = 0x79F5

# Eight recurrence calls run during each of seven iterations.  Four final
# calls close the symmetric arcs.  Addresses name the CALL instructions.
RECURRENCE_CALL_SITES = (
    0x7222,
    0x723A,
    0x7253,
    0x7263,
    0x7281,
    0x729A,
    0x72B2,
    0x72C9,
)
TAIL_CALL_SITES = (0x72D8, 0x72DE, 0x72E4, 0x72EA)
TAIL_FRAME_OFFSETS = (-0x5A, -0x6C, -0x48, -0x5A)
CONSUMED_COEFFICIENT_INDICES = tuple(range(7))

TRACE_POINTS = {
    "circ_cmd": ("page_33", 0x74CE),
    "generator_branch": ("page_33", 0x74DF),
    "clear_flag_generator": ("page_33", 0x74E9),
    "clear_flag_loop": ("page_33", 0x7506),
    "clear_flag_line_emit": ("page_33", 0x7561),
    "clear_flag_end": ("page_33", 0x7580),
    "circ_cmd_return": ("page_33", 0x74D9),
    "grph_circ": ("page_33", 0x758D),
    "draw_circ2": ("page_3B", 0x7171),
    "draw_circ2_coefficient_lookup": ("page_35", 0x79E9),
    "coordinate_line": ("page_33", 0x6028),
    "integer_line": ("page_04", 0x4029),
    "integer_point": ("page_04", 0x4157),
}


@dataclass(frozen=True)
class PairTransition:
    """Visible state transition of the 3B:72F3 point-pair helper."""

    old_x: bytes
    old_y: bytes
    new_x: bytes
    new_y: bytes
    returned_pointer: int

    @property
    def line_registers(self) -> tuple[bytes, bytes, bytes, bytes]:
        """Return OP1, OP2, OP3, and OP4 at the `_CLine` call."""

        return self.new_x, self.new_y, self.old_x, self.old_y


@dataclass(frozen=True)
class TraceSegment:
    """One real-coordinate segment observed at `_CLine` entry."""

    new_x: str
    new_y: str
    old_x: str
    old_y: str
    raw_new_x: str
    raw_new_y: str
    raw_old_x: str
    raw_old_y: str


def decode_tifloat_real(raw: bytes) -> Decimal:
    """Decode the ordinary real subset of TI's nine-byte BCD format."""

    if len(raw) != TIFLOAT_SIZE:
        raise ValueError("a TIFloat must contain exactly nine bytes")
    if raw[0] & 0x7F:
        raise ValueError(f"unsupported non-real TIFloat type 0x{raw[0]:02X}")
    digits: list[str] = []
    for value in raw[2:]:
        high, low = value >> 4, value & 0x0F
        if high > 9 or low > 9:
            raise ValueError("TIFloat mantissa contains a non-BCD nibble")
        digits.extend((str(high), str(low)))
    magnitude = Decimal(int("".join(digits))).scaleb(raw[1] - 0x80 - 13)
    return -magnitude if raw[0] & 0x80 else magnitude


def translate_pair_helper(
    old_x: bytes, old_y: bytes, new_x: bytes, new_y: bytes, *, pointer: int
) -> PairTransition:
    """Translate 3B:72F3–730D at its four-TIFloat ABI boundary.

    The helper copies the old pair into OP3/OP4, replaces the two frame slots
    with OP1/OP2, calls the page-0 bjump at 00:3453 (33:6028 ``_CLine``), and
    returns HL immediately after the replaced pair.
    """

    records = (old_x, old_y, new_x, new_y)
    if any(len(record) != TIFLOAT_SIZE for record in records):
        raise ValueError("each point coordinate must be one nine-byte TIFloat")
    if not 0 <= pointer <= 0x10000 - 2 * TIFLOAT_SIZE:
        raise ValueError("point-pair pointer is outside 16-bit memory")
    return PairTransition(old_x, old_y, new_x, new_y, pointer + 2 * TIFLOAT_SIZE)


def _u16le(data: bytes, offset: int) -> int:
    return data[offset] | data[offset + 1] << 8


def _call_sites(data: bytes, base: int, target: int) -> tuple[int, ...]:
    needle = bytes((0xCD, target & 0xFF, target >> 8))
    return tuple(
        base + offset
        for offset in range(len(data) - 2)
        if data[offset:offset + 3] == needle
    )


def inspect_rom(rom: RomImage) -> dict[str, object]:
    """Return the finite ROM facts that define the translated slice."""

    body = rom.bytes_at(DRAW_CIRC2_PAGE, DRAW_CIRC2_ENTRY, POINTER_HELPERS_END - DRAW_CIRC2_ENTRY)
    loop = rom.bytes_at(DRAW_CIRC2_PAGE, 0x71E8, 0x72D2 - 0x71E8)
    tail = rom.bytes_at(DRAW_CIRC2_PAGE, 0x72D2, 0x72ED - 0x72D2)
    pair_helper = rom.bytes_at(
        DRAW_CIRC2_PAGE, PAIR_HELPER_ENTRY, PAIR_HELPER_END - PAIR_HELPER_ENTRY
    )
    coefficient_bytes = rom.bytes_at(
        COEFFICIENT_PAGE, COEFFICIENT_TABLE, 8 * TIFLOAT_SIZE
    )
    coefficients = tuple(
        decode_tifloat_real(coefficient_bytes[index:index + TIFLOAT_SIZE])
        for index in range(0, len(coefficient_bytes), TIFLOAT_SIZE)
    )
    recurrence_calls = _call_sites(loop, 0x71E8, PAIR_HELPER_ENTRY)
    tail_calls = _call_sites(tail, 0x72D2, TAIL_HELPER_ENTRY)
    page_zero = rom.page(0)
    return {
        "entry": f"{DRAW_CIRC2_PAGE:02X}:{DRAW_CIRC2_ENTRY:04X}",
        "allocation_bytes": _u16le(body, 1),
        "allocation_tifloats": _u16le(body, 1) // TIFLOAT_SIZE,
        "loop_iterations": body[0x71E7 - DRAW_CIRC2_ENTRY],
        "recurrence_call_sites": recurrence_calls,
        "recurrence_calls_per_iteration": len(recurrence_calls),
        "tail_call_sites": tail_calls,
        "tail_frame_offsets": TAIL_FRAME_OFFSETS,
        "total_coordinate_lines": len(recurrence_calls) * 7 + len(tail_calls),
        "coefficient_indices": CONSUMED_COEFFICIENT_INDICES,
        "coefficients": tuple(str(coefficients[index]) for index in CONSUMED_COEFFICIENT_INDICES),
        "adjacent_coefficient": str(coefficients[7]),
        "pair_helper_sha256": hashlib.sha256(pair_helper).hexdigest(),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "cline_bjump_descriptor": page_zero[0x3453:0x3459].hex(),
    }


def _raw_tifloat(memory: bytearray, address: int) -> bytes:
    return bytes(memory[address:address + TIFLOAT_SIZE])


def _trace_segment(memory: bytearray) -> TraceSegment:
    raw = tuple(_raw_tifloat(memory, address) for address in (OP1, OP2, OP3, OP4))
    values = tuple(str(decode_tifloat_real(value)) for value in raw)
    return TraceSegment(
        values[0], values[1], values[2], values[3],
        raw[0].hex(), raw[1].hex(), raw[2].hex(), raw[3].hex(),
    )


def analyze_trace(path: Path) -> dict[str, object]:
    """Reduce one full-memory TLMT v2 circle trace to ordered line evidence."""

    points_by_location = {location: name for name, location in TRACE_POINTS.items()}
    banker = make_banker("ti84p-reset")
    pending_writes: list[tuple[int, int]] = []
    counts: Counter[str] = Counter()
    segments: list[TraceSegment] = []
    branch_states: list[dict[str, int]] = []
    total_instructions = 0
    circle_active = False
    circle_complete = False
    circle_plot: bytes | None = None

    with path.open("rb") as stream:
        header = read_header(stream)
        if header["version"] != 2:
            raise ValueError(f"{path}: expected TLMT v2")
        if len(header["init"]) != 0x10000:
            raise ValueError(f"{path}: expected a 64 KiB logical-memory snapshot")
        memory = bytearray(header["init"])
        for record_type, payload in iter_records(stream):
            if record_type == 0x02:
                pending_writes.append(payload)
                continue
            if record_type != 0x01:
                continue
            total_instructions += 1
            resolved, _switch = resolve_instruction(banker, payload)
            location = (resolved[0], resolved[1])
            if location == TRACE_POINTS["circ_cmd"]:
                if circle_active or circle_complete:
                    raise ValueError(f"{path}: expected one Circle command interval")
                circle_active = True
            if not circle_active:
                for address, value in pending_writes:
                    if 0 <= address < len(memory):
                        memory[address] = value
                pending_writes.clear()
                continue
            name = points_by_location.get(location)
            if name is not None:
                counts[name] += 1
            if location == TRACE_POINTS["generator_branch"]:
                iy = payload[IDX_IY]
                flag_address = (iy + 0x3C) & 0xFFFF
                branch_states.append({
                    "iy": iy,
                    "flag_address": flag_address,
                    "flag_byte": memory[flag_address],
                    "tested_bit": 4,
                    "tested_bit_set": (memory[flag_address] >> 4) & 1,
                })
            if location == TRACE_POINTS["coordinate_line"]:
                segments.append(_trace_segment(memory))
            for address, value in pending_writes:
                if 0 <= address < len(memory):
                    memory[address] = value
            pending_writes.clear()
            if location == TRACE_POINTS["circ_cmd_return"]:
                circle_active = False
                circle_complete = True
                circle_plot = bytes(memory[PLOT_SCREEN.start:PLOT_SCREEN.stop])

    if not circle_complete or circle_plot is None:
        raise ValueError(f"{path}: Circle interval did not reach its 33:74D9 return")
    if counts["circ_cmd"] != 1 or counts["generator_branch"] != 1:
        raise ValueError(f"{path}: expected one Circle command and one generator branch")
    clear_flag_selected = counts["clear_flag_generator"] == 1
    draw_circ2_selected = counts["draw_circ2"] > 0
    if clear_flag_selected == draw_circ2_selected:
        raise ValueError(f"{path}: Circle generator selection is ambiguous")
    if len(segments) != counts["coordinate_line"]:
        raise ValueError(f"{path}: coordinate-line snapshots are incomplete")
    continuity = sum(
        left.raw_new_x == right.raw_old_x and left.raw_new_y == right.raw_old_y
        for left, right in zip(segments, segments[1:])
    )
    generator_selection: dict[str, object]
    if draw_circ2_selected:
        generator_selection = {
            "branch": "33:74DF",
            "tested_flag": "(IY+3C).4",
            "selected_when": "set",
            "bcall": "4C66",
            "entry": "3B:7171",
        }
    else:
        generator_selection = {
            "branch": "33:74DF",
            "tested_flag": "(IY+3C).4",
            "selected_when": "clear",
            "entry": "33:74E9",
            "loop": "33:7506",
            "line_emit": "33:7561",
            "end": "33:7580",
            "page_35_79e9_visits": counts["draw_circ2_coefficient_lookup"],
        }
    return {
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
        "total_instructions": total_instructions,
        "point_visits": {
            name: counts[name] for name in sorted(TRACE_POINTS)
        },
        "generator_branch_states": branch_states,
        "generator_selection": generator_selection,
        "coordinate_lines": len(segments),
        "continuous_adjacent_lines": continuity,
        "first_segments": [asdict(segment) for segment in segments[:2]],
        "last_segments": [asdict(segment) for segment in segments[-1:]],
        "plot_sscreen_sha256": hashlib.sha256(circle_plot).hexdigest(),
        "plot_sscreen_dark_pixels": sum(value.bit_count() for value in circle_plot),
        "caller_state": "draw_circ2" if draw_circ2_selected else "page_33_clear_branch",
    }


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--emulator", type=Path)
    args = parser.parse_args(argv)
    rom_hash = file_sha256(args.rom)
    if rom_hash != TI84_PLUS_OS_255MP_SHA256:
        parser.error("ROM SHA-256 does not match TI-84 Plus OS 2.55MP")
    if args.trace is not None and args.emulator is None:
        parser.error("--emulator is required when reducing a trace")
    report: dict[str, object] = {
        "rom": {"path": "tools/rom.bin", "sha256": rom_hash},
        "static": inspect_rom(RomImage.from_path(args.rom)),
        "natural_witness": {
            "command": "Circle(0,0,5)",
            "macro": "tools/macros/graph-circle-natural.macro",
            "raw_trace_checked_in": False,
        },
    }
    if args.emulator is not None:
        emulator_hash = file_sha256(args.emulator)
        if emulator_hash != TILEM_BINARY_SHA256:
            parser.error("TilEm binary SHA-256 does not match the traced headless build")
        report["tilem"] = {
            "source": TILEM_SOURCE,
            "commit": TILEM_COMMIT,
            "binary_sha256": emulator_hash,
        }
    if args.trace is not None:
        report["natural_trace"] = analyze_trace(args.trace)
    print(json.dumps(report, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
