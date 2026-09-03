"""Typed report and oracle for MAME's TI-84 Plus MD5-port coverage."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ti84re.emulators.mame.runtime import MAME_VERSION, MameRuntimeError, parse_report_fields
from ti84re.hardware.md5 import md5_assist_value

MD5_PORTS = tuple(range(0x18, 0x20))
ZERO_PORT_BLOCK = (0,) * len(MD5_PORTS)
FIRST_STEP = {
    "mode": 0,
    "a": 0x67452301,
    "b": 0xEFCDAB89,
    "c": 0x98BADCFE,
    "d": 0x10325476,
    "x": 0x80636261,
    "t": 0xD76AA478,
    "shift": 7,
}


@dataclass(frozen=True)
class MameMd5Report:
    """MAME identity, unmapped-port reads, and one valid MD5 transaction."""

    machine: str
    version: str
    initial_ports: tuple[int, ...]
    patterned_ports: tuple[int, ...]
    expected_result: int
    observed_result: int
    step_ports: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_port_block(value: str) -> tuple[int, ...]:
    if len(value) != 2 * len(MD5_PORTS):
        raise MameRuntimeError("MAME MD5 port block must contain eight bytes")
    try:
        return tuple(int(value[index : index + 2], 16) for index in range(0, 16, 2))
    except ValueError as error:
        raise MameRuntimeError("invalid hexadecimal MAME MD5 port block") from error


def parse_mame_md5_report(output: str) -> MameMd5Report:
    """Parse identity, initial, patterned-write, and valid-step report lines."""

    prefixes = (
        "MAME_MD5 identity ",
        "MAME_MD5 initial ",
        "MAME_MD5 patterned ",
        "MAME_MD5 step ",
    )
    lines = output.splitlines()
    fields: list[dict[str, str]] = []
    for prefix in prefixes:
        matches = [line for line in lines if line.startswith(prefix)]
        if len(matches) != 1:
            raise MameRuntimeError(
                f"MAME MD5 output requires exactly one {prefix.strip()} line"
            )
        fields.append(parse_report_fields(matches[0]))
    identity, initial, patterned, step = fields
    try:
        return MameMd5Report(
            machine=identity["machine"],
            version=identity["version"],
            initial_ports=_parse_port_block(initial["ports"]),
            patterned_ports=_parse_port_block(patterned["ports"]),
            expected_result=int(step["expected"], 16),
            observed_result=int(step["observed"], 16),
            step_ports=_parse_port_block(step["ports"]),
        )
    except KeyError as error:
        raise MameRuntimeError(
            f"MAME MD5 report omits field {error.args[0]}"
        ) from error
    except MameRuntimeError:
        raise
    except ValueError as error:
        raise MameRuntimeError("invalid numeric MAME MD5 report field") from error


def first_step_expected_result() -> int:
    """Calculate the first padded-`abc` result independently of MAME."""

    return md5_assist_value(**FIRST_STEP)


def expected_mame_md5_report() -> MameMd5Report:
    """Return the exact observations for MAME 0.287's absent MD5 port block."""

    return MameMd5Report(
        machine="ti84pv3",
        version=MAME_VERSION,
        initial_ports=ZERO_PORT_BLOCK,
        patterned_ports=ZERO_PORT_BLOCK,
        expected_result=first_step_expected_result(),
        observed_result=0,
        step_ports=ZERO_PORT_BLOCK,
    )


def validate_mame_md5_report(report: MameMd5Report) -> dict[str, object]:
    """Require the native result implied by MAME 0.287's pinned I/O map."""

    expected = expected_mame_md5_report()
    if report != expected:
        raise MameRuntimeError(
            "MAME MD5 report disagrees with the 0.287 I/O-map model"
        )
    return {
        "source_model": {
            "io_map": "ti83pse_io inherited by ti84p and ti84pv3",
            "mapped_ports": [],
            "tested_ports": list(MD5_PORTS),
            "runtime_unmapped_read": 0,
            "patterned_writes_retained": False,
            "valid_step_supported": False,
        },
        "independent_expected_result": first_step_expected_result(),
        "native": report.to_dict(),
    }
