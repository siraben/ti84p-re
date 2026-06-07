#!/usr/bin/env python3
"""Print small tokenized TI-BASIC sample programs for tracing.

These are raw program bodies: the bytes after a ProgObj's two-byte size word.
They are useful for checking parser traces and for building .8xp fixtures.
"""

from __future__ import annotations

import argparse
from pathlib import Path

T = {
    "store": 0x04,
    "lbrace": 0x08,
    "rbrace": 0x09,
    "rparen": 0x11,
    "string": 0x2A,
    "comma": 0x2B,
    "enter": 0x3F,
    "space": 0x29,
    "mul": 0x82,
    "0": 0x30,
    "1": 0x31,
    "2": 0x32,
    "3": 0x33,
    "4": 0x34,
    "5": 0x35,
    "6": 0x36,
    "7": 0x37,
    "8": 0x38,
    "9": 0x39,
    "A": 0x41,
    "B": 0x42,
    "C": 0x43,
    "D": 0x44,
    "E": 0x45,
    "F": 0x46,
    "G": 0x47,
    "H": 0x48,
    "I": 0x49,
    "K": 0x4B,
    "L": 0x4C,
    "M": 0x4D,
    "N": 0x4E,
    "O": 0x4F,
    "P": 0x50,
    "R": 0x52,
    "S": 0x53,
    "T": 0x54,
    "W": 0x57,
    "X": 0x58,
    "Y": 0x59,
    "varlst": 0x5D,
    "prog": 0x5F,
    "sum": 0xB6,
    "for": 0xD3,
    "end": 0xD4,
    "prompt": 0xDD,
    "disp": 0xDE,
    "clrhome": 0xE1,
    "sorta": 0xE3,
    "2byte": 0xBB,
    "cumsum": 0x29,
    "asm": 0x6A,
    "asmprgm": 0x6C,
}


def letters(text: str) -> list[int]:
    out: list[int] = []
    for ch in text:
        if ch == " ":
            out.append(T["space"])
        elif ch == ",":
            out.append(T["comma"])
        else:
            out.append(T[ch.upper()])
    return out


def string_literal(text: str) -> list[int]:
    return [T["string"], *letters(text), T["string"]]


SAMPLES: dict[str, tuple[str, list[int]]] = {
    "hello": (
        'ClrHome\nDisp "HELLO, WORLD"',
        [
            T["clrhome"], T["enter"],
            T["disp"], *string_literal("HELLO, WORLD"), T["enter"],
        ],
    ),
    "factorial": (
        "Prompt N\n1->F\nFor(I,1,N)\nF*I->F\nEnd\nDisp F",
        [
            T["prompt"], T["N"], T["enter"],
            T["1"], T["store"], T["F"], T["enter"],
            T["for"], T["I"], T["comma"], T["1"], T["comma"], T["N"], T["rparen"], T["enter"],
            T["F"], T["mul"], T["I"], T["store"], T["F"], T["enter"],
            T["end"], T["enter"],
            T["disp"], T["F"], T["enter"],
        ],
    ),
    "data": (
        "{3,1,4,1,5}->L1\nSortA(L1)\ncumSum(L1)->L2\nsum(L1)->S\nDisp L1\nDisp L2\nDisp S",
        [
            T["lbrace"], T["3"], T["comma"], T["1"], T["comma"], T["4"], T["comma"],
            T["1"], T["comma"], T["5"], T["rbrace"], T["store"], T["varlst"], 0x00, T["enter"],
            T["sorta"], T["varlst"], 0x00, T["rparen"], T["enter"],
            T["2byte"], T["cumsum"], T["varlst"], 0x00, T["rparen"], T["store"], T["varlst"], 0x01, T["enter"],
            T["sum"], T["varlst"], 0x00, T["rparen"], T["store"], T["S"], T["enter"],
            T["disp"], T["varlst"], 0x00, T["enter"],
            T["disp"], T["varlst"], 0x01, T["enter"],
            T["disp"], T["S"], T["enter"],
        ],
    ),
    "asmret": (
        "AsmPrgm\nC9",
        [
            T["2byte"], T["asmprgm"], T["enter"],
            T["C"], T["9"], T["enter"],
        ],
    ),
    "asmcall": (
        'Disp "BEFORE"\nAsm(prgmASMRET)\nDisp "AFTER"',
        [
            T["disp"], *string_literal("BEFORE"), T["enter"],
            T["2byte"], T["asm"], T["prog"], T["A"], T["S"], T["M"], T["R"], T["E"], T["T"], T["rparen"], T["enter"],
            T["disp"], *string_literal("AFTER"), T["enter"],
        ],
    ),
}

PROGRAM_NAMES = {
    "hello": "HELLO",
    "factorial": "FACTOR",
    "data": "DATA",
    "asmret": "ASMRET",
    "asmcall": "ASMCALL",
}


def hex_bytes(data: list[int]) -> str:
    return " ".join(f"{b:02X}" for b in data)


def ti83p_program_file(name: str, body: list[int]) -> bytes:
    """Return a TI-83+/84+ .8xp file for a tokenized program body."""
    calc_name = name.upper().encode("ascii")[:8]
    prog_data = len(body).to_bytes(2, "little") + bytes(body)

    entry = bytearray()
    entry += (13).to_bytes(2, "little")      # TI-83+ variable-header length.
    entry += len(prog_data).to_bytes(2, "little")
    entry += bytes([0x05])                   # ProgObj.
    entry += calc_name.ljust(8, b"\0")
    entry += bytes([0x00, 0x00])             # version, archive flag.
    entry += len(prog_data).to_bytes(2, "little")
    entry += prog_data

    header = (
        b"**TI83F*"
        + bytes([0x1A, 0x0A, 0x00])
        + b"Codex TI-BASIC trace sample".ljust(42, b" ")
    )
    payload = header + len(entry).to_bytes(2, "little") + entry
    return payload + (sum(entry) & 0xFFFF).to_bytes(2, "little")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write-dir",
        type=Path,
        help="write NAME.bas, NAME.tok, and TI-OS program NAME.8xp files",
    )
    args = parser.parse_args()

    for name, (source, body) in SAMPLES.items():
        print(f"{name} / prgm{PROGRAM_NAMES[name]}: {len(body)} bytes")
        print(source)
        print(hex_bytes(body))
        print()

    if args.write_dir:
        args.write_dir.mkdir(parents=True, exist_ok=True)
        for name, (source, body) in SAMPLES.items():
            (args.write_dir / f"{name}.bas").write_text(source + "\n", encoding="ascii")
            (args.write_dir / f"{name}.tok").write_text(hex_bytes(body) + "\n", encoding="ascii")
            (args.write_dir / f"{PROGRAM_NAMES[name]}.8xp").write_bytes(
                ti83p_program_file(PROGRAM_NAMES[name], body)
            )


if __name__ == "__main__":
    main()
