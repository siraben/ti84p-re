#!/usr/bin/env python3
"""Tests for MathPrint dynamic call attribution."""

from __future__ import annotations

import unittest

from ti84re.mathprint.analyze_draw_trace import DynamicCallStack, is_taken_call
from ti84re.trace.hardware import ResolvedInstruction


def instruction(index: int, address: int, opcode: int, sp: int) -> ResolvedInstruction:
    return ResolvedInstruction(
        instruction_index=index,
        clock=index,
        logical_pc=address,
        space="page_34",
        address=address,
        flat_address=None,
        page=0x34,
        physical_page=None,
        opcode=opcode,
        af=0,
        bc=0,
        de=0,
        hl=0,
        ix=0,
        iy=0,
        sp=sp,
        wz=0,
    )


class CallRecognitionTests(unittest.TestCase):
    def test_taken_call_requires_opcode_and_stack_change(self) -> None:
        current = instruction(1, 0x5000, 0, 0xFFFC)
        self.assertTrue(is_taken_call(instruction(0, 0x4000, 0xCD, 0xFFFE), current))
        self.assertFalse(is_taken_call(instruction(0, 0x4000, 0xC5, 0xFFFE), current))
        self.assertFalse(is_taken_call(instruction(0, 0x4000, 0xCD, 0xFFFC), current))

    def test_prefixed_low_byte_does_not_masquerade_as_rst(self) -> None:
        previous = instruction(0, 0x4000, 0xCBC7, 0xFFFE)
        current = instruction(1, 0x4002, 0, 0xFFFC)
        self.assertFalse(is_taken_call(previous, current))

    def test_stack_unwinds_before_entering_sibling(self) -> None:
        stack = DynamicCallStack()
        call_a = instruction(0, 0x4000, 0xCD, 0xFFFE)
        body_a = instruction(1, 0x5000, 0, 0xFFFC)
        call_b = instruction(2, 0x5001, 0xCD, 0xFFFC)
        body_b = instruction(3, 0x6000, 0, 0xFFFA)
        returned = instruction(4, 0x5004, 0, 0xFFFC)

        self.assertEqual(len(stack.advance(call_a, body_a)), 1)
        self.assertEqual(len(stack.advance(call_b, body_b)), 2)
        frames = stack.advance(body_b, returned)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].callee.address, 0x5000)


if __name__ == "__main__":
    unittest.main()
