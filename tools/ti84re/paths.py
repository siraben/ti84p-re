"""Repository locations shared by every ti84re module."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
DOCS = ROOT / "docs"
WEB = ROOT / "web"

SYMBOLS = TOOLS / "symbols"        # checked symbol, type, and equate registries
ORACLES = TOOLS / "oracles"        # checked JSON evidence reports and test oracles
DATA = TOOLS / "data"              # checked CSV observations
MACROS = TOOLS / "macros"          # headless TilEm macros
PROBES = TOOLS / "probes"          # probe sources (asm, C, Lua, C++)
TIBASIC_SAMPLES = TOOLS / "tibasic-samples"

DEFAULT_ROM = TOOLS / "rom.bin"    # local, gitignored complete OS 2.55MP image
PAGE0_ROM = TOOLS / "ti84_page00.bin"
