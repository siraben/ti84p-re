#!/usr/bin/env python3
"""Decode an exported TI-84 Plus physical hardware-probe AppVar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ti84re.hardware.probe import ProbeFormatError, probe_appvar_report


def frame_report(path: Path) -> dict[str, object]:
    """Return a serializable report for one exported probe AppVar."""

    return probe_appvar_report(path.read_bytes(), path=str(path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("appvar", type=Path, nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        reports = [frame_report(path) for path in args.appvar]
    except (OSError, ProbeFormatError) as error:
        parser.error(str(error))
    if args.json:
        print(json.dumps({"probes": reports}, indent=2))
        return
    for report in reports:
        print(
            f"{report['variable_name']}: {report['probe_name']} "
            f"format={report['format_version']} ASIC={report['asic_id_hex']} "
            f"status={report['status_hex']} "
            f"verification={report['verification_code_decimal']} "
            f"payload={report['payload_hex']}"
        )
        print(json.dumps(report["measurements"], indent=2))


if __name__ == "__main__":
    main()
