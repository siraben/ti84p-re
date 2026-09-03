#!/usr/bin/env python3
"""Regression tests for the dormant boot LCD diagnostic decoder."""

import unittest


from ti84re.boot.lcd_diagnostic import (
    contrast_sweep,
    key_prompts,
    lcd_diagnostic_reachability,
    lcd_fill_writes,
    lcd_line_writes,
    lcd_pattern_stages,
    validate_lcd_diagnostic_rom,
    visible_pattern,
)
from ti84re.rom.image import RomImage
from ti84re.paths import DEFAULT_ROM


class BootLcdDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = RomImage.from_path(DEFAULT_ROM)

    def test_exact_diagnostic_region_and_unreachable_guard(self):
        self.assertEqual((), validate_lcd_diagnostic_rom(self.rom))

        reachability = lcd_diagnostic_reachability(self.rom)
        self.assertEqual(0, reachability.a_before_compare)
        self.assertEqual(9, reachability.compared_value)
        self.assertFalse(reachability.zero_flag)
        self.assertFalse(reachability.reachable)

    def test_fill_helper_expands_all_visible_cells(self):
        writes = lcd_fill_writes(0x55, 0xAA)

        self.assertEqual(792, len(writes))
        self.assertEqual(24, sum(write.port == 0x10 for write in writes))
        self.assertEqual(768, sum(write.port == 0x11 for write in writes))
        self.assertEqual([0x55, 0xAA, 0x55], [write.value for write in writes[2:5]])

    def test_line_helper_writes_twelve_cells(self):
        writes = lcd_line_writes(0xBF, 0xFF)

        self.assertEqual(36, len(writes))
        self.assertEqual(0xBF, writes[0].value)
        self.assertEqual(0x20, writes[1].value)
        self.assertEqual(0xFF, writes[2].value)
        self.assertEqual(0x2B, writes[-2].value)

    def test_six_screen_patterns_and_bordered_first_stage(self):
        stages = lcd_pattern_stages()
        screen = visible_pattern(0x81, 0x81, bordered=True)

        self.assertEqual(6, len(stages))
        self.assertEqual(72, stages[0].command_writes)
        self.assertEqual(792, stages[0].data_writes)
        self.assertEqual(b"\xFF" * 12, screen[:12])
        self.assertEqual(b"\x81" * 12, screen[12:24])
        self.assertEqual(b"\xFF" * 12, screen[-12:])

    def test_contrast_sweep_is_darkest_down_through_level_25(self):
        steps = contrast_sweep()

        self.assertEqual(39, len(steps))
        self.assertEqual((0x27, 0xFF, 0x3F), (
            steps[0].counter,
            steps[0].command,
            steps[0].controller_level,
        ))
        self.assertEqual((0x01, 0xD9, 0x19), (
            steps[-1].counter,
            steps[-1].command,
            steps[-1].controller_level,
        ))

    def test_key_table_covers_physical_layout_and_final_enter(self):
        prompts = key_prompts(self.rom)

        self.assertEqual(49, len(prompts))
        self.assertEqual((0x35, "Y=", 11), (
            prompts[0].scan_code,
            prompts[0].key_name,
            prompts[0].display_value,
        ))
        self.assertEqual((0x09, "ENTER", 105), (
            prompts[-1].scan_code,
            prompts[-1].key_name,
            prompts[-1].display_value,
        ))
        self.assertEqual(49, len({prompt.scan_code for prompt in prompts}))
        self.assertEqual(
            [
                *range(11, 16),
                *range(21, 27),
                *range(31, 35),
                *range(41, 46),
                *range(51, 56),
                *range(61, 66),
                *range(71, 76),
                *range(81, 86),
                *range(91, 96),
                *range(102, 106),
            ],
            [prompt.display_value for prompt in prompts],
        )


if __name__ == "__main__":
    unittest.main()
