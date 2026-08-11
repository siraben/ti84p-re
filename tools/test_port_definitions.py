"""Regression tests for project-local I/O-port labels."""

import unittest
from pathlib import Path

from port_definitions import (
    PortDefinitionError,
    load_port_definitions,
    parse_port_definitions,
)

TOOLS = Path(__file__).resolve().parent


class PortDefinitionTests(unittest.TestCase):
    def test_parses_comments_and_hexadecimal_ports(self):
        definitions = parse_port_definitions(
            "4B port_usbPowerControl # external orientation\n"
            "5A\tport_usbPresentationMirror\n"
        )

        self.assertEqual("port_usbPowerControl", definitions[0x4B].name)
        self.assertEqual("port_usbPresentationMirror", definitions[0x5A].name)

    def test_rejects_duplicate_ports_and_symbols(self):
        cases = (
            "4B port_one\n4B port_two\n",
            "4B port_same\n5A port_same\n",
        )
        for text in cases:
            with self.subTest(text=text), self.assertRaises(PortDefinitionError):
                parse_port_definitions(text)

    def test_rejects_malformed_rows(self):
        for text in ("100 port_too_high\n", "GG port_bad\n", "4B bad-name\n"):
            with self.subTest(text=text), self.assertRaises(PortDefinitionError):
                parse_port_definitions(text)

    def test_repository_labels_include_all_rom_used_usb_low_ports(self):
        definitions = load_port_definitions(TOOLS / "ports.txt")

        observed = {
            0x4A,
            0x4B,
            0x4C,
            0x4D,
            0x4F,
            0x50,
            0x54,
            0x55,
            0x56,
            0x57,
            0x5A,
            0x5B,
        }
        self.assertLessEqual(observed, definitions.keys())


if __name__ == "__main__":
    unittest.main()
