#!/usr/bin/env python3
"""Build or verify a self-contained physical-probe evidence bundle."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from hardware_probe import (
    PROBE_NAMES,
    ProbeFormatError,
    decode_ti_variable_file,
    probe_appvar_report,
)

SCHEMA = "ti84p-re.physical-probe-evidence.v1"
METADATA_SCHEMA = "ti84p-re.physical-probe-metadata.v1"

MUTATING_PROBE_IDS = frozenset((2, 4, 7, 10, 11, 12, 14, 15, 16, 17))
RECOVERY_REQUIREMENTS: tuple[tuple[str, type], ...] = (
    ("calculator.backup_verified", bool),
    ("calculator.backup_artifact_sha256", str),
    ("run.restore_rehearsal.utc_time", str),
    ("run.restore_rehearsal.result", str),
    ("run.restore_rehearsal.backup_sha256", str),
    ("run.restore_rehearsal.notes", str),
)

BASE_REQUIREMENTS = (
    ("probe", str),
    ("program", str),
    ("result_appvar", str),
    ("calculator.unit_id", str),
    ("calculator.model", str),
    ("calculator.pcb_revision", str),
    ("calculator.asic_marking", str),
    ("calculator.port_0x15", int),
    ("calculator.boot_version", str),
    ("calculator.os_version", str),
    ("run.utc_time", str),
    ("run.power_source", str),
    ("run.launch_context", str),
    ("run.cpu_speed_setting", str),
    ("run.interrupts_enabled_on_entry", bool),
    ("run.preexisting_hooks_or_shells", list),
    ("run.connected_equipment", list),
    ("run.operator_actions", list),
    ("run.visible_reset", bool),
)

PROBE_REQUIREMENTS: dict[int, tuple[tuple[str, type], ...]] = {
    2: RECOVERY_REQUIREMENTS,
    4: (
        *RECOVERY_REQUIREMENTS,
        ("run.recovery_observation", str),
    ),
    5: (("run.usb_state", str),),
    6: (
        ("run.supply_volts", (int, float)),
        ("run.load_amps", (int, float)),
        ("run.temperature_c", (int, float)),
        ("run.supply_sweep_direction", str),
    ),
    7: (
        *RECOVERY_REQUIREMENTS,
        ("run.supply_volts", (int, float)),
        ("run.load_amps", (int, float)),
        ("run.temperature_c", (int, float)),
        ("run.supply_sweep_direction", str),
    ),
    8: (("run.link_connector_state", str),),
    10: RECOVERY_REQUIREMENTS,
    11: RECOVERY_REQUIREMENTS,
    12: RECOVERY_REQUIREMENTS,
    13: (("run.rtc_configuration", str),),
    14: RECOVERY_REQUIREMENTS,
    15: (
        *RECOVERY_REQUIREMENTS,
        ("calculator.lcd_controller_or_revision", str),
        ("run.panel_observation", str),
    ),
    16: RECOVERY_REQUIREMENTS,
    17: (
        *RECOVERY_REQUIREMENTS,
        ("calculator.lcd_controller_or_revision", str),
        ("run.panel_observation", str),
        ("run.recovery_notes", str),
    ),
}


def require(condition: bool, message: str) -> None:
    """Raise a stable validation error when an evidence invariant fails."""

    if not condition:
        raise ValueError(message)


def _json_object(blob: bytes, label: str) -> dict[str, Any]:
    """Decode one UTF-8 JSON object."""

    try:
        value = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not a UTF-8 JSON document: {error}") from error
    require(isinstance(value, dict), f"{label} must contain a JSON object")
    return value


def _field(value: Mapping[str, Any], path: str) -> Any:
    """Return one dotted metadata field or ``None`` when it is absent."""

    current: Any = value
    for component in path.split("."):
        if not isinstance(current, Mapping) or component not in current:
            return None
        current = current[component]
    return current


def _nonempty(value: Any, expected: type | tuple[type, ...]) -> bool:
    """Return whether *value* has the required type and meaningful content."""

    if isinstance(value, bool) and expected in ((int, float), int, float):
        return False
    if not isinstance(value, expected):
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() != "unknown"
    return True


def _encoded_file(name: str, blob: bytes) -> dict[str, Any]:
    """Encode one complete input file with a strong identity."""

    return {
        "name": name,
        "size": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "encoding": "base64",
        "content": base64.b64encode(blob).decode("ascii"),
    }


def _decode_file(record: Mapping[str, Any], label: str) -> bytes:
    """Decode and verify one embedded file record."""

    require(record.get("encoding") == "base64", f"{label} encoding is not base64")
    content = record.get("content")
    require(isinstance(content, str), f"{label} has no base64 content")
    try:
        blob = base64.b64decode(content, validate=True)
    except ValueError as error:
        raise ValueError(f"{label} has invalid base64 content") from error
    require(record.get("size") == len(blob), f"{label} size does not match")
    require(
        record.get("sha256") == hashlib.sha256(blob).hexdigest(),
        f"{label} SHA-256 does not match",
    )
    return blob


def _is_sha256(value: Any) -> bool:
    """Return whether *value* is one canonical SHA-256 hex digest."""

    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _acceptance(report: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one decoded run without discarding an unsuccessful observation."""

    probe_id = report["probe_id"]
    measurements = report["measurements"]
    require(isinstance(measurements, Mapping), "decoded measurements are not an object")
    predicates: list[dict[str, Any]] = []

    def check(name: str, observed: Any, expected: Any = True) -> None:
        predicates.append(
            {
                "name": name,
                "passed": observed == expected,
                "observed": observed,
                "expected": expected,
            }
        )

    def check_all(name: str, values: Any) -> None:
        require(isinstance(values, Mapping), f"decoded {name} is not an object")
        for field, value in values.items():
            check(f"{name}.{field}", value)

    if "outcome_code" in measurements:
        check(
            "outcome_code",
            measurements["outcome_code"],
            1 if probe_id == 17 else 0,
        )
    elif probe_id == 4:
        check("outcome", measurements.get("outcome"), "returned")

    if probe_id == 2:
        check("restore_matches", measurements.get("restore_matches"))
    elif probe_id in (6, 7):
        check("cleanup_matches", measurements.get("cleanup_matches"))
        pre = measurements.get("pre")
        restored = measurements.get("restored")
        require(isinstance(pre, Mapping), "decoded pre-state is not an object")
        require(isinstance(restored, Mapping), "decoded restored state is not an object")
        check("cleanup_status_matches", restored.get("status"), pre.get("status"))
    elif probe_id == 8:
        check("cleanup_idle_matches", measurements.get("cleanup_idle_matches"))
        pre = measurements.get("pre")
        cleanup = measurements.get("cleanup")
        require(isinstance(pre, Mapping), "decoded pre-state is not an object")
        require(isinstance(cleanup, Mapping), "decoded cleanup state is not an object")
        check("cleanup_status_matches", cleanup.get("status"), pre.get("status"))
    elif probe_id == 9:
        for field in (
            "measurements_valid",
            "cleanup_all_columns_high",
            "status_unchanged",
            "interrupt_ports_unchanged",
            "speed_unchanged",
        ):
            check(field, measurements.get(field))
        check("operator_wait_timed_out", measurements.get("operator_wait_timed_out"), False)
    elif probe_id in (10, 11):
        check_all("restored", measurements.get("restored"))
        check("speed_unchanged", measurements.get("speed_unchanged"))
        check("timing_gates_unchanged", measurements.get("timing_gates_unchanged"))
    elif probe_id == 12:
        check_all("restored", measurements.get("restored"))
    elif probe_id == 13:
        for field in (
            "control_unchanged",
            "first_transition_coherent",
            "later_reads_monotonic",
        ):
            check(field, measurements.get(field))
    elif probe_id == 14:
        check("all_marker_pages_restored", measurements.get("all_marker_pages_restored"))
        check("readable_ports_restored", measurements.get("readable_ports_restored"))
    elif probe_id == 15:
        check("restore_ok", measurements.get("restore_ok"))
        check("wait_registers_unchanged", measurements.get("wait_registers_unchanged"))
        if measurements.get("schema") == "visible-cell-v2":
            visible_cell = measurements.get("visible_cell")
            require(isinstance(visible_cell, Mapping), "decoded visible cell is not an object")
            check("visible_cell.matches", visible_cell.get("matches"))
            check("movement_status_restored", measurements.get("movement_status_restored"))
    elif probe_id == 16:
        check("restore_ok", measurements.get("restore_ok"))
        check("i_register_restored", measurements.get("i_register_restored"))
    elif probe_id == 17:
        restoration = measurements.get("restoration")
        direct = measurements.get("direct_hidden_columns")
        increment = measurements.get("increment_from_column_14")
        require(isinstance(restoration, Mapping), "decoded restoration is not an object")
        require(isinstance(direct, Mapping), "decoded direct result is not an object")
        require(isinstance(increment, Mapping), "decoded increment result is not an object")
        check("last_completed_stage", measurements.get("last_completed_stage"), 5)
        check("restoration.matches", restoration.get("matches"))
        check("direct_hidden_columns.change_count_matches", direct.get("change_count_matches"))
        check("increment_from_column_14.change_count_matches", increment.get("change_count_matches"))

    failed = [predicate["name"] for predicate in predicates if not predicate["passed"]]
    return {
        "accepted": not failed,
        "classification": "accepted" if not failed else "failed",
        "predicates": predicates,
        "failed_predicates": failed,
    }


def _manifest_row(
    manifest: Mapping[str, Any], report: Mapping[str, Any]
) -> dict[str, Any]:
    """Select the exact artifact row that produced the result AppVar."""

    require(manifest.get("format") == 1, "build manifest format is not 1")
    rows = manifest.get("probes")
    if isinstance(rows, list):
        matches = [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("probe_id") == report["probe_id"]
            and row.get("result_appvar") == report["variable_name"]
        ]
    elif (
        manifest.get("laboratory_only") is True
        and manifest.get("probe_id") == report["probe_id"]
        and manifest.get("result_appvar") == report["variable_name"]
    ):
        matches = [{"probe": "lcd-hidden-lab", **manifest}]
    else:
        matches = []
    require(len(matches) == 1, "manifest must contain one matching probe artifact")
    row = matches[0]
    require(
        row.get("payload_size") == report["payload_size"],
        "manifest payload size does not match the AppVar",
    )
    for field in (
        "probe",
        "program",
        "source",
        "physical_use_class",
        "machine_code_size",
        "machine_code_sha256",
        "program_file_size",
        "program_file_sha256",
    ):
        require(field in row, f"manifest probe row is missing {field}")
    return dict(row)


def _validate_metadata(
    metadata: Mapping[str, Any],
    report: Mapping[str, Any],
    artifact: Mapping[str, Any],
    attachments: Sequence[tuple[str, str, bytes]],
) -> dict[str, Any]:
    """Validate physical context and report the state-coverage contract."""

    require(
        artifact.get("physical_use_class") != "blocked",
        "this artifact is blocked from physical evidence collection by its safety review",
    )

    require(metadata.get("schema") == METADATA_SCHEMA, "wrong metadata schema")
    requirements = (*BASE_REQUIREMENTS, *PROBE_REQUIREMENTS.get(report["probe_id"], ()))
    missing = [
        path
        for path, expected in requirements
        if not _nonempty(_field(metadata, path), expected)
    ]
    if not _field(metadata, "run.operator_actions"):
        missing.append("run.operator_actions(nonempty)")
    if report["probe_id"] in (5, 8) and not _field(
        metadata, "run.connected_equipment"
    ):
        missing.append("run.connected_equipment(nonempty; use 'none' if disconnected)")

    require(metadata.get("probe") == artifact["probe"], "metadata probe does not match")
    require(metadata.get("program") == artifact["program"], "metadata program does not match")
    require(
        metadata.get("result_appvar") == report["variable_name"],
        "metadata AppVar does not match",
    )
    require(
        _field(metadata, "calculator.port_0x15") == report["asic_id"],
        "metadata port 0x15 does not match the AppVar",
    )
    for path in ("run.supply_volts", "run.load_amps", "run.temperature_c"):
        value = _field(metadata, path)
        if value is not None:
            require(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value),
                f"{path} must be a finite number when recorded",
            )
    supply_volts = _field(metadata, "run.supply_volts")
    load_amps = _field(metadata, "run.load_amps")
    if supply_volts is not None:
        require(supply_volts > 0, "run.supply_volts must be positive")
    if load_amps is not None:
        require(load_amps >= 0, "run.load_amps must not be negative")
    backup = _field(metadata, "calculator.backup_verified")
    if report["probe_id"] in MUTATING_PROBE_IDS:
        require(backup is True, "this probe requires a verified calculator backup")
        backup_sha256 = _field(metadata, "calculator.backup_artifact_sha256")
        rehearsal_sha256 = _field(metadata, "run.restore_rehearsal.backup_sha256")
        require(
            _is_sha256(backup_sha256),
            "calculator.backup_artifact_sha256 must be canonical SHA-256 hex",
        )
        require(
            rehearsal_sha256 == backup_sha256,
            "restore rehearsal does not identify the embedded backup",
        )
        require(
            _field(metadata, "run.restore_rehearsal.result") == "passed",
            "restore rehearsal result must be passed",
        )
        backup_attachments = [
            blob for role, _name, blob in attachments if role == "calculator_backup"
        ]
        require(
            len(backup_attachments) == 1,
            "this probe requires one calculator_backup attachment",
        )
        require(backup_attachments[0], "calculator_backup attachment must not be empty")
        require(
            hashlib.sha256(backup_attachments[0]).hexdigest() == backup_sha256,
            "calculator_backup attachment SHA-256 does not match metadata",
        )
        recovery = artifact.get("recovery")
        if report["probe_id"] == 17:
            require(
                isinstance(recovery, Mapping),
                "laboratory manifest is missing recovery metadata",
            )
            recovery_backup = recovery.get("backup")
            require(
                isinstance(recovery_backup, Mapping)
                and recovery_backup.get("sha256") == backup_sha256,
                "laboratory manifest recovery backup does not match metadata",
            )

    run_datetime = None
    rehearsal_datetime = None
    utc_time = _field(metadata, "run.utc_time")
    if isinstance(utc_time, str):
        try:
            run_datetime = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
        except ValueError:
            missing.append("run.utc_time(valid ISO 8601 timestamp)")
        else:
            if run_datetime.tzinfo is None:
                missing.append("run.utc_time(timezone required)")
    rehearsal_time = _field(metadata, "run.restore_rehearsal.utc_time")
    if rehearsal_time is not None:
        try:
            rehearsal_datetime = datetime.fromisoformat(
                rehearsal_time.replace("Z", "+00:00")
            )
        except (AttributeError, ValueError):
            missing.append("run.restore_rehearsal.utc_time(valid ISO 8601 timestamp)")
        else:
            if rehearsal_datetime.tzinfo is None:
                missing.append("run.restore_rehearsal.utc_time(timezone required)")
    if (
        run_datetime is not None
        and run_datetime.tzinfo is not None
        and rehearsal_datetime is not None
        and rehearsal_datetime.tzinfo is not None
    ):
        require(
            rehearsal_datetime < run_datetime,
            "restore rehearsal must predate the physical probe run",
        )

    reset = _field(metadata, "run.visible_reset") is True
    display_code = _field(metadata, "run.displayed_verification_code")
    if reset:
        if display_code is not None:
            require(
                display_code == report["verification_code_decimal"],
                "displayed verification code does not match the AppVar",
            )
    else:
        if display_code is None:
            missing.append("run.displayed_verification_code")
        else:
            require(
                display_code == report["verification_code_decimal"],
                "displayed verification code does not match the AppVar",
            )

    missing = sorted(set(missing))
    require(not missing, "metadata is incomplete: " + ", ".join(missing))
    acceptance = _acceptance(report)
    return {
        "complete": acceptance["accepted"],
        "run_acceptance": acceptance,
        "calculator_observable_state": {
            "encoding": "complete HWP1 frame",
            "raw_frame_retained": True,
            "decoded_measurements_retained": True,
            "frame_sha256": report["frame_sha256"],
        },
        "external_state": {
            "metadata_schema": METADATA_SCHEMA,
            "required_fields": [path for path, _expected in requirements],
            "required_attachment_roles": (
                ["calculator_backup"]
                if report["probe_id"] in MUTATING_PROBE_IDS
                else []
            ),
            "missing_fields": [],
        },
        "scope": (
            "The bundle covers every calculator-observable byte defined by the "
            "probe and the required run context. Electrical waveforms and other "
            "instrument-only quantities require embedded attachments."
        ),
    }


def build_evidence(
    appvar_blob: bytes,
    program_blob: bytes,
    manifest_blob: bytes,
    metadata_blob: bytes,
    *,
    appvar_name: str,
    program_name: str,
    manifest_name: str,
    metadata_name: str,
    attachments: Sequence[tuple[str, str, bytes]] = (),
) -> dict[str, Any]:
    """Return a deterministic, self-contained physical evidence bundle."""

    report = probe_appvar_report(appvar_blob)
    manifest = _json_object(manifest_blob, "build manifest")
    metadata = _json_object(metadata_blob, "metadata")
    artifact = _manifest_row(manifest, report)
    program_variable = decode_ti_variable_file(program_blob)
    require(program_variable.variable_type == 0x05, "program file is not a program")
    require(
        program_variable.name == artifact["program"],
        "program file name does not match the manifest",
    )
    require(
        artifact["program_file_size"] == len(program_blob),
        "program file size does not match the manifest",
    )
    require(
        artifact["program_file_sha256"] == hashlib.sha256(program_blob).hexdigest(),
        "program file SHA-256 does not match the manifest",
    )
    roles = [role for role, _name, _blob in attachments]
    require(len(roles) == len(set(roles)), "attachment roles must be unique")
    coverage = _validate_metadata(metadata, report, artifact, attachments)
    return {
        "schema": SCHEMA,
        "probe": {
            "name": artifact["probe"],
            "generic_name": PROBE_NAMES.get(report["probe_id"], "unknown"),
            "probe_id": report["probe_id"],
            "program": artifact["program"],
            "result_appvar": report["variable_name"],
        },
        "input_files": {
            "appvar": _encoded_file(appvar_name, appvar_blob),
            "program": _encoded_file(program_name, program_blob),
            "build_manifest": _encoded_file(manifest_name, manifest_blob),
            "metadata": _encoded_file(metadata_name, metadata_blob),
            "attachments": [
                {"role": role, **_encoded_file(name, blob)}
                for role, name, blob in attachments
            ],
        },
        "artifact": artifact,
        "metadata": metadata,
        "probe_report": report,
        "state_coverage": coverage,
    }


def validate_evidence(evidence: Mapping[str, Any]) -> None:
    """Recompute every embedded identity and semantic check."""

    require(evidence.get("schema") == SCHEMA, "wrong evidence schema")
    files = evidence.get("input_files")
    require(isinstance(files, Mapping), "evidence has no input files")
    appvar_record = files.get("appvar")
    program_record = files.get("program")
    manifest_record = files.get("build_manifest")
    metadata_record = files.get("metadata")
    require(isinstance(appvar_record, Mapping), "evidence has no AppVar")
    require(isinstance(program_record, Mapping), "evidence has no program")
    require(isinstance(manifest_record, Mapping), "evidence has no build manifest")
    require(isinstance(metadata_record, Mapping), "evidence has no metadata")
    attachment_records = files.get("attachments")
    require(isinstance(attachment_records, list), "attachments must be a list")
    decoded_attachments = []
    for index, record in enumerate(attachment_records):
        require(isinstance(record, Mapping), f"attachment {index} is not an object")
        role = record.get("role")
        name = record.get("name")
        require(isinstance(role, str) and role.strip(), f"attachment {index} has no role")
        require(isinstance(name, str) and name, f"attachment {index} has no name")
        decoded_attachments.append(
            (role, name, _decode_file(record, f"attachment {role}"))
        )
    expected = build_evidence(
        _decode_file(appvar_record, "AppVar"),
        _decode_file(program_record, "program"),
        _decode_file(manifest_record, "build manifest"),
        _decode_file(metadata_record, "metadata"),
        appvar_name=str(appvar_record.get("name")),
        program_name=str(program_record.get("name")),
        manifest_name=str(manifest_record.get("name")),
        metadata_name=str(metadata_record.get("name")),
        attachments=decoded_attachments,
    )
    claimed_coverage = evidence.get("state_coverage")
    require(isinstance(claimed_coverage, Mapping), "evidence has no state coverage")
    if claimed_coverage.get("complete") is True:
        require(
            expected["state_coverage"]["run_acceptance"]["accepted"] is True,
            "evidence claims complete state coverage for a failed probe run",
        )
    require(evidence == expected, "evidence content does not match embedded inputs")


def _attachment(argument: str) -> tuple[str, Path]:
    """Parse one ``ROLE=PATH`` command-line attachment."""

    if "=" not in argument:
        raise argparse.ArgumentTypeError("attachment must use ROLE=PATH")
    role, raw_path = argument.split("=", 1)
    if not role.strip() or not raw_path:
        raise argparse.ArgumentTypeError("attachment must use nonempty ROLE=PATH")
    return role.strip(), Path(raw_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appvar", type=Path)
    parser.add_argument("--program", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--attachment", action="append", default=[], type=_attachment)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    try:
        if args.check is not None:
            require(
                not any(
                    (
                        args.appvar,
                        args.program,
                        args.manifest,
                        args.metadata,
                        args.output,
                        args.attachment,
                    )
                ),
                "--check cannot be combined with build arguments",
            )
            evidence = _json_object(args.check.read_bytes(), "evidence")
            validate_evidence(evidence)
            print(f"PASS {args.check}")
            return
        require(
            all((args.appvar, args.program, args.manifest, args.metadata, args.output)),
            "building requires --appvar, --program, --manifest, --metadata, and --output",
        )
        attachment_blobs = [
            (role, path.name, path.read_bytes()) for role, path in args.attachment
        ]
        evidence = build_evidence(
            args.appvar.read_bytes(),
            args.program.read_bytes(),
            args.manifest.read_bytes(),
            args.metadata.read_bytes(),
            appvar_name=args.appvar.name,
            program_name=args.program.name,
            manifest_name=args.manifest.name,
            metadata_name=args.metadata.name,
            attachments=attachment_blobs,
        )
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"WROTE {args.output}")
    except (OSError, ProbeFormatError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
