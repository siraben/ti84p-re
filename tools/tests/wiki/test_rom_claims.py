"""ROM-backed checks that address-catalog drift is detected, not regenerated."""

from pathlib import Path
import shutil
import tempfile
import unittest

from ti84re.paths import DEFAULT_ROM, ROOT
from ti84re.wiki.audit_rom_claims import audit


class RomClaimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = DEFAULT_ROM.read_bytes()

    def test_checked_catalogs_match_raw_rom(self):
        report = audit(self.rom)
        self.assertEqual([], report["issues"])
        self.assertEqual(732, report["wiki_rows"])
        self.assertEqual(87, report["bjump_rows"])

    def test_rejects_unrecognized_rom(self):
        with self.assertRaisesRegex(ValueError, "canonical retail"):
            audit(bytes(len(self.rom)))

    def test_detects_wrong_missing_duplicate_and_malformed_page_counts(self):
        original = (ROOT / "docs/flash-page-map.md").read_text()
        row = next(line for line in original.splitlines() if line.startswith("| `00` | 297 |"))
        mutations = (
            (row.replace("297", "296"), "main-table row counts"),
            ("", "missing or extra count rows"),
            (row + "\n" + row, "missing or extra count rows"),
            (row.replace("297", "unknown"), "malformed count row"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            shutil.copyfile(ROOT / "docs/bcall-index.md", root / "docs/bcall-index.md")
            shutil.copytree(ROOT / "tools/symbols", root / "tools/symbols")
            for replacement, expected in mutations:
                with self.subTest(expected=expected):
                    (root / "docs/flash-page-map.md").write_text(original.replace(row, replacement))
                    self.assertTrue(any(expected in issue for issue in audit(self.rom, root)["issues"]))

    def test_detects_wrong_missing_duplicate_and_renamed_wiki_rows(self):
        original = (ROOT / "docs/bcall-index.md").read_text()
        row = "| `_FPAdd` | `4072` | `00:229E` |"
        self.assertIn(row, original)
        mutations = (
            (row.replace("00:229E", "02:229E"), "target at 4072"),
            ("", "missing or extra IDs"),
            (row + "\n" + row, "duplicate 4072"),
            (row.replace("_FPAdd", "_FPSub"), "name at 4072"),
            (row + "\n| `_Bogus` | `4fff` | `ff:ffff` |", "name at 4FFF"),
            (row + "\n   | `_Bogus` | `4fff` | `ff:ffff` |", "name at 4FFF"),
            (row + "\n| `_Bogus` | garbage | broken |", "malformed table row"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            shutil.copyfile(ROOT / "docs/flash-page-map.md", root / "docs/flash-page-map.md")
            shutil.copytree(ROOT / "tools/symbols", root / "tools/symbols")
            for replacement, expected in mutations:
                with self.subTest(expected=expected):
                    (root / "docs/bcall-index.md").write_text(original.replace(row, replacement))
                    self.assertTrue(any(expected in issue for issue in audit(self.rom, root)["issues"]))


if __name__ == "__main__":
    unittest.main()
