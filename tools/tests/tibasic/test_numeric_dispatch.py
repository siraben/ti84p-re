"""Guard dispatch identities against source-token and inferred-name confusion."""

import unittest
import re

from ti84re.paths import DEFAULT_ROM, DOCS, SYMBOLS
from ti84re.tibasic.analyze_numeric_dispatch import build_report


@unittest.skipUnless(DEFAULT_ROM.is_file(), "pinned ROM not present")
class NumericDispatchTests(unittest.TestCase):
    def test_dispatch_and_callees_match_raw_rom(self):
        report = build_report()
        calls = {row["id"]: row["target"] for row in report["bcalls"]}
        self.assertEqual(calls["4A83"], "07:6365")
        self.assertEqual(calls["462A"], "02:4663")
        self.assertNotEqual(calls["4B85"], calls["462A"])
        self.assertNotEqual(calls["4B88"], calls["462A"])
        self.assertIn("no complete algorithm", report["scope"])
        self.assertEqual(calls["47A1"], "33:6340")
        self.assertEqual(calls["4EA6"], "02:6D08")

    def test_every_documented_float_coefficient_row_matches_rom(self):
        blocks = re.findall(r"```text\n(.*?)```", (DOCS / "floating-point.md").read_text(), re.S)
        rom = DEFAULT_ROM.read_bytes()
        for base, marker, stride, count in (
            (0x7D42, "02:7D42", 9, 7),
            (0x7181, "[00] 30 10", 8, 16),
            (0x7201, "02:7201:", 16, 8),
            (0x7281, "02:7281:", 16, 8),
        ):
            block = next(block for block in blocks if marker in block)
            if base == 0x7201:
                block = block.split("02:7281:")[0]
            elif base == 0x7281:
                block = block.split("02:7281:")[1]
            rows = re.findall(r"\[(\d\d)\] ([^\[\n;]+)", block)
            self.assertEqual(len(rows), count)
            self.assertEqual([int(index) for index, _ in rows], list(range(count)))
            for index, digits in rows:
                values = bytes.fromhex(digits.replace("|", " "))
                self.assertEqual(len(values), stride)
                offset = 0x8000 + base - 0x4000 + stride * int(index)
                self.assertEqual(rom[offset:offset + stride], values)

    def test_integration_name_is_consistent_in_bcall_catalogs(self):
        names = dict(line.split() for line in (SYMBOLS / "bcalls.txt").read_text().splitlines()
                     if line.strip() and not line.startswith("#"))
        target_rows = [line.split() for line in (SYMBOLS / "bcall_targets.txt").read_text().splitlines()
                       if line.strip() and not line.startswith("#")]
        target = next(row for row in target_rows if row[1] == "4A83")
        self.assertEqual(names["4A83"], "fnint_integrate")
        self.assertEqual(target, ["fnint_integrate", "4A83", "6365", "07"])


if __name__ == "__main__":
    unittest.main()
