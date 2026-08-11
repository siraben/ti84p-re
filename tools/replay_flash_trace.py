#!/usr/bin/env python3
"""Replay accepted Flash commands into final or interrupted GC images."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path

from file_hashes import file_sha256
from flash_replay import (
    FlashReplayError,
    find_gc_phase_snapshots,
    replay_accepted_commands,
)
from flash_trace import (
    FLASH_WRITE_SEMANTICS,
    decode_amd_flash_commands,
    group_byte_program_invocations,
)
from hardware_trace import iter_resolved_memory_writes, trace_header
from rom_signatures import TI84_PLUS_OS_255MP_SHA256

TOOLS = Path(__file__).resolve().parent


def parse_phase(value: str) -> int:
    phase = int(value, 0)
    if not 0 <= phase <= 0xFF:
        raise argparse.ArgumentTypeError("phase must be a byte")
    return phase


def validate_replay_stream(commands) -> Counter[str]:
    """Reject decoded streams whose worker outcomes are incomplete or failed."""

    if not commands:
        raise FlashReplayError("trace contains no decoded Flash commands")
    counts = Counter(command.kind for command in commands)
    if counts["unmatched_write"]:
        raise FlashReplayError(
            f"trace contains {counts['unmatched_write']} unmatched Flash write(s)"
        )
    outcomes = Counter(
        invocation.worker_outcome
        for invocation in group_byte_program_invocations(commands)
    )
    unsafe = {
        name: count
        for name, count in outcomes.items()
        if name not in {"success", "certificate-success"}
    }
    if unsafe:
        rendered = ", ".join(f"{name}={count}" for name, count in sorted(unsafe.items()))
        raise FlashReplayError(f"trace has non-successful program invocation(s): {rendered}")
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="replay the complete command stream into one output image",
    )
    parser.add_argument(
        "--phase",
        action="append",
        type=parse_phase,
        help="active GC phase to materialize; repeatable",
    )
    parser.add_argument(
        "--expected-rom-sha256",
        default=TI84_PLUS_OS_255MP_SHA256,
        help="required source identity (default: pinned OS 2.55MP image)",
    )
    parser.add_argument(
        "--initial-mapping",
        choices=("unknown", "ti84p-reset"),
        default="ti84p-reset",
    )
    parser.add_argument("--resync", action="store_true")
    parser.add_argument(
        "--accept-command-shapes",
        action="store_true",
        help=(
            "acknowledge that TLMT records CPU write attempts rather than ASIC/device "
            "acceptance; required before producing images"
        ),
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if bool(args.phase) == bool(args.output):
        parser.error("choose either one or more --phase values or one --output")
    if args.phase and args.output_dir is None:
        parser.error("--output-dir is required with --phase")
    if args.output and args.output_dir is not None:
        parser.error("--output-dir applies only to --phase snapshots")
    if not args.accept_command_shapes:
        parser.error(
            "--accept-command-shapes is required because the trace does not encode "
            "ASIC/device acceptance"
        )
    try:
        source = args.rom.read_bytes()
        source_digest = sha256(source).hexdigest()
        expected_digest = args.expected_rom_sha256.casefold()
        if source_digest != expected_digest:
            raise FlashReplayError(
                f"source ROM SHA-256 is {source_digest}; expected {expected_digest}"
            )
        writes = []
        unresolved = 0
        for event in iter_resolved_memory_writes(
            args.trace,
            initial_mapping=args.initial_mapping,
            resync=args.resync,
        ):
            if event.unresolved:
                unresolved += 1
            elif event.target_kind == "flash":
                writes.append(event)
        if unresolved:
            raise FlashReplayError(
                f"trace contains {unresolved} unresolved memory write(s)"
            )
        commands = list(decode_amd_flash_commands(writes))
        outcomes = validate_replay_stream(commands)
        artifacts = []
        if args.phase:
            snapshots = find_gc_phase_snapshots(source, commands, args.phase)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            for snapshot in snapshots:
                output = args.output_dir / f"gc-phase-{snapshot.phase:02x}.rom"
                if output.exists() and not args.force:
                    raise FlashReplayError(
                        f"refusing to overwrite existing output {output}; use --force"
                    )
                output.write_bytes(snapshot.replay.image)
                artifacts.append(
                    {
                        "phase": snapshot.phase,
                        "active_half_base": snapshot.half_base,
                        "trigger_clock": snapshot.trigger_clock,
                        "trigger_kind": snapshot.trigger_kind,
                        "trigger_address": snapshot.trigger_address,
                        "commands_applied": snapshot.replay.commands_applied,
                        "command_counts": dict(snapshot.replay.command_counts),
                        "changed_command_count": sum(
                            mutation.changed_bytes > 0
                            for mutation in snapshot.replay.mutations
                        ),
                        "changed_byte_events": sum(
                            mutation.changed_bytes
                            for mutation in snapshot.replay.mutations
                        ),
                        "output": str(output),
                        "output_sha256": sha256(snapshot.replay.image).hexdigest(),
                    }
                )
        else:
            if args.output.exists() and not args.force:
                raise FlashReplayError(
                    f"refusing to overwrite existing output {args.output}; use --force"
                )
            replay = replay_accepted_commands(source, commands)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(replay.image)
            artifacts.append(
                {
                    "phase": None,
                    "active_half_base": None,
                    "trigger_clock": replay.last_clock,
                    "trigger_kind": "end_of_trace",
                    "trigger_address": None,
                    "commands_applied": replay.commands_applied,
                    "command_counts": dict(replay.command_counts),
                    "changed_command_count": sum(
                        mutation.changed_bytes > 0
                        for mutation in replay.mutations
                    ),
                    "changed_byte_events": sum(
                        mutation.changed_bytes
                        for mutation in replay.mutations
                    ),
                    "output": str(args.output),
                    "output_sha256": sha256(replay.image).hexdigest(),
                }
            )
        header = trace_header(args.trace)
        report = {
            "source_rom": str(args.rom),
            "source_rom_sha256": source_digest,
            "trace": str(args.trace),
            "trace_sha256": file_sha256(args.trace),
            "trace_header": {
                "version": header.version,
                "range_start": header.range_start,
                "range_end": header.range_end,
            },
            "write_semantics": FLASH_WRITE_SEMANTICS,
            "acceptance_scope": (
                "commands are replayed under caller-acknowledged accepted-device "
                "semantics after rejecting non-successful OS program invocations, "
                "unmatched writes, and unresolved writes; TLMT alone does not record "
                "ASIC or device acceptance"
            ),
            "program_outcomes": dict(sorted(outcomes.items())),
            "artifacts": artifacts,
        }
    except (OSError, FlashReplayError, ValueError) as error:
        parser.error(str(error))
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
        return
    print(f"source ROM SHA-256: {report['source_rom_sha256']}")
    print(f"trace SHA-256: {report['trace_sha256']}")
    print(f"program outcomes: {report['program_outcomes']}")
    for artifact in report["artifacts"]:
        phase = (
            "final"
            if artifact["phase"] is None
            else f"phase 0x{artifact['phase']:02X}"
        )
        half = (
            ""
            if artifact["active_half_base"] is None
            else f" half=0x{artifact['active_half_base']:05X}"
        )
        print(
            f"{phase}: clock={artifact['trigger_clock']}{half} -> "
            f"{artifact['output']} "
            f"sha256={artifact['output_sha256']}"
        )


if __name__ == "__main__":
    main()
