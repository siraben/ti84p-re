#!/usr/bin/env python3
"""Build the TI-BASIC Asm(prgmSCRPROBE) wrapper for the scratch guard probe."""

import argparse
from pathlib import Path

from ti84re.tibasic.samples import T, letters, ti83p_program_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    body = [
        T["2byte"], T["asm"], T["prog"], *letters("SCRPROBE"),
        T["rparen"], T["enter"],
    ]
    args.output.write_bytes(ti83p_program_file("ASCRATCH", body))


if __name__ == "__main__":
    main()
