#!/usr/bin/env python3
"""Regression tests for USB/FDRC and pinned-emulator helpers."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from usb_hardware import (
    USB_EMULATOR_PROFILES,
    USB_LAYOUT_SOURCES,
    boot_usb_event_action,
    compare_usb_global_layouts,
    decode_fdrc_bits,
    decode_link_assist_rate,
    decode_usb_line_state,
    emulator_initial_usb_read,
    fdrc_register,
    main_usb_event_targets,
    usb_active_low_summary_bits,
    wabbitemu_port4a_read,
    wabbitemu_port4a_write,
    wabbitemu_port4c_read,
    wabbitemu_port4d_read,
    wabbitemu_usb_summary,
)


class UsbHardwareTests(unittest.TestCase):
    def test_layout_comparison_exposes_discriminating_offsets(self):
        rows = {row.port: row for row in compare_usb_global_layouts()}

        self.assertTrue(rows[0x80].same_names)
        self.assertEqual(("INTRUSB",), rows[0x86].fdrc_names)
        self.assertEqual(("INTRTX1E",), rows[0x86].hdrc_names)
        self.assertEqual(("DEVCTL",), rows[0x8F].fdrc_names)
        self.assertEqual(("TESTMODE",), rows[0x8F].hdrc_names)

    def test_layout_sources_preserve_provenance_limits(self):
        self.assertEqual(3, len(USB_LAYOUT_SOURCES))
        self.assertIn("proprietary", USB_LAYOUT_SOURCES[0].provenance)
        self.assertIn("does not identify", USB_LAYOUT_SOURCES[0].limit)

    def test_fdrc_global_and_indexed_aliases(self):
        self.assertEqual(("FADDR",), fdrc_register(0x80).names)
        self.assertEqual(("CSR0", "TXCSR1"), fdrc_register(0x91).names)
        self.assertTrue(fdrc_register(0x91).indexed_role)
        self.assertEqual(("RXFIFO2", "FIFOSIZE", "CONFIGDATA"), fdrc_register(0x9F).names)

    def test_fdrc_fifo_offsets_are_sequential_in_non_ahb_layout(self):
        fifo = fdrc_register(0xA2)
        self.assertEqual(("FIFO2",), fifo.names)
        self.assertEqual(2, fifo.endpoint)
        self.assertIsNone(fdrc_register(0xB0))

    def test_imported_global_bit_decoders(self):
        self.assertEqual(("VBUSVAL",), decode_fdrc_bits(0x81, 0x40))
        self.assertEqual(("RESET/BABBLE", "CONNECT"), decode_fdrc_bits(0x86, 0x14))
        self.assertEqual(("SESSION", "HOST_MODE", "B_DEVICE"), decode_fdrc_bits(0x8F, 0x85))

    def test_wabbitemu_disconnected_line_state(self):
        state = decode_usb_line_state(0xA5)
        self.assertEqual("low", state.d_plus)
        self.assertEqual("low", state.d_minus)
        self.assertEqual("high", state.id)
        self.assertEqual("low", state.vbus)

    def test_line_decoder_exposes_invalid_paired_states(self):
        state = decode_usb_line_state(0xC0)
        self.assertEqual("both", state.vbus)
        self.assertEqual("neither", state.d_plus)

    def test_summary_is_active_low_only_in_low_five_bits(self):
        self.assertEqual((), usb_active_low_summary_bits(0x1F))
        self.assertEqual((2,), usb_active_low_summary_bits(0x1B))
        self.assertEqual((0, 1, 2, 3, 4), usb_active_low_summary_bits(0xE0))

    def test_main_and_boot_event_decoders_keep_distinct_routing(self):
        self.assertEqual(
            ("35:4B6A line/event settle", "35:40B2 USB setup"),
            main_usb_event_targets(0x50),
        )
        self.assertEqual("line-state cleanup and wait", boot_usb_event_action(0x70))
        self.assertEqual("_InitUSB", boot_usb_event_action(0x40))
        self.assertEqual("common error exit", boot_usb_event_action(0x80))

    def test_link_assist_rom_values(self):
        slow = decode_link_assist_rate(0x97)
        fast = decode_link_assist_rate(0xB4)
        halted = decode_link_assist_rate(0xE0)
        self.assertEqual((16, 0x17), (slow.divisor, slow.inter_bit_wait))
        self.assertEqual((32, 0x14), (fast.divisor, fast.inter_bit_wait))
        self.assertTrue(halted.halted)
        self.assertIsNone(halted.divisor)

    def test_pinned_emulator_initial_reads(self):
        self.assertEqual(3, len(USB_EMULATOR_PROFILES))
        self.assertEqual(0x22, emulator_initial_usb_read("TilEm", 0x4C))
        self.assertEqual(0x50, emulator_initial_usb_read("Wabbitemu", 0x56))
        self.assertEqual(0, emulator_initial_usb_read("MAME", 0x56))
        self.assertIsNone(emulator_initial_usb_read("MAME", 0x4D))

    def test_wabbitemu_port4a_write_reproduces_inconsistent_pairs(self):
        result = wabbitemu_port4a_write(0x08)
        self.assertEqual(0x08, result.stored_port4a)
        self.assertEqual(0xE5, result.line_state_after)
        self.assertEqual(0x58, result.events_after)
        self.assertTrue(result.line_interrupt)
        self.assertEqual("both", decode_usb_line_state(result.line_state_after).vbus)

    def test_wabbitemu_read_handlers_preserve_source_quirks(self):
        self.assertEqual(
            0x09,
            wabbitemu_port4a_read(
                0x08, port54=0x44, port4c=0x08, line_state=0xE5
            ),
        )
        self.assertEqual(0x2A, wabbitemu_port4c_read(0x08, port54=0))
        self.assertEqual(
            0xA7, wabbitemu_port4d_read(0xA6, port54=0, port4c=0)
        )
        self.assertEqual(
            0xE7,
            wabbitemu_port4d_read(0xE5, port54=0x44, port4c=0x08),
        )

    def test_wabbitemu_usb_summary_matrix_is_active_low(self):
        self.assertEqual(
            0x1F,
            wabbitemu_usb_summary(
                line_interrupt=False, protocol_interrupt=False
            ),
        )
        self.assertEqual(
            0x1B,
            wabbitemu_usb_summary(
                line_interrupt=True, protocol_interrupt=False
            ),
        )
        self.assertEqual(
            0x0F,
            wabbitemu_usb_summary(
                line_interrupt=False, protocol_interrupt=True
            ),
        )
        self.assertEqual(
            0x0B,
            wabbitemu_usb_summary(
                line_interrupt=True, protocol_interrupt=True
            ),
        )

    def test_rejects_invalid_values_and_unsupported_bit_port(self):
        with self.assertRaises(ValueError):
            fdrc_register(0x100)
        with self.assertRaises(ValueError):
            decode_fdrc_bits(0x90, 0)
        with self.assertRaises(ValueError):
            decode_link_assist_rate(-1)


if __name__ == "__main__":
    unittest.main()
