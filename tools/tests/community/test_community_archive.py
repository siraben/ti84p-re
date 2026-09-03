#!/usr/bin/env python3
"""Tests for the public community-archive inventory and extractor."""

from __future__ import annotations

import csv
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile


from ti84re.community.archive import extract_archive, inspect_tree, write_inventory


class CommunityArchiveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_zip(self, relative_path: str, members: dict[str, bytes]) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        return path

    def test_inventory_and_extract(self) -> None:
        self._write_zip(
            "shells/example.zip",
            {"src/main.z80": b" ret\n", "readme.txt": b"example"},
        )
        archives = inspect_tree(self.root)
        self.assertEqual(1, len(archives))
        self.assertEqual(1, archives[0].source_member_count)

        archive_csv = self.root / "archive.csv"
        member_csv = self.root / "member.csv"
        write_inventory(archives, archive_csv, member_csv)
        with archive_csv.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual("shells/example.zip", rows[0]["archive_path"])
        self.assertEqual("1", rows[0]["source_member_count"])

        destination = self.root / "extracted"
        extract_archive(archives[0], destination)
        self.assertEqual(
            b" ret\n",
            (destination / "shells/example.zip.contents/src/main.z80").read_bytes(),
        )

    def test_rejects_parent_traversal(self) -> None:
        self._write_zip("bad.zip", {"../escape": b"bad"})
        with self.assertRaisesRegex(ValueError, "unsafe member path"):
            inspect_tree(self.root)

    def test_preserves_symlink_as_inert_metadata(self) -> None:
        path = self.root / "link.zip"
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(info, "target")
        archives = inspect_tree(self.root)
        self.assertEqual("symlink", archives[0].members[0].kind)
        destination = self.root / "extracted"
        extract_archive(archives[0], destination)
        self.assertFalse((destination / "link.zip.contents/link").exists())
        self.assertEqual(
            b"target",
            (
                destination
                / "link.zip.contents/__archive_symlinks__/link.link-target"
            ).read_bytes(),
        )

    def test_preserves_duplicate_path(self) -> None:
        path = self.root / "duplicate.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("same", b"one")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr("same", b"two")
        archives = inspect_tree(self.root)
        self.assertEqual([1, 2], [member.occurrence for member in archives[0].members])
        destination = self.root / "extracted"
        extract_archive(archives[0], destination)
        self.assertEqual(
            b"one", (destination / "duplicate.zip.contents/same").read_bytes()
        )
        self.assertEqual(
            b"two",
            (
                destination
                / "duplicate.zip.contents/__archive_duplicates__/2/same"
            ).read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
