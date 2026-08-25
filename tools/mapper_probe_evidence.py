"""Normalize guarded mapper-probe emulator runs into tracked evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from file_hashes import file_sha256
from hardware_probe import decode_probe_frame, probe_verification_code
from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from tilem_core import TILEM_COMMIT, TILEM_TREE
from wabbitemu_headless import WABBITEMU_COMMIT, WABBITEMU_TREE_SHA256

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
SCHEMA = "ti84p-re.mapper-overlay-emulator-evidence.v1"
MAME_VERSION = "0.287"
PROBE_NAME = "mapper-overlays"
PROGRAM_NAME = "HWPMAP"
APPVAR_NAME = "HWPMAP01"
PROBE_ID = 14
PAYLOAD_SIZE = 47

SOURCE_PATHS = (
    "tools/hardware-probes/mapper-overlays.asm",
    "tools/hardware-probes/common.inc",
    "tools/hardware-probes/display.inc",
    "tools/build_tilem_exact_probe.py",
    "tools/build_wabbitemu_exact_probe.py",
    "tools/tilem_probe_support.c",
    "tools/tilem_exact_probe.c",
    "tools/wabbitemu_exact_probe.cpp",
    "tools/run_exact_hardware_probe.py",
    "tools/run_mame_mapper_probe.py",
    "tools/mame_mapper_probe.lua",
)


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def require(condition: bool, message: str) -> None:
    """Raise a stable validation error when an evidence invariant fails."""

    if not condition:
        raise ValueError(message)


def mapper_artifact(build_manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    """Select and validate the mapper row from a probe build manifest."""

    probes = build_manifest.get("probes")
    require(isinstance(probes, list), "build manifest has no probe list")
    rows = [row for row in probes if row.get("probe") == PROBE_NAME]
    require(len(rows) == 1, "build manifest must contain one mapper probe")
    row = rows[0]
    require(row.get("probe_id") == PROBE_ID, "mapper probe ID changed")
    require(row.get("payload_size") == PAYLOAD_SIZE, "mapper payload size changed")
    require(row.get("program") == PROGRAM_NAME, "mapper program name changed")
    require(row.get("result_appvar") == APPVAR_NAME, "mapper AppVar name changed")
    return row


def normalize_exact_run(
    run: Mapping[str, Any],
    *,
    backend: str,
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one exact-byte run and retain its portable evidence fields."""

    expected_emulator = "TilEm" if backend == "tilem" else "Wabbitemu"
    expected_commit = TILEM_COMMIT if backend == "tilem" else WABBITEMU_COMMIT
    require(run.get("emulator") == expected_emulator, f"wrong {backend} emulator")
    require(run.get("backend") == backend, f"wrong {backend} backend")
    require(run.get("commit") == expected_commit, f"wrong {backend} revision")
    require(run.get("probe") == PROBE_NAME, f"wrong {backend} probe")
    require(run.get("program") == PROGRAM_NAME, f"wrong {backend} program")
    require(run.get("result_appvar") == APPVAR_NAME, f"wrong {backend} AppVar")
    require(
        run.get("machine_code_size") == artifact.get("machine_code_size"),
        f"{backend} machine-code size does not match the build",
    )
    require(
        run.get("machine_code_sha256") == artifact.get("machine_code_sha256"),
        f"{backend} machine-code hash does not match the build",
    )
    require(
        run.get("source_rom_sha256") == TI84_PLUS_OS_255MP_SHA256,
        f"{backend} ROM hash is not OS 2.55MP",
    )

    decoded = run.get("decoded_frame")
    require(isinstance(decoded, dict), f"{backend} run has no decoded frame")
    require(decoded.get("probe_id") == PROBE_ID, f"{backend} frame has wrong probe ID")
    measurements = decoded.get("measurements")
    require(isinstance(measurements, dict), f"{backend} frame has no measurements")
    require(measurements.get("outcome") == "completed", f"{backend} probe did not complete")
    require(measurements.get("outcome_code") == 0, f"{backend} outcome is not zero")
    require(measurements.get("restore_flags") == "0x0F", f"{backend} restore flags failed")
    require(
        measurements.get("all_marker_pages_restored") is True,
        f"{backend} marker restoration failed",
    )
    require(
        measurements.get("readable_ports_restored") is True,
        f"{backend} port restoration failed",
    )
    native = run.get("native_fields")
    require(isinstance(native, dict), f"{backend} run has no native fields")
    require(native.get("completed") == "1", f"{backend} native runner did not complete")
    require(native.get("appvar_matches") == "1", f"{backend} AppVar did not match")
    require(
        native.get("frame_hex") == native.get("appvar_frame_hex"),
        f"{backend} resident frame did not match the staging frame",
    )
    require(
        int(native.get("display_code", "-1"))
        == decoded.get("verification_code_decimal"),
        f"{backend} displayed code does not match the decoded frame",
    )

    source_identity = (
        {"commit": TILEM_COMMIT, "git_tree": TILEM_TREE}
        if backend == "tilem"
        else {
            "commit": WABBITEMU_COMMIT,
            "source_tree_sha256": WABBITEMU_TREE_SHA256,
        }
    )
    return {
        "emulator": expected_emulator,
        "status": "completed",
        "execution": "exact-assembled-bytes",
        **source_identity,
        "runner_sha256": run["binary_sha256"],
        "machine_code_size": run["machine_code_size"],
        "machine_code_sha256": run["machine_code_sha256"],
        "verification_code_decimal": decoded["verification_code_decimal"],
        "frame_hex": native["frame_hex"],
        "decoded_frame": decoded,
        "native_counts": {
            key: native[key]
            for key in (
                "run_clocks",
                "boot_steps",
                "probe_steps",
                "create_intercepts",
                "final_pc",
            )
            if key in native
        },
        "launch": run["launch"],
        "host_intercepts": run["host_intercepts"],
        "evidence_scope": run["evidence_scope"],
    }


def normalize_mame(run: Mapping[str, Any]) -> dict[str, Any]:
    """Retain a direct-handler MAME profile without calling it an exact run."""

    require(run.get("emulator") == "MAME", "wrong MAME emulator")
    require(run.get("version") == MAME_VERSION, "wrong MAME version")
    require(run.get("machine") == "ti84pv3", "wrong MAME machine")
    require(
        run.get("source_rom_sha256") == TI84_PLUS_OS_255MP_SHA256,
        "MAME ROM hash is not OS 2.55MP",
    )
    report = run.get("report")
    require(isinstance(report, dict), "MAME run has no report")
    source_model = report.get("source_model")
    require(isinstance(source_model, dict), "MAME report has no source model")
    require(
        source_model.get("unmapped_tested_ports") == [14, 15, 39, 40],
        "MAME did not test all overlay ports",
    )
    require(
        source_model.get("forced_ram_overlays") is False,
        "MAME unexpectedly reports forced RAM overlays",
    )
    return {
        "emulator": "MAME",
        "version": MAME_VERSION,
        "binary_sha256": run["binary_sha256"],
        "machine": "ti84pv3",
        "exact_execution": {
            "status": "unsupported",
            "reason": (
                "No guarded adapter currently injects and executes the exact HWPMAP "
                "machine-code image in MAME. The Lua result below is a direct-handler "
                "profile and must not be treated as an all-zero probe result."
            ),
        },
        "direct_handler_profile": {
            "status": "completed",
            "execution": "guarded-lua-device-handler-profile",
            "lua_script_sha256": run["lua_script_sha256"],
            "report": report,
            "launch": run["launch"],
            "evidence_scope": run["evidence_scope"],
        },
    }


def source_hashes(root: Path = ROOT) -> dict[str, str]:
    """Hash the assembly and runner sources needed to reproduce this evidence."""

    return {path: file_sha256(root / path) for path in SOURCE_PATHS}


def build_evidence(
    build_manifest: Mapping[str, Any],
    tilem_run: Mapping[str, Any],
    wabbitemu_run: Mapping[str, Any],
    mame_run: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Validate raw run manifests and return a deterministic portable record."""

    artifact = mapper_artifact(build_manifest)
    return {
        "schema": SCHEMA,
        "probe": {
            "name": PROBE_NAME,
            "probe_id": PROBE_ID,
            "program": PROGRAM_NAME,
            "result_appvar": APPVAR_NAME,
            "payload_size": PAYLOAD_SIZE,
        },
        "sources": source_hashes(root),
        "artifact": {
            key: artifact[key]
            for key in (
                "machine_code_size",
                "machine_code_sha256",
                "program_file_size",
                "program_file_sha256",
            )
        },
        "source_rom_sha256": TI84_PLUS_OS_255MP_SHA256,
        "emulators": {
            "tilem": normalize_exact_run(tilem_run, backend="tilem", artifact=artifact),
            "wabbitemu": normalize_exact_run(
                wabbitemu_run, backend="wabbitemu", artifact=artifact
            ),
            "mame": normalize_mame(mame_run),
        },
        "physical_status": {
            "status": "not-run",
            "evidence_needed": (
                "Export HWPMAP01 and record the displayed decimal code from a backed-up "
                "physical TI-84 Plus under stable power."
            ),
        },
    }


def validate_tracked_evidence(evidence: Mapping[str, Any], *, root: Path = ROOT) -> None:
    """Check schema, source freshness, restoration, and unsupported labeling."""

    require(evidence.get("schema") == SCHEMA, "wrong mapper evidence schema")
    require(evidence.get("sources") == source_hashes(root), "mapper evidence sources are stale")
    emulators = evidence.get("emulators")
    require(isinstance(emulators, dict), "mapper evidence has no emulator records")
    for backend in ("tilem", "wabbitemu"):
        row = emulators.get(backend)
        require(isinstance(row, dict), f"mapper evidence has no {backend} record")
        require(row.get("execution") == "exact-assembled-bytes", f"{backend} is not exact")
        require(row.get("status") == "completed", f"{backend} did not complete")
        artifact = evidence.get("artifact", {})
        require(
            row.get("machine_code_size") == artifact.get("machine_code_size"),
            f"{backend} machine-code size does not match the artifact",
        )
        require(
            row.get("machine_code_sha256") == artifact.get("machine_code_sha256"),
            f"{backend} machine-code hash does not match the artifact",
        )
        frame = decode_probe_frame(bytes.fromhex(row.get("frame_hex", "")))
        require(frame.probe_id == PROBE_ID, f"{backend} frame has wrong probe ID")
        require(
            probe_verification_code(frame) == row.get("verification_code_decimal"),
            f"{backend} verification code does not match the frame",
        )
        measurements = row.get("decoded_frame", {}).get("measurements", {})
        require(measurements.get("restore_flags") == "0x0F", f"{backend} restore flags failed")
        require(measurements.get("all_marker_pages_restored") is True, f"{backend} markers failed")
        require(measurements.get("readable_ports_restored") is True, f"{backend} ports failed")
    mame = emulators.get("mame")
    require(isinstance(mame, dict), "mapper evidence has no MAME record")
    require(
        mame.get("exact_execution", {}).get("status") == "unsupported",
        "MAME exact execution must remain explicitly unsupported",
    )
    require(
        mame.get("direct_handler_profile", {}).get("status") == "completed",
        "MAME direct-handler profile did not complete",
    )
    require(
        evidence.get("physical_status", {}).get("status") == "not-run",
        "physical status must not be inferred from emulator evidence",
    )


def parse_args() -> argparse.Namespace:
    """Parse evidence generation or freshness-check arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-manifest", type=Path)
    parser.add_argument("--tilem-manifest", type=Path)
    parser.add_argument("--wabbitemu-manifest", type=Path)
    parser.add_argument("--mame-manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    if args.check is not None:
        if any(
            value is not None
            for value in (
                args.build_manifest,
                args.tilem_manifest,
                args.wabbitemu_manifest,
                args.mame_manifest,
                args.output,
            )
        ):
            parser.error("--check cannot be combined with generation arguments")
    elif any(
        value is None
        for value in (
            args.build_manifest,
            args.tilem_manifest,
            args.wabbitemu_manifest,
            args.mame_manifest,
            args.output,
        )
    ):
        parser.error("generation requires all four manifests and --output")
    return args


def main() -> None:
    """Generate portable evidence or validate the tracked record."""

    args = parse_args()
    if args.check is not None:
        validate_tracked_evidence(load_json(args.check))
        print(f"mapper evidence is current: {args.check}")
        return
    evidence = build_evidence(
        load_json(args.build_manifest),
        load_json(args.tilem_manifest),
        load_json(args.wabbitemu_manifest),
        load_json(args.mame_manifest),
    )
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"wrote mapper evidence: {args.output}")


if __name__ == "__main__":
    main()
