"""Tests for community-runtime calculator fixture builders."""

import unittest

from build_asm_wrapper import build_wrapper
from build_truvid_settings import build_settings
from hardware_probe import decode_ti_variable_file
from package_compiled_program import package_program


class CommunityRuntimeBuilderTests(unittest.TestCase):
    def test_assembly_wrapper(self) -> None:
        variable = decode_ti_variable_file(build_wrapper("NOEXEC"))
        self.assertEqual(variable.name, "AARUN")
        self.assertEqual(variable.data[2:], b"\xBB\x6A\x5FNOEXEC\x11\x3F")

    def test_compiled_program_requires_marker(self) -> None:
        with self.assertRaisesRegex(ValueError, "BB 6D"):
            package_program("BAD", b"\xC9")
        variable = decode_ti_variable_file(package_program("GOOD", b"\xBB\x6D\xC9"))
        self.assertEqual(variable.data[2:], b"\xBB\x6D\xC9")

    def test_archived_truvid_settings(self) -> None:
        variable = decode_ti_variable_file(build_settings(7, 178, archived=True))
        self.assertEqual(variable.variable_type, 0x15)
        self.assertEqual(variable.name, "TRUVID")
        self.assertTrue(variable.archived)
        self.assertEqual(variable.data, b"\x02\x00\x07\xB2")


if __name__ == "__main__":
    unittest.main()
