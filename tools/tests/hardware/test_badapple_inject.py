"""The partial audio fixture must not corrupt the retail boot/USB bodies."""

import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from ti84re.badapple.inject import (
    APP_BASE_PAGE, APP_FIRST_PAGE, APP_LIMIT_PAGE, OFF_GETCSC, OFF_P22, OFF_P25, OFF_P26,
    PAGESZ, inject_rom, main,
)
from ti84re.paths import DEFAULT_ROM


class BadAppleInjectionTests(unittest.TestCase):
    def test_rejects_output_hardlinked_to_either_input(self):
        with tempfile.TemporaryDirectory() as directory:
            clean = Path(directory) / "clean.rom"
            app = Path(directory) / "app.bin"
            clean.write_bytes(b"original ROM")
            app.write_bytes(b"original app")
            for index, source in enumerate((clean, app)):
                output = Path(directory) / f"output-{index}.rom"
                output.hardlink_to(source)
                with patch("sys.argv", ["inject", str(clean), str(app), str(output)]):
                    with self.assertRaisesRegex(SystemExit, "overwrite either input"):
                        main()
            self.assertEqual(clean.read_bytes(), b"original ROM")
            self.assertEqual(app.read_bytes(), b"original app")

    def test_rejects_unknown_image_instead_of_patching_old_offsets(self):
        with self.assertRaisesRegex(ValueError, "canonical retail"):
            inject_rom(bytes(64 * PAGESZ), bytes(128))

    @unittest.skipUnless(DEFAULT_ROM.is_file(), "canonical ROM unavailable")
    def test_preserves_usb_page_and_uses_retail_protection_immediates(self):
        original = DEFAULT_ROM.read_bytes()
        result = inject_rom(original, b"".join(bytes((p,)) * PAGESZ for p in range(58)))
        self.assertEqual(len(original), len(result))
        self.assertEqual(original[0x2F * PAGESZ:0x30 * PAGESZ],
                         result[0x2F * PAGESZ:0x30 * PAGESZ])
        for page in range(39):
            destination = (APP_FIRST_PAGE - page) * PAGESZ
            self.assertEqual(result[destination:destination + PAGESZ],
                             bytes((page,)) * PAGESZ)
        self.assertEqual(result[OFF_GETCSC + 1], APP_FIRST_PAGE)
        self.assertEqual([original[p] for p in (OFF_P22, OFF_P25, OFF_P26)],
                         [0x08, 0x10, 0x20])
        self.assertEqual([result[p] for p in (OFF_P22, OFF_P25, OFF_P26)],
                         [0x40, 0x00, 0xFF])
        allowed = {OFF_P22, OFF_P25, OFF_P26, *range(OFF_GETCSC, OFF_GETCSC + 7)}
        self.assertTrue(all(a == b or i in allowed
                            or APP_BASE_PAGE * PAGESZ <= i < APP_LIMIT_PAGE * PAGESZ
                            for i, (a, b) in enumerate(zip(original, result))))
