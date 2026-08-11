"""Tests for shared streaming file digests."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from file_hashes import file_sha256


class FileHashTests(unittest.TestCase):
    def test_hashes_in_configurable_bounded_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture"
            path.write_bytes(b"composable hashing")

            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                file_sha256(path, chunk_size=3),
            )

    def test_rejects_nonpositive_chunk_size(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            file_sha256(Path("unused"), chunk_size=0)


if __name__ == "__main__":
    unittest.main()
