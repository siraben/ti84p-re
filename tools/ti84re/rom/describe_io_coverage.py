#!/usr/bin/env python3
"""Verify the complete reviewed sets of direct and indirect ROM I/O candidates."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from ti84re.trace.hardware import count_resolved_trace_points
from ti84re.rom.port_definitions import PortDefinitionError, load_port_definitions
from ti84re.rom.image import RomImage
from ti84re.rom.io_coverage import audit_indirect_io, audit_unlisted_io
from ti84re.rom.z80_disassembly import DisassemblyError
from ti84re.paths import SYMBOLS, DEFAULT_ROM


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--ports-file", type=Path, default=SYMBOLS / "ports.txt")
    parser.add_argument("--z80dasm", default="z80dasm")
    parser.add_argument("--trace", type=Path, help="optional reset-origin TLMT trace")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        rom = RomImage.from_path(args.rom)
        definitions = load_port_definitions(args.ports_file)
        direct_report = audit_unlisted_io(
            rom, definitions, executable=args.z80dasm
        )
        indirect_report = audit_indirect_io(rom, executable=args.z80dasm)
        trace = None
        direct_points = {
            (f"page_{item.location.page:02X}", item.location.address)
            for item in direct_report.candidates
        }
        indirect_points = {
            (f"page_{item.location.page:02X}", item.location.address)
            for item in indirect_report.candidates
        }
        if args.trace is not None:
            trace = count_resolved_trace_points(
                args.trace,
                direct_points | indirect_points,
                initial_mapping="ti84p-reset",
            )
    except (OSError, PortDefinitionError, DisassemblyError, ValueError) as error:
        parser.error(str(error))

    payload = {
        "valid": direct_report.complete and indirect_report.complete,
        "exact_rom": direct_report.exact_rom and indirect_report.exact_rom,
        "rom_sha256": direct_report.rom_sha256,
        "candidate_count": len(direct_report.candidates),
        "classification_counts": direct_report.classification_counts,
        "missing_reviews": [
            asdict(item) for item in direct_report.missing_reviews
        ],
        "stale_reviews": [asdict(item) for item in direct_report.stale_reviews],
        "duplicate_candidate_locations": [
            str(item) for item in direct_report.duplicate_candidate_locations
        ],
        "duplicate_review_locations": [
            str(item) for item in direct_report.duplicate_review_locations
        ],
        "drift_errors": list(direct_report.drift_errors),
        "candidates": [
            {
                "location": str(item.candidate.location),
                "bytes": item.candidate.data.hex(),
                "direction": item.candidate.direction,
                "port": item.candidate.port,
                "instruction": item.candidate.instruction,
                "classification": item.review.classification,
                "evidence": item.review.evidence,
            }
            for item in direct_report.reviewed
        ],
        "indirect_candidate_count": len(indirect_report.candidates),
        "indirect_resolved_count": len(indirect_report.resolved),
        "indirect_classification_counts": indirect_report.classification_counts,
        "indirect_missing_reviews": [
            asdict(item) for item in indirect_report.missing_reviews
        ],
        "indirect_stale_reviews": [
            asdict(item) for item in indirect_report.stale_reviews
        ],
        "indirect_duplicate_candidate_locations": [
            str(item)
            for item in indirect_report.duplicate_candidate_locations
        ],
        "indirect_duplicate_review_locations": [
            str(item) for item in indirect_report.duplicate_review_locations
        ],
        "indirect_boundary_prefix_locations": [
            str(item) for item in indirect_report.boundary_prefix_locations
        ],
        "indirect_drift_errors": list(indirect_report.drift_errors),
        "indirect_candidates": [
            {
                "location": str(item.candidate.location),
                "bytes": item.candidate.data.hex(),
                "direction": item.candidate.direction,
                "form": item.candidate.form,
                "classification": item.review.classification,
                "evidence": item.review.evidence,
                "resolved_port": item.review.resolved_port,
            }
            for item in indirect_report.reviewed
        ],
        "trace": (
            None
            if trace is None
            else {
                "processed_instructions": trace.processed_instructions,
                "direct_candidate_hits": {
                    f"{space}:{address:04X}": count
                    for (space, address), count in sorted(trace.counts.items())
                    if (space, address) in direct_points
                },
                "indirect_candidate_hits": {
                    f"{space}:{address:04X}": count
                    for (space, address), count in sorted(trace.counts.items())
                    if (space, address) in indirect_points
                },
            }
        ),
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print("valid" if payload["valid"] else "invalid")
        print(
            f"ROM {payload['rom_sha256']}; "
            f"{payload['candidate_count']} direct candidate(s); "
            f"{payload['indirect_candidate_count']} indirect candidate(s)"
        )
        counts = payload["classification_counts"]
        print(
            ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
        )
        indirect_counts = payload["indirect_classification_counts"]
        print(
            "indirect: "
            + ", ".join(
                f"{name}={count}"
                for name, count in sorted(indirect_counts.items())
            )
        )
        for error in payload["drift_errors"]:
            print(f"error: {error}")
        for error in payload["indirect_drift_errors"]:
            print(f"error: {error}")
        if trace is not None:
            print(
                f"trace processed {trace.processed_instructions} instruction(s); "
                f"candidate hits={sum(trace.counts.values())}"
            )
    if not payload["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
