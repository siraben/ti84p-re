#!/usr/bin/env python3
"""Regression tests for resolved trace-point parsing."""

import argparse
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_trace_points import TracePoint, parse_point


class TracePointTests(unittest.TestCase):
    def test_parses_overlay_point(self):
        self.assertEqual(
            TracePoint("page_3C", 0x7733),
            parse_point("page_3C:7733"),
        )

    def test_rejects_missing_space(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_point(":7733")


if __name__ == "__main__":
    unittest.main()
