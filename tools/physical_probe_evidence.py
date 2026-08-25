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
    4: (
        ("calculator.backup_verified", bool),
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
        ("run.supply_volts", (int, float)),
        ("run.load_amps", (int, float)),
        ("run.temperature_c", (int, float)),
        ("run.supply_sweep_direction", str),
    ),
    8: (("run.link_connector_state", str),),
    13: (("run.rtc_configuration", str),),
    14: (("calculator.backup_verified", bool),),
    15: (
        ("calculator.backup_verified", bool),
        ("calculator.lcd_controller_or_revision", str),
        ("run.panel_observation", str),
    ),
    17: (
        ("calculator.backup_verified", bool),
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
) -> dict[str, Any]:
    """Validate physical context and report the state-coverage contract."""

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
    if report["probe_id"] in (4, 14, 15, 17):
        require(backup is True, "this probe requires a verified calculator backup")

    utc_time = _field(metadata, "run.utc_time")
    if isinstance(utc_time, str):
        try:
            parsed = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
        except ValueError:
            missing.append("run.utc_time(valid ISO 8601 timestamp)")
        else:
            if parsed.tzinfo is None:
                missing.append("run.utc_time(timezone required)")

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
    return {
        "complete": True,
        "calculator_observable_state": {
            "encoding": "complete HWP1 frame",
            "raw_frame_retained": True,
            "decoded_measurements_retained": True,
            "frame_sha256": report["frame_sha256"],
        },
        "external_state": {
            "metadata_schema": METADATA_SCHEMA,
            "required_fields": [path for path, _expected in requirements],
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
    coverage = _validate_metadata(metadata, report, artifact)
    roles = [role for role, _name, _blob in attachments]
    require(len(roles) == len(set(roles)), "attachment roles must be unique")
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
