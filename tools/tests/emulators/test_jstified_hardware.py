"""Regression tests for the pinned jsTIfied source profile."""

import unittest
from pathlib import Path
from unittest.mock import patch

from ti84re.emulators.jstified import (
    FINGERPRINTS,
    JSTIFIED_ARTIFACT_SHA256,
    JSTIFIED_ARTIFACT_SIZE,
    describe_artifact,
    verify_fingerprints,
)


class JstifiedHardwareTests(unittest.TestCase):
    def test_accepts_all_source_fingerprints(self):
        data = b"\n".join(item.fragment for item in FINGERPRINTS)
        self.assertEqual(len(FINGERPRINTS), len(verify_fingerprints(data)))

    def test_reports_missing_source_fingerprint(self):
        with self.assertRaisesRegex(ValueError, "LCD busy model"):
            verify_fingerprints(b"\n".join(
                item.fragment
                for item in FINGERPRINTS
                if item.feature != "LCD busy model"
            ))

    @patch("ti84re.emulators.jstified.verify_fingerprints", return_value=("verified",))
    @patch("ti84re.emulators.jstified.hashlib.sha256")
    @patch.object(Path, "read_bytes", return_value=b"x" * JSTIFIED_ARTIFACT_SIZE)
    def test_describes_exact_artifact(self, _read_bytes, sha256, _fingerprints):
        sha256.return_value.hexdigest.return_value = JSTIFIED_ARTIFACT_SHA256
        result = describe_artifact(Path("jstified.js"))
        self.assertEqual("jsTIfied", result["emulator"])
        self.assertFalse(result["features"]["usb"]["implemented"])

    @patch.object(Path, "read_bytes", return_value=b"drift")
    def test_rejects_size_drift(self, _read_bytes):
        with self.assertRaisesRegex(ValueError, "size"):
            describe_artifact(Path("jstified.js"))


if __name__ == "__main__":
    unittest.main()
