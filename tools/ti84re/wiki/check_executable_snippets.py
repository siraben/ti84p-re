#!/usr/bin/env python3
"""Check tagged Markdown Z80 examples against an executable assembly fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ti84re.wiki.executable_snippets import (
    ExecutableSnippetError,
    compare_snippets,
    load_assembly_snippets,
    load_markdown_snippets,
)
from ti84re.paths import ROOT, PROBES

DEFAULT_MARKDOWN = ROOT / "docs" / "flash-memory.md"
DEFAULT_ASSEMBLY = PROBES / "emulator" / "flash-bcall-usage.asm"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--assembly", type=Path, default=DEFAULT_ASSEMBLY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        manifest = compare_snippets(
            load_markdown_snippets(args.markdown),
            load_assembly_snippets(args.assembly),
        )
    except (OSError, ExecutableSnippetError) as error:
        parser.error(str(error))
    result = {
        "markdown": str(args.markdown),
        "assembly": str(args.assembly),
        "snippets": manifest,
    }
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(f"matched {len(manifest)} executable snippets")
    for name, fields in manifest.items():
        print(f"{name}: {fields['line_count']} lines, sha256={fields['sha256']}")


if __name__ == "__main__":
    main()
