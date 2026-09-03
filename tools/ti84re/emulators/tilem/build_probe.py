#!/usr/bin/env python3
"""Build one direct-core probe from the exact pinned TilEm source tree.

Every probe links ``tilem_probe_support.c`` plus one probe-specific adapter
from ``tools/probes/tilem/`` against the complete pinned TilEm core.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ti84re.emulators.tilem.core import (
    TILEM_COMMIT,
    TILEM_TREE,
    TilemCoreError,
    build_probe,
    file_sha256,
)
from ti84re.paths import PROBES

SUPPORT_ADAPTER = "tilem_probe_support.c"

# probe name -> (adapter source, human description)
PROBE_ADAPTERS: dict[str, tuple[str, str]] = {
    "battery": ("tilem_battery_probe.c", "battery-comparator"),
    "flash": ("tilem_flash_probe.c", "Flash"),
    "interrupt": ("tilem_interrupt_probe.c", "interrupt"),
    "keypad": ("tilem_keypad_probe.c", "keypad"),
    "link": ("tilem_link_probe.c", "raw-link"),
    "md5": ("tilem_md5_probe.c", "MD5-assist"),
    "reset": ("tilem_reset_probe.c", "reset"),
    "timer": ("tilem_timer_probe.c", "timer/RTC"),
}


def adapters_for(probe: str) -> list[Path]:
    """Return the ordered adapter sources linked into one probe."""

    return [PROBES / "tilem" / SUPPORT_ADAPTER, PROBES / "tilem" / PROBE_ADAPTERS[probe][0]]


def build_report(
    probe: str, source: Path, output: Path, *, cc: str = "cc"
) -> dict[str, object]:
    """Compile one probe and return its provenance report."""

    adapters = adapters_for(probe)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = build_probe(source, adapters, output, cc=cc)
    return {
        "repository": "debrouxl/tilem",
        "commit": TILEM_COMMIT,
        "git_tree": TILEM_TREE,
        "probe": probe,
        "source": str(source),
        "adapters": [
            {"path": str(path), "sha256": file_sha256(path)} for path in adapters
        ],
        "output": str(output),
        "output_sha256": file_sha256(output),
        "command": command,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", choices=sorted(PROBE_ADAPTERS), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        parser.error(
            f"refusing to overwrite existing output {args.output}; use --force"
        )
    try:
        report = build_report(args.probe, args.source, args.output, cc=args.cc)
    except (OSError, TilemCoreError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        description = PROBE_ADAPTERS[args.probe][1]
        print(
            f"built pinned TilEm {TILEM_COMMIT[:8]} {description} probe: {args.output}"
        )
        print(f"binary SHA-256: {report['output_sha256']}")


if __name__ == "__main__":
    main()
