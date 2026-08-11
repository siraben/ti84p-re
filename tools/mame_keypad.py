"""Typed report and oracle for MAME's TI-84 Plus keypad matrix."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from keypad_hardware import read_keypad_matrix
from mame_runtime import MAME_VERSION, MameRuntimeError, parse_report_fields


@dataclass(frozen=True)
class MameKeypadCaseSpec:
    """One matrix mask and set of injected ``(group, column)`` positions."""

    name: str
    group_mask: int
    pressed_keys: tuple[tuple[int, int], ...]


MATRIX_CASES = (
    MameKeypadCaseSpec("release_ff", 0xFF, ((0, 0),)),
    MameKeypadCaseSpec("bit7_only", 0x7F, ((0, 0),)),
    MameKeypadCaseSpec("single", 0xFE, ((0, 0),)),
    MameKeypadCaseSpec("unselected", 0xFE, ((1, 0),)),
    MameKeypadCaseSpec("same_column", 0xFC, ((0, 0), (1, 0))),
    MameKeypadCaseSpec("rectangle", 0xFE, ((0, 0), (1, 0), (1, 1))),
    MameKeypadCaseSpec("column_seven", 0xF7, ((3, 7),)),
    MameKeypadCaseSpec("all_selected", 0x00, ((0, 0), (1, 0), (2, 1))),
)


@dataclass(frozen=True)
class MameKeypadCase:
    """One native port-``0x01`` matrix observation."""

    name: str
    group_mask: int
    pressed_keys: tuple[tuple[int, int], ...]
    read: int


@dataclass(frozen=True)
class MameKeypadReport:
    """Identity and complete ordered keypad case matrix."""

    machine: str
    version: str
    cases: tuple[MameKeypadCase, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_pressed_keys(value: str) -> tuple[tuple[int, int], ...]:
    if value == "none":
        return ()
    keys: list[tuple[int, int]] = []
    try:
        for item in value.split(","):
            parts = item.split(":")
            if len(parts) != 2:
                raise MameRuntimeError("invalid MAME keypad position")
            keys.append((int(parts[0], 10), int(parts[1], 10)))
    except ValueError as error:
        raise MameRuntimeError("invalid MAME keypad position") from error
    return tuple(keys)


def parse_mame_keypad_report(output: str) -> MameKeypadReport:
    """Parse the identity and every native keypad matrix observation."""

    identity_lines = [
        line for line in output.splitlines() if line.startswith("MAME_KEYPAD identity ")
    ]
    case_lines = [
        line for line in output.splitlines() if line.startswith("MAME_KEYPAD case ")
    ]
    if len(identity_lines) != 1:
        raise MameRuntimeError("MAME keypad output omits identity report")
    if len(case_lines) != len(MATRIX_CASES):
        raise MameRuntimeError("MAME keypad output has incomplete case matrix")

    identity = parse_report_fields(identity_lines[0])
    fields = [parse_report_fields(line) for line in case_lines]
    try:
        cases = tuple(
            MameKeypadCase(
                name=values["name"],
                group_mask=int(values["mask"], 16),
                pressed_keys=_parse_pressed_keys(values["pressed"]),
                read=int(values["read"], 16),
            )
            for values in fields
        )
        report = MameKeypadReport(
            machine=identity["machine"],
            version=identity["version"],
            cases=cases,
        )
    except KeyError as error:
        raise MameRuntimeError(
            f"MAME keypad report omits field {error.args[0]}"
        ) from error
    except MameRuntimeError:
        raise
    except ValueError as error:
        raise MameRuntimeError("invalid numeric MAME keypad report field") from error

    selectors = tuple(
        (case.name, case.group_mask, case.pressed_keys) for case in report.cases
    )
    expected_selectors = tuple(
        (case.name, case.group_mask, case.pressed_keys) for case in MATRIX_CASES
    )
    if selectors != expected_selectors:
        raise MameRuntimeError("MAME keypad output has unexpected case selectors")
    return report


def expected_mame_keypad_report() -> MameKeypadReport:
    """Return the complete report derived from the reusable MAME model."""

    return MameKeypadReport(
        machine="ti84pv3",
        version=MAME_VERSION,
        cases=tuple(
            MameKeypadCase(
                name=case.name,
                group_mask=case.group_mask,
                pressed_keys=case.pressed_keys,
                read=read_keypad_matrix(
                    "MAME", case.group_mask, case.pressed_keys
                ).active_low_value,
            )
            for case in MATRIX_CASES
        ),
    )


def validate_mame_keypad_report(report: MameKeypadReport) -> dict[str, object]:
    """Require the native values implied by MAME 0.287's pinned source."""

    expected = expected_mame_keypad_report()
    if report != expected:
        raise MameRuntimeError(
            "MAME keypad report disagrees with the 0.287 source model"
        )
    return {
        "source_model": {
            "handler": "ti8x_keypad_r/ti8x_keypad_w",
            "selected_groups": 7,
            "returned_columns": 8,
            "group_write": "active-low; bit 7 is discarded",
            "matrix_algorithm": "XOR each selected pressed position",
            "input_ports": [f":BIT{column}" for column in range(8)],
            "electrical_settling": False,
            "ghosting_model": False,
        },
        "native": report.to_dict(),
    }
