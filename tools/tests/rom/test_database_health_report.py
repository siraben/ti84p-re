import json
import unittest
from ti84re.paths import DATA


REPORT = DATA / "database-health.json"


class DatabaseHealthReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(REPORT.read_text())

    def test_report_identity_and_shape(self):
        report = self.report
        self.assertEqual(report["schema"], "ti84p-re.database-health.v1")
        self.assertEqual(
            report["rom_sha256"],
            "dbb47afae091ab36f9abe74e32083013fbeff3d7e0516bbf5d1abf4ee57adc09",
        )
        self.assertEqual(report["loaded_flash_pages"], 64)
        self.assertEqual(
            [row["page"] for row in report["pages"]],
            [f"{number:02X}" for number in range(64)],
        )
        self.assertTrue(all(row["bytes"] == 0x4000 for row in report["pages"]))

    def test_aggregate_counts_match_detail(self):
        report = self.report
        self.assertEqual(
            report["undefined_flash_bytes"],
            sum(row["undefined_bytes"] for row in report["pages"]),
        )
        self.assertEqual(
            report["unresolved_cross_page_jumps"],
            len(report["unresolved_cross_page_jump_locations"]),
        )
        self.assertEqual(
            report["symbols_without_typed_storage"],
            len(report["symbols_without_typed_storage_locations"]),
        )
        self.assertLessEqual(
            report["instructions_in_functions"], report["instruction_count"]
        )
        self.assertGreaterEqual(report["function_instruction_coverage_percent"], 0)
        self.assertLessEqual(report["function_instruction_coverage_percent"], 100)

    def test_health_invariants(self):
        report = self.report
        self.assertEqual(report["overlapping_instructions"], 0)
        self.assertGreater(report["instruction_count"], 0)
        self.assertGreater(report["function_count"], 0)


if __name__ == "__main__":
    unittest.main()
