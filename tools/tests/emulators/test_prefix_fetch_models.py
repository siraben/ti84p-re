#!/usr/bin/env python3
"""Regression tests for prefixed-opcode emulator-source classification."""

import unittest


from ti84re.emulators.prefix_fetch_models import PrefixFetchModelError, _case_counts, _require_once


class PrefixFetchModelTests(unittest.TestCase):
    def test_case_counts_preserve_the_indexed_cb_disagreement(self):
        tilem = _case_counts("tilem")
        wabbitemu = _case_counts("wabbitemu")

        self.assertEqual(2, tilem["dd_cb"])
        self.assertEqual(3, wabbitemu["dd_cb"])
        self.assertEqual(
            {"unprefixed", "cb", "ed", "dd", "dd_dd", "dd_cb"},
            set(tilem),
        )

    def test_require_once_returns_one_based_line(self):
        self.assertEqual(2, _require_once("a\ntarget\nc\n", "target", "fixture"))

    def test_require_once_rejects_missing_or_duplicate_structure(self):
        with self.assertRaisesRegex(PrefixFetchModelError, "found 0"):
            _require_once("a\n", "target", "fixture")
        with self.assertRaisesRegex(PrefixFetchModelError, "found 2"):
            _require_once("target\ntarget\n", "target", "fixture")


if __name__ == "__main__":
    unittest.main()
