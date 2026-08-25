"""Tests for exhaustive exact-probe matrix reporting."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from build_hardware_probes import PROBES
from run_exact_hardware_probe_matrix import run_probe_matrix, short_failure


class ExactHardwareProbeMatrixTest(unittest.TestCase):
    def test_tracked_summary_covers_every_probe(self) -> None:
        fixture = json.loads(
            (
                Path(__file__).parent
                / "fixtures"
                / "exact-hardware-probe-matrix.json"
            ).read_text(encoding="utf-8")
        )
        interactive = set(fixture["interactive_input_required"])
        self.assertEqual({"keypad-settle"}, interactive)
        for backend in fixture["backends"].values():
            codes = backend["verification_codes_decimal"]
            self.assertEqual(set(PROBES) - interactive, set(codes))
            self.assertEqual(24, backend["completed"])
            self.assertEqual(0, backend["failed"])

    def test_failure_diagnostic_is_bounded(self) -> None:
        completed = subprocess.CompletedProcess([], 2, "", "x" * 900)
        self.assertEqual(500, len(short_failure(completed)))

    def test_records_completed_failed_and_interactive_rows(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            rom = root / "rom.bin"
            binary = root / "runner"
            # This test exercises orchestration, not the project ROM identity.
            rom.write_bytes(b"test-rom")
            binary.write_bytes(b"test-runner")

            calls = 0

            def fake_run(command, **_kwargs):
                nonlocal calls
                calls += 1
                probe = command[command.index("--probe") + 1]
                probe_dir = Path(command[command.index("--output-dir") + 1])
                if probe == "ram-alias":
                    probe_dir.mkdir()
                    (probe_dir / "manifest.json").write_text(json.dumps({
                        "decoded_frame": {
                            "verification_code_decimal": 12345,
                            "measurements": {"restore_matches": True},
                        }
                    }), encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0, "ok\n", "")
                return subprocess.CompletedProcess(command, 3, "", "runner failed\n")

            # Patch the imported fixed ROM hash only around this host-only test.
            import run_exact_hardware_probe_matrix as matrix

            original = matrix.TI84_PLUS_OS_255MP_SHA256
            matrix.TI84_PLUS_OS_255MP_SHA256 = hashlib.sha256(
                b"test-rom"
            ).hexdigest()
            try:
                report = run_probe_matrix(
                    backend="tilem",
                    rom=rom,
                    binary=binary,
                    expected_binary_sha256=hashlib.sha256(b"test-runner").hexdigest(),
                    output_dir=root / "out",
                    probes=["ram-alias", "md5-edge", "keypad-settle"],
                    spasm="spasm",
                    include_interactive=False,
                    run=fake_run,
                )
            finally:
                matrix.TI84_PLUS_OS_255MP_SHA256 = original

            self.assertEqual(2, calls)
            self.assertEqual(
                {"completed": 1, "failed": 1, "interactive-input-required": 1},
                report["counts"],
            )
            self.assertEqual(
                12345, report["results"][0]["verification_code_decimal"]
            )
            self.assertEqual("failed", report["results"][1]["status"])
            self.assertEqual(
                "interactive-input-required", report["results"][2]["status"]
            )


if __name__ == "__main__":
    unittest.main()
