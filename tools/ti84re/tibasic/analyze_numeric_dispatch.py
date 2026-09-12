"""Verify numeric token widths, normalized selectors, and their ROM call edges.

These anchors establish dispatch and selected local semantics, not complete
numeric algorithms or runtime coverage. No inferred Ghidra names are inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ti84re.paths import DEFAULT_ROM
from ti84re.rom.bcall_tables import main_target
from ti84re.rom.image import RomImage
from ti84re.rom.signatures import TI84_PLUS_OS_255MP_SHA256


ANCHORS = (
    (0x38, 0x6FB2, "c664c36369", "BB-family selector normalization adds 64h"),
    (0x02, 0x635B, "fe912020f14737", "ref selector 91h sets carry"),
    (0x02, 0x6378, "f1cd6346", "restore carry and call row-echelon engine"),
    (0x02, 0x637F, "fe922005f147af18da", "rref selector 92h clears carry"),
    (0x02, 0x46DA, "f1f53811", "carry skips above-pivot elimination"),
    (0x02, 0x6388, "fe8d2028f1fe02", "cumSum selector 8Dh checks matrix type"),
    (0x02, 0x61C1, "fe8e2051f1fe04", "expr selector 8Eh checks string type"),
    (0x02, 0x609A, "fe2d200ef12004ef854bc9", "single-byte factorial token 2Dh calls 4B85h"),
    (0x02, 0x68F3, "fe24200ddfcd381b3e7b327984ef834ac9", "fnInt token 24h, tolerance 1e-5, bcall 4A83h"),
    (0x02, 0x6904, "fe252007cd2d21cdf36ac9", "nDeriv token 25h calls 6AF3h"),
    (0x02, 0x6927, "ef944b", "solve argument path calls 4B94h"),
    (0x00, 0x2621, "1600cdd73dc9", "Int selects zero decimal places for Round"),
    (0x00, 0x3DD7, "cd092b655102", "Round stub targets 02:5165"),
    (0x02, 0x6A57, "16093a7984f53e80327984cd2326", "RndGuard rounds normalized mantissa with D=9"),
    (0x00, 0x212D, "cde91dc018ea", "zero guard branches to ErrDomain via 211Dh"),
    (0x00, 0x1942, "3a7884e61fc9", "CkOP1Real returns masked class; no error jump"),
    (0x00, 0x1DE9, "3a7a84a7c9", "CkOP1FP0 tests the first mantissa byte only"),
    (0x00, 0x1FBF, "3a798421848496c9", "exponent difference uses SUB and unsigned borrow"),
    (0x02, 0x6CFE, "3e03cd1e7dcd8b23", "CLog scales argument by log10(e)"),
    (0x02, 0x6F5A, "cd6f1e3e80cda677cd8222", "near-one log rescales and calls inverse recurrence, then doubles"),
    (0x02, 0x7064, "1803cd2726", "EToX branches over TenX guard initialization"),
    (0x02, 0x74F8, "0423e5c53e0b96cb3f28ef5778805f", "trig product shift doubles the incremented digit index"),
    (0x06, 0x57C0, "47cdc1213809cdfc60380478c32b61", "FormBase is a typed formatter dispatcher"),
    (0x33, 0x640A, "0e01effe50", "real power enters base-10 log with selector C=1"),
    (0x33, 0x6419, "cd371acd6523cd0a26ef0151", "real power multiplies exponent and calls TenX2"),
)

BANKED_CALLS = (
    (0x4A83, 0x07, 0x6365, "fnInt integration entry"),
    (0x4B94, 0x39, 0x4039, "ITSOLVERB"),
    (0x462A, 0x02, 0x4663, "ROWECHELON"),
    (0x4B85, 0x35, 0x7995, "Factorial"),
    (0x4B88, 0x02, 0x7C23, "YONOFF"),
    (0x4741, 0x35, 0x7C7C, "CPYO1TOES15"),
    (0x47A1, 0x33, 0x6340, "real YToX power"),
    (0x4EA6, 0x02, 0x6D08, "complex TenX, not general power"),
    (0x4EA9, 0x02, 0x6D1D, "complex EtoX"),
    (0x4EB2, 0x02, 0x6D5C, "complex YtoX power"),
    (0x50AA, 0x06, 0x57C0, "typed numeric FormBase formatter"),
)


def build_report(path: Path = DEFAULT_ROM) -> dict:
    rom = RomImage.from_path(path)
    digest = hashlib.sha256(rom.data).hexdigest()
    if digest != TI84_PLUS_OS_255MP_SHA256:
        raise ValueError(f"unrecognized ROM SHA-256: {digest}")
    anchors = []
    for page, address, hex_bytes, meaning in ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom.bytes_at(page, address, len(expected))
        if actual != expected:
            raise ValueError(f"signature mismatch at {page:02X}:{address:04X}: {actual.hex()}")
        anchors.append({"location": f"{page:02X}:{address:04X}", "bytes": hex_bytes, "meaning": meaning})
    calls = []
    for identifier, page, address, meaning in BANKED_CALLS:
        target = main_target(rom, 0x3B, identifier)
        if target is None or (target.page, target.address) != (page, address):
            raise ValueError(f"unexpected target for {identifier:04X}")
        calls.append({"id": f"{identifier:04X}", "table_bytes": target.table_bytes.hex(),
                      "target": str(target.location), "meaning": meaning})
    return {"rom_sha256": digest, "anchors": anchors, "bcalls": calls,
            "scope": "Static dispatch and local instruction checks; no complete algorithm or runtime claim."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    args = parser.parse_args()
    print(json.dumps(build_report(args.rom), indent=2))


if __name__ == "__main__":
    main()
