#!/usr/bin/env python3
"""Regression tests for reusable MD5-assist trace decoding."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hardware_trace import ResolvedIoEvent
from md5_hardware import (
    MD5_IMPLEMENTATIONS,
    Md5AssistImplementation,
    Md5TraceError,
    decode_md5_steps,
    md5_assist_value,
)


def event(index, direction, port, value):
    return ResolvedIoEvent(
        instruction_index=index,
        clock=1000 + index,
        logical_pc=0x6BE4,
        space="page_3F",
        address=0x6BE4,
        direction=direction,
        port=port,
        value=value,
        form="test",
    )


def word_events(start, direction, port, value):
    return [
        event(start + byte, direction, port, (value >> (8 * byte)) & 0xFF)
        for byte in range(4)
    ]


def first_md5_step():
    values = {
        0x18: 0x67452301,
        0x19: 0xEFCDAB89,
        0x1A: 0x98BADCFE,
        0x1B: 0x10325476,
        0x1C: 0x80636261,
        0x1D: 0xD76AA478,
    }
    events = [event(0, "OUT", 0x1F, 0)]
    index = 1
    for port in range(0x18, 0x1E):
        events.extend(word_events(index, "OUT", port, values[port]))
        index += 4
    events.append(event(index, "OUT", 0x1E, 7))
    index += 1
    result = 0xD6D117B4
    for port in range(0x1C, 0x20):
        events.append(event(index, "IN", port, result & 0xFF))
        result >>= 8
        index += 1
    return events


class Md5AssistTests(unittest.TestCase):
    def test_first_abc_step_matches_standard_result(self):
        self.assertEqual(
            0xD6D117B4,
            md5_assist_value(
                0,
                0x67452301,
                0xEFCDAB89,
                0x98BADCFE,
                0x10325476,
                0x80636261,
                0xD76AA478,
                7,
            ),
        )

    def test_decoder_recovers_little_endian_operands(self):
        step = list(decode_md5_steps(first_md5_step()))[0]

        self.assertEqual(0x67452301, step.a)
        self.assertEqual(0x80636261, step.x)
        self.assertEqual(0xD76AA478, step.t)
        self.assertEqual(7, step.shift)
        self.assertEqual(0xD6D117B4, step.result)
        self.assertTrue(step.verified)

    def test_decoder_ignores_unrelated_leading_io(self):
        leading = [event(0, "OUT", 0x10, 0x80)]
        self.assertEqual(1, len(list(decode_md5_steps(leading + first_md5_step()))))

    def test_decoder_rejects_wrong_transaction_order(self):
        events = first_md5_step()
        events[1] = event(1, "OUT", 0x19, events[1].value)

        with self.assertRaises(Md5TraceError):
            list(decode_md5_steps(events))

    def test_tilem_and_wabbitemu_execute_the_first_abc_step(self):
        operands = (
            0x67452301,
            0xEFCDAB89,
            0x98BADCFE,
            0x10325476,
            0x80636261,
            0xD76AA478,
        )
        for profile in ("tilem", "wabbitemu"):
            assist = Md5AssistImplementation(profile)
            assist.write_port(0x1F, 0)
            for port, value in zip(range(0x18, 0x1E), operands):
                assist.load_word(port, value)
            assist.write_port(0x1E, 7)

            self.assertEqual(0xD6D117B4, assist.result())
            self.assertEqual(
                [0xB4, 0x17, 0xD1, 0xD6],
                [assist.read_port(port) for port in range(0x1C, 0x20)],
            )
            self.assertEqual([0, 0, 0, 0], [
                assist.read_port(port) for port in range(0x18, 0x1C)
            ])

    def test_control_writes_are_masked(self):
        assist = Md5AssistImplementation("tilem")

        assist.write_port(0x1E, 0xFF)
        assist.write_port(0x1F, 0xFF)

        self.assertEqual(31, assist.shift)
        self.assertEqual(3, assist.mode)

    def test_result_bytes_recompute_after_operand_mutation(self):
        assist = Md5AssistImplementation("wabbitemu")
        for port, value in zip(range(0x18, 0x1E), (1, 2, 3, 4, 5, 6)):
            assist.load_word(port, value)
        assist.write_port(0x1E, 0)

        low_before = assist.read_port(0x1C)
        assist.load_word(0x18, 0xFFFFFFFF)
        high_after = assist.read_port(0x1F)

        self.assertNotEqual(low_before, assist.result() & 0xFF)
        self.assertEqual(high_after, assist.result() >> 24)

    def test_mame_omits_the_entire_md5_block(self):
        assist = Md5AssistImplementation("mame")

        self.assertFalse(assist.write_port(0x18, 0x12))
        self.assertIsNone(assist.read_port(0x1C))
        self.assertIsNone(assist.result())
        self.assertEqual([(0x18, 0x12)], assist.ignored_writes)
        self.assertEqual(set(), set(MD5_IMPLEMENTATIONS["mame"].mapped_ports))


if __name__ == "__main__":
    unittest.main()
