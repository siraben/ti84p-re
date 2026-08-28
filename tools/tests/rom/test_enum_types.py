#!/usr/bin/env python3
"""Static checks for the conservative Ghidra enum applications."""

from __future__ import annotations

import os
from pathlib import Path
import unittest

from ti84re.paths import DEFAULT_ROM, SYMBOLS, TOOLS


def load_enum(path: Path) -> dict[str, int]:
    rows: dict[str, int] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        fields = raw.split()
        if len(fields) >= 2:
            rows[fields[0]] = int(fields[1], 16)
    return rows


def manifest_rows() -> list[tuple[str, int, str, str, bytes]]:
    rows: list[tuple[str, int, str, str, bytes]] = []
    for raw in (SYMBOLS / "ty_enum_operands.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        address, operand, enum_name, member, byte_text = line.split()
        rows.append((address, int(operand), enum_name, member, bytes.fromhex(byte_text)))
    return rows


def rom_offset(address: str) -> int:
    space, logical_text = address.split(":")
    logical = int(logical_text, 16)
    if space == "ram":
        return logical
    if not space.startswith("page_"):
        raise ValueError(f"unsupported address space: {space}")
    page = int(space.removeprefix("page_"), 16)
    return page * 0x4000 + logical - 0x4000


class EnumTypeTests(unittest.TestCase):
    def test_operand_manifest_is_conservative_and_self_consistent(self) -> None:
        enums = {
            name: load_enum(SYMBOLS / filename)
            for name, filename in {
                "TIVarType": "ty_vartype.txt",
                "TIError": "ty_error.txt",
                "TIKeyCode": "ty_keycode.txt",
            }.items()
        }
        seen: set[tuple[str, int]] = set()
        rows = manifest_rows()
        for address, operand, enum_name, member, instruction in rows:
            self.assertIn(enum_name, enums)
            self.assertIn(member, enums[enum_name])
            self.assertEqual(instruction[-1], enums[enum_name][member])
            self.assertEqual(operand, {0x3E: 1, 0xFE: 0}[instruction[0]])
            self.assertNotIn((address, operand), seen)
            seen.add((address, operand))
        self.assertEqual({row[2] for row in rows}, set(enums))
        self.assertEqual(sum(row[2] == "TIVarType" for row in rows), 16)
        self.assertEqual(sum(row[2] == "TIError" for row in rows), 39)
        self.assertEqual(sum(row[2] == "TIKeyCode" for row in rows), 2)

    def test_operand_manifest_matches_supplied_rom(self) -> None:
        rom_path = Path(os.environ.get("TI84_ROM", DEFAULT_ROM))
        if not rom_path.is_file():
            self.skipTest("set TI84_ROM or provide tools/rom.bin for ROM-byte checks")
        rom = rom_path.read_bytes()
        for address, _operand, _enum_name, _member, instruction in manifest_rows():
            offset = rom_offset(address)
            self.assertEqual(rom[offset : offset + len(instruction)], instruction, address)

    def test_typed_regions_cover_each_enum(self) -> None:
        regions = (SYMBOLS / "ty_regions.txt").read_text(encoding="utf-8")
        for row in (
            "8444\tTIKeyCode\t\tkbdKey",
            "8450\tTIVarType\t\tcurType",
            "858D\tContext\t\tcxMain",
            "85D0\tTIVarType\t\tvarType",
            "86DD\tTIError\t\terrNo",
        ):
            self.assertIn(row, regions)

    def test_build_script_applies_and_checks_each_manifest_row(self) -> None:
        source = (TOOLS / "ghidra" / "BuildTypes.java").read_text(encoding="utf-8")
        self.assertIn('println("Applied enum operands: " + applyEnumOperands())', source)
        self.assertIn("scalar.getUnsignedValue() != expected", source)
        self.assertIn("Arrays.equals(instruction.getBytes(), expectedBytes)", source)
        self.assertIn("new CreateEnumEquateCommand(singleton, enumType, false)", source)
        self.assertIn("!equate.isEnumBased() || !equate.isValidUUID()", source)
        self.assertIn("enumType.getUniversalID().equals(equate.getEnumUUID())", source)


if __name__ == "__main__":
    unittest.main()
