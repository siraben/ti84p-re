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
    "lparen": 0x10,
    "rparen": 0x11,
    "string": 0x2A,
    "comma": 0x2B,
    "enter": 0x3F,
    "space": 0x29,
    "add": 0x70,
    "sub": 0x71,
    "mul": 0x82,
    "div": 0x83,
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
    "U": 0x55,
    "V": 0x56,
    "W": 0x57,
    "X": 0x58,
    "Y": 0x59,
    "varlst": 0x5D,
    "prog": 0x5F,
    "varsys": 0x63,
    "eq": 0x6A,
    "clrdraw": 0x85,
    "text": 0x93,
    "line": 0x9C,
    "circle": 0xA5,
    "int": 0xB1,
    "sum": 0xB6,
    "if": 0xCE,
    "then": 0xCF,
    "while": 0xD1,
    "for": 0xD3,
    "end": 0xD4,
    "return": 0xD5,
    "prompt": 0xDD,
    "disp": 0xDE,
    "dispgraph": 0xDF,
    "output": 0xE0,
    "clrhome": 0xE1,
    "sorta": 0xE3,
    "2byte": 0xBB,
    "cumsum": 0x29,
    "asm": 0x6A,
    "asmprgm": 0x6C,
}

SYSVAR = {
    "Xmin": 0x0A,
    "Xmax": 0x0B,
    "Ymin": 0x0C,
    "Ymax": 0x0D,
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
    "animtext": (
        'ClrHome\nFor(I,1,8)\nOutput(1,I,"X")\nEnd\nDisp "DONE"',
        [
            T["clrhome"], T["enter"],
            T["for"], T["I"], T["comma"], T["1"], T["comma"], T["8"], T["rparen"], T["enter"],
            T["output"], T["1"], T["comma"], T["I"], T["comma"], *string_literal("X"), T["rparen"], T["enter"],
            T["end"], T["enter"],
            T["disp"], *string_literal("DONE"), T["enter"],
        ],
    ),
    "graphviz": (
        'ClrDraw\nLine(0,0,95,63)\nCircle(47,31,10)\nText(0,0,"DFS")\nDispGraph',
        [
            T["clrdraw"], T["enter"],
            T["line"], T["0"], T["comma"], T["0"], T["comma"], T["9"], T["5"], T["comma"], T["6"], T["3"], T["rparen"], T["enter"],
            T["circle"], T["4"], T["7"], T["comma"], T["3"], T["1"], T["comma"], T["1"], T["0"], T["rparen"], T["enter"],
            T["text"], T["0"], T["comma"], T["0"], T["comma"], *string_literal("DFS"), T["rparen"], T["enter"],
            T["dispgraph"], T["enter"],
        ],
    ),
    "graphdfs": (
        'ClrDraw\n'
        '0->Xmin\n94->Xmax\n0->Ymin\n62->Ymax\n'
        'Line(10,44,35,54)\n'
        'Line(10,44,35,14)\n'
        'Line(35,54,55,29)\n'
        'Circle(10,44,3)\n'
        'Circle(35,54,3)\n'
        'Circle(35,14,3)\n'
        'Circle(55,29,3)\n'
        'Text(16,8,"1")\n'
        'Text(6,33,"2")\n'
        'Text(46,33,"3")\n'
        'Text(31,53,"4")\n'
        'DispGraph',
        [
            T["clrdraw"], T["enter"],
            T["0"], T["store"], T["varsys"], SYSVAR["Xmin"], T["enter"],
            T["9"], T["4"], T["store"], T["varsys"], SYSVAR["Xmax"], T["enter"],
            T["0"], T["store"], T["varsys"], SYSVAR["Ymin"], T["enter"],
            T["6"], T["2"], T["store"], T["varsys"], SYSVAR["Ymax"], T["enter"],
            T["line"], T["1"], T["0"], T["comma"], T["4"], T["4"], T["comma"], T["3"], T["5"], T["comma"], T["5"], T["4"], T["rparen"], T["enter"],
            T["line"], T["1"], T["0"], T["comma"], T["4"], T["4"], T["comma"], T["3"], T["5"], T["comma"], T["1"], T["4"], T["rparen"], T["enter"],
            T["line"], T["3"], T["5"], T["comma"], T["5"], T["4"], T["comma"], T["5"], T["5"], T["comma"], T["2"], T["9"], T["rparen"], T["enter"],
            T["circle"], T["1"], T["0"], T["comma"], T["4"], T["4"], T["comma"], T["3"], T["rparen"], T["enter"],
            T["circle"], T["3"], T["5"], T["comma"], T["5"], T["4"], T["comma"], T["3"], T["rparen"], T["enter"],
            T["circle"], T["3"], T["5"], T["comma"], T["1"], T["4"], T["comma"], T["3"], T["rparen"], T["enter"],
            T["circle"], T["5"], T["5"], T["comma"], T["2"], T["9"], T["comma"], T["3"], T["rparen"], T["enter"],
            T["text"], T["1"], T["6"], T["comma"], T["8"], T["comma"], *string_literal("1"), T["rparen"], T["enter"],
            T["text"], T["6"], T["comma"], T["3"], T["3"], T["comma"], *string_literal("2"), T["rparen"], T["enter"],
            T["text"], T["4"], T["6"], T["comma"], T["3"], T["3"], T["comma"], *string_literal("3"), T["rparen"], T["enter"],
            T["text"], T["3"], T["1"], T["comma"], T["5"], T["3"], T["comma"], *string_literal("4"), T["rparen"], T["enter"],
            T["dispgraph"], T["enter"],
        ],
    ),
    "subrt": (
        'Disp "SUB"\nA+1->A\nReturn',
        [
            T["disp"], *string_literal("SUB"), T["enter"],
            T["A"], T["add"], T["1"], T["store"], T["A"], T["enter"],
            T["return"], T["enter"],
        ],
    ),
    "callsub": (
        "0->A\nprgmSUBRT\nDisp A",
        [
            T["0"], T["store"], T["A"], T["enter"],
            T["prog"], T["S"], T["U"], T["B"], T["R"], T["T"], T["enter"],
            T["disp"], T["A"], T["enter"],
        ],
    ),
    "bigadd": (
        "{5,4,3,2,1}->L1\n"
        "{5,6,7,8,9}->L2\n"
        "{0,0,0,0,0,0}->L3\n"
        "0->C\n"
        "For(I,1,5)\n"
        "L1(I)+L2(I)+C->S\n"
        "int(S/10)->C\n"
        "S-10*C->L3(I)\n"
        "End\n"
        "C->L3(6)\n"
        "Disp L3\n"
        "Disp L3(6)",
        [
            T["lbrace"], T["5"], T["comma"], T["4"], T["comma"], T["3"], T["comma"],
            T["2"], T["comma"], T["1"], T["rbrace"], T["store"], T["varlst"], 0x00, T["enter"],
            T["lbrace"], T["5"], T["comma"], T["6"], T["comma"], T["7"], T["comma"],
            T["8"], T["comma"], T["9"], T["rbrace"], T["store"], T["varlst"], 0x01, T["enter"],
            T["lbrace"], T["0"], T["comma"], T["0"], T["comma"], T["0"], T["comma"],
            T["0"], T["comma"], T["0"], T["comma"], T["0"], T["rbrace"], T["store"], T["varlst"], 0x02, T["enter"],
            T["0"], T["store"], T["C"], T["enter"],
            T["for"], T["I"], T["comma"], T["1"], T["comma"], T["5"], T["rparen"], T["enter"],
            T["varlst"], 0x00, T["lparen"], T["I"], T["rparen"], T["add"],
            T["varlst"], 0x01, T["lparen"], T["I"], T["rparen"], T["add"], T["C"], T["store"], T["S"], T["enter"],
            T["int"], T["S"], T["div"], T["1"], T["0"], T["rparen"], T["store"], T["C"], T["enter"],
            T["S"], T["sub"], T["1"], T["0"], T["mul"], T["C"], T["store"],
            T["varlst"], 0x02, T["lparen"], T["I"], T["rparen"], T["enter"],
            T["end"], T["enter"],
            T["C"], T["store"], T["varlst"], 0x02, T["lparen"], T["6"], T["rparen"], T["enter"],
            T["disp"], T["varlst"], 0x02, T["enter"],
            T["disp"], T["varlst"], 0x02, T["lparen"], T["6"], T["rparen"], T["enter"],
        ],
    ),
    "dfs": (
        "{1,1,2}->L1\n"
        "{2,3,4}->L2\n"
        "{0,0,0,0}->L3\n"
        "{1,0,0,0}->L4\n"
        "1->P\n"
        "While P\n"
        "L4(P)->V\n"
        "P-1->P\n"
        "If L3(V)=0\n"
        "Then\n"
        "1->L3(V)\n"
        "Disp V\n"
        "For(E,1,3)\n"
        "If L1(E)=V\n"
        "Then\n"
        "P+1->P\n"
        "L2(E)->L4(P)\n"
        "End\n"
        "End\n"
        "End\n"
        "End\n"
        "Disp L3",
        [
            T["lbrace"], T["1"], T["comma"], T["1"], T["comma"], T["2"], T["rbrace"], T["store"], T["varlst"], 0x00, T["enter"],
            T["lbrace"], T["2"], T["comma"], T["3"], T["comma"], T["4"], T["rbrace"], T["store"], T["varlst"], 0x01, T["enter"],
            T["lbrace"], T["0"], T["comma"], T["0"], T["comma"], T["0"], T["comma"], T["0"], T["rbrace"], T["store"], T["varlst"], 0x02, T["enter"],
            T["lbrace"], T["1"], T["comma"], T["0"], T["comma"], T["0"], T["comma"], T["0"], T["rbrace"], T["store"], T["varlst"], 0x03, T["enter"],
            T["1"], T["store"], T["P"], T["enter"],
            T["while"], T["P"], T["enter"],
            T["varlst"], 0x03, T["lparen"], T["P"], T["rparen"], T["store"], T["V"], T["enter"],
            T["P"], T["sub"], T["1"], T["store"], T["P"], T["enter"],
            T["if"], T["varlst"], 0x02, T["lparen"], T["V"], T["rparen"], T["eq"], T["0"], T["enter"],
            T["then"], T["enter"],
            T["1"], T["store"], T["varlst"], 0x02, T["lparen"], T["V"], T["rparen"], T["enter"],
            T["disp"], T["V"], T["enter"],
            T["for"], T["E"], T["comma"], T["1"], T["comma"], T["3"], T["rparen"], T["enter"],
            T["if"], T["varlst"], 0x00, T["lparen"], T["E"], T["rparen"], T["eq"], T["V"], T["enter"],
            T["then"], T["enter"],
            T["P"], T["add"], T["1"], T["store"], T["P"], T["enter"],
            T["varlst"], 0x01, T["lparen"], T["E"], T["rparen"], T["store"],
            T["varlst"], 0x03, T["lparen"], T["P"], T["rparen"], T["enter"],
            T["end"], T["enter"],
            T["end"], T["enter"],
            T["end"], T["enter"],
            T["end"], T["enter"],
            T["disp"], T["varlst"], 0x02, T["enter"],
        ],
    ),
}

PROGRAM_NAMES = {
    "hello": "HELLO",
    "factorial": "FACTOR",
    "data": "DATA",
    "asmret": "ASMRET",
    "asmcall": "ASMCALL",
    "animtext": "ANIMTXT",
    "graphviz": "GRAPHV",
    "graphdfs": "GRAPHDFS",
    "subrt": "SUBRT",
    "callsub": "CALLSUB",
    "bigadd": "BIGADD",
    "dfs": "DFS",
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
