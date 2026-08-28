#!/usr/bin/env python3
"""Run and validate the reversible small-font code in two emulator cores."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ti84re.hardware.build_probes import PROBES, assemble_machine_code
from ti84re.hardware.compact_probe_code import decode_compact_probe_code, encode_compact_probe_code
from ti84re.file_hashes import file_sha256
from ti84re.hardware.probe import decode_probe_frame, probe_verification_code
from ti84re.emulators.probe_cli import DEFAULT_ROM, require_exact_hash
from ti84re.rom.signatures import TI84_PLUS_OS_255MP_SHA256
from ti84re.emulators.tilem.core import TILEM_COMMIT, TILEM_TREE
from ti84re.emulators.wabbitemu.headless import WABBITEMU_COMMIT, WABBITEMU_TREE_SHA256
from ti84re.paths import ROOT
SCHEMA = "ti84p-re.compact-probe-emulator-evidence.v1"
BACKEND_TIMEOUT_SECONDS = 30
FIELD_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")
SOURCE_PATHS = (
    "tools/probes/hardware/display.inc",
    "tools/probes/hardware/common.inc",
    "tools/ti84re/hardware/compact_probe_code.py",
    "tools/ti84re/hardware/probe.py",
    "tools/ti84re/hardware/build_probes.py",
    "tools/ti84re/emulators/probe_build.py",
    "tools/ti84re/emulators/tilem/build_compact_probe.py",
    "tools/ti84re/emulators/wabbitemu/build_compact_probe.py",
    "tools/probes/tilem/tilem_compact_probe.c",
    "tools/probes/tilem/tilem_probe_support.c",
    "tools/probes/tilem/tilem_probe_support.h",
    "tools/ti84re/emulators/tilem/core.py",
    "tools/probes/wabbitemu/wabbitemu_compact_probe.cpp",
    "tools/probes/wabbitemu/wabbitemu_headless.cpp",
    "tools/ti84re/emulators/wabbitemu/headless.py",
    "tools/ti84re/hardware/run_compact_probe_e2e.py",
)


def require(condition: bool, message: str) -> None:
    """Raise one stable validation error for a failed evidence invariant."""

    if not condition:
        raise ValueError(message)


def parse_native_output(output: str) -> dict[str, str]:
    """Parse one compact-runner status line."""

    lines = [line for line in output.splitlines() if "compact_code=" in line]
    require(len(lines) == 1, "compact runner must emit one status line")
    fields = {
        match["key"]: match["value"]
        for match in FIELD_PATTERN.finditer(lines[0])
    }
    required = {
        "mode",
        "probe_id",
        "payload_size",
        "probe_size",
        "create_intercepts",
        "key_pages",
        "marker_visits",
        "returned",
        "final_sp",
        "appvar_matches",
        "completed",
        "display_code",
        "rendered",
        "lcd_fnv1a64",
        "compact_code",
        "frame_hex",
    }
    missing = sorted(required - fields.keys())
    require(not missing, "compact runner omitted fields: " + ", ".join(missing))
    return fields


def validate_native_fields(
    fields: Mapping[str, str], *, probe_name: str, machine_code: bytes, backend: str
) -> dict[str, Any]:
    """Require exact reversible agreement between assembly and host codecs."""

    probe = PROBES[probe_name]
    expected_mode = f"{backend}-compact"
    require(fields["mode"] == expected_mode, f"wrong {backend} runner mode")
    require(fields["completed"] == "1", f"{backend} compact run did not complete")
    require(fields["marker_visits"] == "1", f"{backend} marker count differs")
    require(fields["returned"] == "1", f"{backend} probe did not return")
    require(fields["final_sp"] == "0xFF02", f"{backend} final stack differs")
    require(fields["appvar_matches"] == "1", f"{backend} AppVar did not match")
    require(int(fields["probe_id"], 0) == probe.probe_id, f"wrong {backend} probe ID")
    require(
        int(fields["payload_size"], 0) == probe.payload_size,
        f"wrong {backend} payload size",
    )
    require(
        int(fields["probe_size"], 0) == len(machine_code),
        f"wrong {backend} machine-code size",
    )
    frame_bytes = bytes.fromhex(fields["frame_hex"])
    frame = decode_probe_frame(frame_bytes)
    expected_code = encode_compact_probe_code(frame_bytes)
    require(
        fields["compact_code"] == expected_code,
        f"{backend} assembly compact code differs from the host encoder",
    )
    require(
        decode_compact_probe_code(fields["compact_code"]) == frame_bytes,
        f"{backend} compact code does not recover the frame",
    )
    require(
        int(fields["display_code"], 0) == probe_verification_code(frame),
        f"{backend} decimal CRC differs",
    )
    expected_rendered = 1 if backend == "wabbitemu" else 0
    require(
        int(fields["rendered"], 0) == expected_rendered,
        f"{backend} render scope differs",
    )
    compact_code = fields["compact_code"]
    expected_key_pages = 1 + math.ceil(len(compact_code) / 144)
    require(
        int(fields["key_pages"], 0) == expected_key_pages,
        f"{backend} compact pagination differs",
    )
    if backend == "wabbitemu":
        require(fields.get("all_pages_nonblank") == "1", "Wabbitemu page is blank")
        page_hashes = fields.get("page_lcd_fnv1a64", "").split(",")
        nonzero_counts = fields.get("page_nonzero_bytes", "").split(",")
        require(
            len(page_hashes) == expected_key_pages
            and all(re.fullmatch(r"[0-9a-f]{16}", value) for value in page_hashes),
            "Wabbitemu page hashes differ",
        )
        require(
            len(nonzero_counts) == expected_key_pages
            and all(int(value, 0) > 0 for value in nonzero_counts),
            "Wabbitemu page visibility differs",
        )
    return {
        "status": "completed",
        "frame_hex": fields["frame_hex"],
        "display_code_decimal": int(fields["display_code"], 0),
        "compact_code": compact_code,
        "compact_code_length": len(compact_code),
        "key_pages": int(fields["key_pages"], 0),
        "rendered_small_font": bool(expected_rendered),
        "lcd_fnv1a64": fields["lcd_fnv1a64"],
        "native_fields": dict(fields),
    }


def source_hashes(probe_name: str, root: Path = ROOT) -> dict[str, str]:
    """Hash every local source that defines the end-to-end result."""

    paths = (*SOURCE_PATHS, f"tools/probes/hardware/{PROBES[probe_name].source_name}")
    return {path: file_sha256(root / path) for path in paths}


def run_backend(
    *,
    backend: str,
    binary: Path,
    rom: Path,
    machine_path: Path,
    probe_name: str,
    machine_code: bytes,
) -> dict[str, Any]:
    """Execute one native backend and validate its compact text."""

    probe = PROBES[probe_name]
    command = [
        str(binary),
        "--compact-probe",
        str(rom),
        str(machine_path),
        str(probe.probe_id),
        str(probe.payload_size),
        "100000000" if backend == "tilem" else "10000000",
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=BACKEND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError(
            f"{backend} compact runner exceeded {BACKEND_TIMEOUT_SECONDS} seconds"
        ) from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"{backend} compact runner failed: {detail}")
    fields = parse_native_output(completed.stdout)
    recorded_command = [
        str(binary),
        "--compact-probe",
        f"rom-sha256:{file_sha256(rom)}",
        f"probe-sha256:{hashlib.sha256(machine_code).hexdigest()}",
        str(probe.probe_id),
        str(probe.payload_size),
        "100000000" if backend == "tilem" else "10000000",
    ]
    return {
        "backend": backend,
        "binary_sha256": file_sha256(binary),
        "command": recorded_command,
        **validate_native_fields(
            fields, probe_name=probe_name, machine_code=machine_code, backend=backend
        ),
    }


def validate_evidence(
    evidence: Mapping[str, Any], *, root: Path = ROOT, spasm: str = "spasm"
) -> None:
    """Validate a tracked compact-code emulator record against current sources."""

    require(evidence.get("schema") == SCHEMA, "wrong compact evidence schema")
    probe_name = evidence.get("probe")
    require(isinstance(probe_name, str) and probe_name in PROBES, "unknown probe")
    require(
        evidence.get("sources") == source_hashes(probe_name, root),
        "compact sources are stale",
    )
    probe = PROBES[probe_name]
    require(evidence.get("probe_id") == probe.probe_id, "tracked probe ID differs")
    require(evidence.get("payload_size") == probe.payload_size, "tracked payload differs")
    require(
        evidence.get("rom_sha256") == TI84_PLUS_OS_255MP_SHA256,
        "tracked ROM hash differs",
    )
    require(
        evidence.get("emulator_sources")
        == {
            "tilem": {"commit": TILEM_COMMIT, "git_tree": TILEM_TREE},
            "wabbitemu": {
                "commit": WABBITEMU_COMMIT,
                "source_tree_sha256": WABBITEMU_TREE_SHA256,
            },
        },
        "tracked emulator revisions differ",
    )
    machine_size = evidence.get("machine_code_size")
    machine_code = assemble_machine_code(probe_name, spasm=spasm)
    require(
        machine_size == len(machine_code),
        "tracked machine-code size differs from current assembly",
    )
    machine_hash = evidence.get("machine_code_sha256")
    require(
        machine_hash == hashlib.sha256(machine_code).hexdigest(),
        "tracked machine-code hash differs from current assembly",
    )
    backends = evidence.get("backends")
    require(isinstance(backends, Mapping), "tracked backends are absent")
    for backend, mode in (("tilem", "tilem-compact"), ("wabbitemu", "wabbitemu-compact")):
        row = backends.get(backend)
        require(isinstance(row, Mapping), f"tracked {backend} result is absent")
        require(row.get("backend") == backend, f"tracked {backend} backend differs")
        require(row.get("status") == "completed", f"tracked {backend} status differs")
        fields = row.get("native_fields")
        require(isinstance(fields, Mapping), f"tracked {backend} fields are absent")
        require(fields.get("mode") == mode, f"tracked {backend} mode differs")
        require(fields.get("create_intercepts") == "1", "AppVar intercept count differs")
        require(fields.get("marker_visits") == "1", "compact marker count differs")
        require(fields.get("returned") == "1", "compact probe did not return")
        require(fields.get("final_sp") == "0xFF02", "compact final stack differs")
        require(fields.get("completed") == "1", f"tracked {backend} completion differs")
        require(
            fields.get("appvar_matches") == "1",
            f"tracked {backend} AppVar comparison differs",
        )
        require(
            int(fields.get("probe_id", "-1"), 0) == probe.probe_id,
            f"tracked {backend} native probe ID differs",
        )
        require(
            int(fields.get("payload_size", "-1"), 0) == probe.payload_size,
            f"tracked {backend} native payload size differs",
        )
        require(
            int(fields.get("probe_size", "-1"), 0) == machine_size,
            "machine size differs",
        )
        frame_bytes = bytes.fromhex(str(row.get("frame_hex")))
        frame = decode_probe_frame(frame_bytes)
        require(frame.probe_id == probe.probe_id, "tracked frame probe ID differs")
        require(len(frame.payload) == probe.payload_size, "tracked frame payload differs")
        require(fields.get("frame_hex") == row.get("frame_hex"), "native frame differs")
        require(fields.get("compact_code") == row.get("compact_code"), "native code differs")
        require(
            row.get("compact_code") == encode_compact_probe_code(frame_bytes),
            f"tracked {backend} compact code differs",
        )
        require(
            decode_compact_probe_code(str(row.get("compact_code"))) == frame_bytes,
            f"tracked {backend} code does not recover its frame",
        )
        expected_rendered = backend == "wabbitemu"
        require(
            row.get("rendered_small_font") is expected_rendered,
            f"tracked {backend} rendering scope differs",
        )
        require(
            int(fields.get("rendered", "-1"), 0) == int(expected_rendered),
            f"tracked {backend} native rendering scope differs",
        )
        lcd_hash = row.get("lcd_fnv1a64")
        require(
            isinstance(lcd_hash, str)
            and re.fullmatch(r"[0-9a-f]{16}", lcd_hash) is not None,
            f"tracked {backend} LCD hash is malformed",
        )
        compact_code = str(row.get("compact_code"))
        require(
            row.get("compact_code_length") == len(compact_code),
            f"tracked {backend} compact length differs",
        )
        require(
            row.get("display_code_decimal") == probe_verification_code(frame),
            f"tracked {backend} decimal CRC differs",
        )
        require(
            int(fields.get("display_code", "-1"), 0)
            == row.get("display_code_decimal"),
            f"tracked {backend} native decimal CRC differs",
        )
        expected_key_pages = 1 + math.ceil(len(compact_code) / 144)
        require(
            int(row.get("key_pages", 0)) == expected_key_pages,
            f"tracked {backend} compact pagination differs",
        )
        require(
            int(fields.get("key_pages", "-1"), 0) == expected_key_pages,
            f"tracked {backend} native pagination differs",
        )
        require(
            fields.get("lcd_fnv1a64") == lcd_hash,
            f"tracked {backend} native LCD hash differs",
        )
        binary_hash = row.get("binary_sha256")
        require(
            isinstance(binary_hash, str)
            and re.fullmatch(r"[0-9a-f]{64}", binary_hash) is not None,
            f"tracked {backend} binary hash is malformed",
        )
        command = row.get("command")
        require(
            isinstance(command, list)
            and len(command) == 7
            and isinstance(command[0], str)
            and command[1:]
            == [
                "--compact-probe",
                f"rom-sha256:{TI84_PLUS_OS_255MP_SHA256}",
                f"probe-sha256:{machine_hash}",
                str(probe.probe_id),
                str(probe.payload_size),
                "100000000" if backend == "tilem" else "10000000",
            ],
            f"tracked {backend} normalized command differs",
        )
        if backend == "wabbitemu":
            require(
                lcd_hash != "9fa9e040e0eedf25",
                "tracked Wabbitemu LCD is blank after rendering",
            )
            require(fields.get("all_pages_nonblank") == "1", "Wabbitemu page is blank")
            page_hashes = str(fields.get("page_lcd_fnv1a64", "")).split(",")
            nonzero_counts = str(fields.get("page_nonzero_bytes", "")).split(",")
            require(
                len(page_hashes) == expected_key_pages
                and all(re.fullmatch(r"[0-9a-f]{16}", value) for value in page_hashes),
                "tracked Wabbitemu page hashes differ",
            )
            require(
                len(nonzero_counts) == expected_key_pages
                and all(int(value, 0) > 0 for value in nonzero_counts),
                "tracked Wabbitemu page visibility differs",
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--tilem-binary", type=Path)
    parser.add_argument("--expected-tilem-sha256")
    parser.add_argument("--wabbitemu-binary", type=Path)
    parser.add_argument("--expected-wabbitemu-sha256")
    parser.add_argument("--probe", choices=PROBES, default="asic-snapshot")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    parser.add_argument("--spasm", default="spasm")
    args = parser.parse_args()
    try:
        if args.check:
            require(
                not any(
                    (
                        args.tilem_binary,
                        args.wabbitemu_binary,
                        args.output,
                        args.expected_tilem_sha256,
                        args.expected_wabbitemu_sha256,
                    )
                ),
                "--check cannot be combined with run arguments",
            )
            evidence = json.loads(args.check.read_text(encoding="utf-8"))
            require(isinstance(evidence, dict), "evidence must be a JSON object")
            validate_evidence(evidence, spasm=args.spasm)
            print(f"PASS {args.check}")
            return
        require(
            all(
                (
                    args.tilem_binary,
                    args.expected_tilem_sha256,
                    args.wabbitemu_binary,
                    args.expected_wabbitemu_sha256,
                    args.output,
                )
            ),
            "a run requires both binaries, both expected hashes, and --output",
        )
        rom_sha = require_exact_hash(args.rom, TI84_PLUS_OS_255MP_SHA256, "ROM")
        require_exact_hash(
            args.tilem_binary, args.expected_tilem_sha256, "TilEm compact runner"
        )
        require_exact_hash(
            args.wabbitemu_binary,
            args.expected_wabbitemu_sha256,
            "Wabbitemu compact runner",
        )
        machine_code = assemble_machine_code(args.probe, spasm=args.spasm)
        with tempfile.TemporaryDirectory(prefix="ti84-compact-e2e-") as directory:
            machine_path = Path(directory) / f"{PROBES[args.probe].program}.bin"
            machine_path.write_bytes(machine_code)
            tilem = run_backend(
                backend="tilem",
                binary=args.tilem_binary,
                rom=args.rom,
                machine_path=machine_path,
                probe_name=args.probe,
                machine_code=machine_code,
            )
            wabbitemu = run_backend(
                backend="wabbitemu",
                binary=args.wabbitemu_binary,
                rom=args.rom,
                machine_path=machine_path,
                probe_name=args.probe,
                machine_code=machine_code,
            )
        evidence = {
            "schema": SCHEMA,
            "probe": args.probe,
            "probe_id": PROBES[args.probe].probe_id,
            "payload_size": PROBES[args.probe].payload_size,
            "machine_code_size": len(machine_code),
            "machine_code_sha256": hashlib.sha256(machine_code).hexdigest(),
            "rom_sha256": rom_sha,
            "sources": source_hashes(args.probe),
            "emulator_sources": {
                "tilem": {"commit": TILEM_COMMIT, "git_tree": TILEM_TREE},
                "wabbitemu": {
                    "commit": WABBITEMU_COMMIT,
                    "source_tree_sha256": WABBITEMU_TREE_SHA256,
                },
            },
            "backends": {"tilem": tilem, "wabbitemu": wabbitemu},
        }
        validate_evidence(evidence, spasm=args.spasm)
        if args.output.exists():
            raise ValueError(f"refusing to overwrite {args.output}")
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"WROTE {args.output}")
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
