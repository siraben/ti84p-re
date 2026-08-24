"""Pinned ROM identities shared by reverse-engineering tools."""

TI84_PLUS_OS_255MP_SHA256 = (
    "7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d"
)

TI84_PLUS_PATCHED_BASE_SHA256 = (
    "90472848b5f56902287fd5d8b455e62d60e9ab054647c9a03c1c91a67fc1a95a"
)

# The same OS pages with the BootFree 11.259 replacement in page 0x3F and the
# patched-base page 0x2F. This is useful for emulator runtime traces, but it is
# not the canonical retail-boot analysis image above.
TI84_PLUS_OS_255MP_BOOTFREE_SHA256 = (
    "dbb47afae091ab36f9abe74e32083013fbeff3d7e0516bbf5d1abf4ee57adc09"
)
BOOTFREE_11259_PAGE_SHA256 = (
    "b3ae75aa81231de15e5931746d79834863132d5e4dca01010e3a8e24aabd3003"
)

D84PBE1_APPVAR_SHA256 = (
    "82a85f12f8aa8f102a477d71eb2d49ba55ac3dd7bbf3f7e2690686da231f1779"
)
D84PBE1_PAGE_SHA256 = (
    "85b06d180b411a17932dbd584ba9cbd2123323abc555dbd1366a24b38803067b"
)

D84PBE2_APPVAR_SHA256 = (
    "70312bd0d8da3a9edf6086aa75e776442484e2562fef4ee2c185c182df5b4357"
)
D84PBE2_PAGE_SHA256 = (
    "81f98a11c3fbb12c3258fcaa4ff1945e18ddeb8ca6fbc7b8af43243c2cbc3c8c"
)
