"""Regression tests for RAM-selector alias inference."""

import unittest

from ram_topology import (
    RAM_ALIAS_PATTERNS,
    RamTopologyObservation,
    decode_ram_alias_payload,
    infer_alias_groups,
    simulate_alias_writes,
)


class RamTopologyTests(unittest.TestCase):
    def test_independent_selectors_form_singleton_groups(self):
        groups = infer_alias_groups(RAM_ALIAS_PATTERNS)

        self.assertEqual(tuple((selector,) for selector in range(0x82, 0x88)), groups)

    def test_fully_shared_backing_uses_last_writer(self):
        observed = simulate_alias_writes((0, 0, 0, 0, 0, 0))

        self.assertEqual(bytes((0x66,)) * 6, observed)
        self.assertEqual((tuple(range(0x82, 0x88)),), infer_alias_groups(observed))

    def test_partial_alias_groups_are_recovered(self):
        observed = simulate_alias_writes((0, 0, 1, 1, 2, 3))

        self.assertEqual(bytes.fromhex("222244445566"), observed)
        self.assertEqual(
            ((0x82, 0x83), (0x84, 0x85), (0x86,), (0x87,)),
            infer_alias_groups(observed),
        )

    def test_impossible_last_writer_is_unclassified(self):
        self.assertIsNone(infer_alias_groups(bytes.fromhex("111133445566")))

    def test_unknown_pattern_is_unclassified(self):
        self.assertIsNone(infer_alias_groups(bytes.fromhex("992233445566")))

    def test_custom_selector_set_uses_its_own_length(self):
        groups = infer_alias_groups(
            bytes.fromhex("2040"),
            selectors=(0x90, 0x91),
            patterns=bytes.fromhex("2040"),
        )

        self.assertEqual(((0x90,), (0x91,)), groups)

    def test_observation_requires_six_bytes_per_phase(self):
        with self.assertRaisesRegex(ValueError, "original must contain 6 bytes"):
            RamTopologyObservation(
                original=b"short",
                observed=RAM_ALIAS_PATTERNS,
                restored=RAM_ALIAS_PATTERNS,
                alias_groups=tuple((selector,) for selector in range(0x82, 0x88)),
            )

    def test_observation_rejects_inconsistent_groups(self):
        with self.assertRaisesRegex(ValueError, "do not match"):
            RamTopologyObservation(
                original=bytes(6),
                observed=RAM_ALIAS_PATTERNS,
                restored=bytes(6),
                alias_groups=(tuple(range(0x82, 0x88)),),
            )

    def test_payload_reports_partial_topology_and_failed_restore(self):
        original = bytes.fromhex("102030405060")
        observed = bytes.fromhex("222244445566")
        restored = bytes.fromhex("102030405061")

        report = decode_ram_alias_payload(original + observed + restored).to_dict()

        self.assertEqual("partial-selector-aliases", report["topology_observation"])
        self.assertFalse(report["restore_matches"])
        self.assertEqual(
            [["0x82", "0x83"], ["0x84", "0x85"], ["0x86"], ["0x87"]],
            report["alias_groups"],
        )

    def test_payload_requires_exact_size(self):
        with self.assertRaisesRegex(ValueError, "18 bytes"):
            decode_ram_alias_payload(b"short")


if __name__ == "__main__":
    unittest.main()
