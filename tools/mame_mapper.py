"""Typed report and source-derived oracle for MAME's TI-84 Plus mapper."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from mame_runtime import MAME_VERSION, MameRuntimeError, parse_report_fields
from memory_mapper import Ti83PlusMapper, mapper_profile

PROBE_CASES = ("direct", "independent_b", "window_a", "paired_b", "mapping")
ROM_PREFIXES = {
    0x00: (0xDB, 0x02),
    0x01: (0x44, 0x6F),
    0x02: (0x0E, 0x01),
    0x03: (0x3E, 0x02),
    0x3F: (0x3E, 0x07),
}


@dataclass(frozen=True)
class MameMapperBootObservation:
    """One actual-Z80 read and its fixed-page state before and after."""

    case: str
    mode: int
    bank_a: int
    bank_b: int
    address: int
    fixed_before: tuple[int, ...]
    observed: int
    fixed_after: tuple[int, ...]
    pc: int


@dataclass(frozen=True)
class MameMapperReport:
    """Complete reset, selector, mapping, overlay, and fetch observations."""

    machine: str
    version: str
    reset_pc: int
    reset_ports: tuple[int, ...]
    reset_fixed_before: tuple[int, ...]
    reset_a: tuple[int, ...]
    reset_b: tuple[int, ...]
    reset_c: tuple[int, ...]
    reset_fixed_after: tuple[int, ...]
    independent_b: MameMapperBootObservation
    window_a: MameMapperBootObservation
    paired_b: MameMapperBootObservation
    selector_flash41: tuple[int, ...]
    selector_read41: int
    selector_flash7f: tuple[int, ...]
    selector_read7f: int
    selector_ram80: int
    selector_read80: int
    selector_ram86: int
    selector_read86: int
    selector_b85: int
    selector_read85: int
    selector_cfe: int
    selector_readfe: int
    paired_a: tuple[int, ...]
    paired_b_bytes: tuple[int, ...]
    paired_c: int
    paired_port5: int
    paired_port6: int
    paired_port7: int
    absent_initial: tuple[int, ...]
    absent_patterned: tuple[int, ...]
    overlay_b_before: int
    overlay_c_before: int
    overlay_forced_b_after: int
    overlay_underlying_b_after: int
    overlay_forced_c_after: int
    overlay_underlying_c_after: int
    fetch_marker: int
    fetch_pc: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _one_line(output: str, prefix: str) -> dict[str, str]:
    matches = [line for line in output.splitlines() if line.startswith(prefix)]
    if len(matches) != 1:
        raise MameRuntimeError(
            f"MAME mapper output requires exactly one {prefix.strip()} line"
        )
    return parse_report_fields(matches[0])


def _hex_bytes(value: str, count: int, name: str) -> tuple[int, ...]:
    if len(value) != count * 2:
        raise MameRuntimeError(f"MAME mapper {name} must contain exactly {count} bytes")
    try:
        return tuple(
            int(value[index : index + 2], 16) for index in range(0, count * 2, 2)
        )
    except ValueError as error:
        raise MameRuntimeError(f"invalid MAME mapper {name}") from error


def _hex(fields: dict[str, str], name: str) -> int:
    try:
        return int(fields[name], 16)
    except KeyError as error:
        raise MameRuntimeError(f"MAME mapper report omits field {name}") from error
    except ValueError as error:
        raise MameRuntimeError(f"invalid MAME mapper field {name}") from error


def _block(fields: dict[str, str], name: str, count: int) -> tuple[int, ...]:
    try:
        return _hex_bytes(fields[name], count, name)
    except KeyError as error:
        raise MameRuntimeError(f"MAME mapper report omits field {name}") from error


def _boot_observation(fields: dict[str, str]) -> MameMapperBootObservation:
    try:
        case = fields["case"]
    except KeyError as error:
        raise MameRuntimeError("MAME mapper boot report omits field case") from error
    return MameMapperBootObservation(
        case=case,
        mode=_hex(fields, "mode"),
        bank_a=_hex(fields, "bank_a"),
        bank_b=_hex(fields, "bank_b"),
        address=_hex(fields, "address"),
        fixed_before=_block(fields, "fixed_before", 2),
        observed=_hex(fields, "observed"),
        fixed_after=_block(fields, "fixed_after", 2),
        pc=_hex(fields, "pc"),
    )


def parse_mame_mapper_report(output: str) -> MameMapperReport:
    """Parse all five isolated MAME mapper runs into one typed report."""

    identity_lines = [
        parse_report_fields(line)
        for line in output.splitlines()
        if line.startswith("MAME_MAPPER identity ")
    ]
    if len(identity_lines) != len(PROBE_CASES):
        raise MameRuntimeError("MAME mapper output requires five identity lines")
    try:
        identities = {fields["case"]: fields for fields in identity_lines}
    except KeyError as error:
        raise MameRuntimeError("MAME mapper identity omits its case") from error
    if set(identities) != set(PROBE_CASES):
        raise MameRuntimeError("MAME mapper identities do not cover every probe case")
    machines = {fields.get("machine") for fields in identity_lines}
    versions = {fields.get("version") for fields in identity_lines}
    if len(machines) != 1 or None in machines or len(versions) != 1 or None in versions:
        raise MameRuntimeError("MAME mapper identities disagree")

    reset = _one_line(output, "MAME_MAPPER reset ")
    boot_lines = [
        parse_report_fields(line)
        for line in output.splitlines()
        if line.startswith("MAME_MAPPER boot ")
    ]
    if len(boot_lines) != 3:
        raise MameRuntimeError("MAME mapper output requires three boot lines")
    try:
        boots = {fields["case"]: _boot_observation(fields) for fields in boot_lines}
    except KeyError as error:
        raise MameRuntimeError("MAME mapper boot report omits its case") from error
    if set(boots) != {"independent_b", "window_a", "paired_b"}:
        raise MameRuntimeError("MAME mapper boot cases are incomplete")

    selectors = _one_line(output, "MAME_MAPPER selectors ")
    paired = _one_line(output, "MAME_MAPPER paired ")
    absent = _one_line(output, "MAME_MAPPER absent ")
    overlay = _one_line(output, "MAME_MAPPER overlay ")
    fetch = _one_line(output, "MAME_MAPPER fetch ")

    machine = next(iter(machines))
    version = next(iter(versions))
    assert machine is not None and version is not None
    return MameMapperReport(
        machine=machine,
        version=version,
        reset_pc=_hex(reset, "pc"),
        reset_ports=_block(reset, "ports", 4),
        reset_fixed_before=_block(reset, "fixed_before", 2),
        reset_a=_block(reset, "a", 2),
        reset_b=_block(reset, "b", 2),
        reset_c=_block(reset, "c", 2),
        reset_fixed_after=_block(reset, "fixed_after", 2),
        independent_b=boots["independent_b"],
        window_a=boots["window_a"],
        paired_b=boots["paired_b"],
        selector_flash41=_block(selectors, "flash41", 2),
        selector_read41=_hex(selectors, "read41"),
        selector_flash7f=_block(selectors, "flash7f", 2),
        selector_read7f=_hex(selectors, "read7f"),
        selector_ram80=_hex(selectors, "ram80"),
        selector_read80=_hex(selectors, "read80"),
        selector_ram86=_hex(selectors, "ram86"),
        selector_read86=_hex(selectors, "read86"),
        selector_b85=_hex(selectors, "b85"),
        selector_read85=_hex(selectors, "read85"),
        selector_cfe=_hex(selectors, "cfe"),
        selector_readfe=_hex(selectors, "readfe"),
        paired_a=_block(paired, "a", 2),
        paired_b_bytes=_block(paired, "b", 2),
        paired_c=_hex(paired, "c"),
        paired_port5=_hex(paired, "port5"),
        paired_port6=_hex(paired, "port6"),
        paired_port7=_hex(paired, "port7"),
        absent_initial=_block(absent, "initial", 4),
        absent_patterned=_block(absent, "patterned", 4),
        overlay_b_before=_hex(overlay, "b_before"),
        overlay_c_before=_hex(overlay, "c_before"),
        overlay_forced_b_after=_hex(overlay, "forced_b_after"),
        overlay_underlying_b_after=_hex(overlay, "underlying_b_after"),
        overlay_forced_c_after=_hex(overlay, "forced_c_after"),
        overlay_underlying_c_after=_hex(overlay, "underlying_c_after"),
        fetch_marker=_hex(fetch, "marker"),
        fetch_pc=_hex(fetch, "pc"),
    )


def _prefix(mapper: Ti83PlusMapper, logical: int) -> tuple[int, ...]:
    kind, page = mapper.mapped_address(logical)
    if kind != "flash" or page not in ROM_PREFIXES:
        raise AssertionError(f"expected a pinned Flash prefix at 0x{logical:04X}")
    return ROM_PREFIXES[page]


def _expected_boot(
    case: str, address: int, mode: int, bank_a: int, bank_b: int
) -> MameMapperBootObservation:
    mapper = Ti83PlusMapper.ti84p_reset("mame")
    mapper.write_port(0x04, 0)
    mapper.write_port(0x05, 0)
    mapper.write_port(0x06, bank_a)
    mapper.write_port(0x07, bank_b)
    if mode:
        mapper.write_port(0x07, 0x80)
        mapper.write_port(0x04, mode)
    fixed_before = _prefix(mapper, 0)
    kind, page = mapper.read_address(address)
    if kind != "flash" or page not in ROM_PREFIXES:
        raise AssertionError("boot case did not read one of the pinned Flash pages")
    observed = ROM_PREFIXES[page][address & 1]
    return MameMapperBootObservation(
        case=case,
        mode=mode,
        bank_a=mapper.bank_a or 0,
        bank_b=mapper.bank_b or 0,
        address=address,
        fixed_before=fixed_before,
        observed=observed,
        fixed_after=_prefix(mapper, 0),
        pc=0xC008,
    )


def expected_mame_mapper_report() -> MameMapperReport:
    """Derive the exact runtime observations from the pinned mapper profile."""

    reset = Ti83PlusMapper.ti84p_reset("mame")
    reset_fixed_before = _prefix(reset, 0)
    reset_a = _prefix(reset, 0x4000)
    reset_b = _prefix(reset, 0x8000)
    reset_c = _prefix(reset, 0xC000)
    reset.read_address(0x4000)

    mapping = Ti83PlusMapper.ti84p_reset("mame")
    mapping.write_port(0x04, 0)
    mapping.write_port(0x06, 0x41)
    flash41 = _prefix(mapping, 0x4000)
    read41 = mapping.read_port(0x06)
    mapping.write_port(0x06, 0x7F)
    flash7f = _prefix(mapping, 0x4000)
    read7f = mapping.read_port(0x06)
    mapping.write_port(0x06, 0x80)
    read80 = mapping.read_port(0x06)
    mapping.write_port(0x06, 0x86)
    read86 = mapping.read_port(0x06)
    mapping.write_port(0x07, 0x85)
    read85 = mapping.read_port(0x07)
    mapping.write_port(0x05, 0xFE)
    readfe = mapping.read_port(0x05)
    mapping.write_port(0x06, 0x02)
    mapping.write_port(0x07, 0x83)
    mapping.write_port(0x04, 1)

    scalar_reads = (read41, read7f, read80, read86, read85, readfe)
    if any(value is None for value in scalar_reads):
        raise AssertionError("MAME selector source model lost readback")

    return MameMapperReport(
        machine="ti84pv3",
        version=MAME_VERSION,
        reset_pc=reset.initial_pc or 0,
        reset_ports=(0x08, 0x00, 0x00, 0x00),
        reset_fixed_before=reset_fixed_before,
        reset_a=reset_a,
        reset_b=reset_b,
        reset_c=reset_c,
        reset_fixed_after=_prefix(reset, 0),
        independent_b=_expected_boot("independent_b", 0x8000, 0, 1, 2),
        window_a=_expected_boot("window_a", 0x4000, 0, 1, 2),
        paired_b=_expected_boot("paired_b", 0x8001, 1, 2, 0x80),
        selector_flash41=flash41,
        selector_read41=int(read41),
        selector_flash7f=flash7f,
        selector_read7f=int(read7f),
        selector_ram80=0xA0,
        selector_read80=int(read80),
        selector_ram86=0xA6,
        selector_read86=int(read86),
        selector_b85=0xA5,
        selector_read85=int(read85),
        selector_cfe=0xA6,
        selector_readfe=int(readfe),
        paired_a=_prefix(mapping, 0x4000),
        paired_b_bytes=_prefix(mapping, 0x8000),
        paired_c=0xA3,
        paired_port5=0x06,
        paired_port6=0x02,
        paired_port7=0x83,
        absent_initial=(0, 0, 0, 0),
        absent_patterned=(0, 0, 0, 0),
        overlay_b_before=0xA2,
        overlay_c_before=0xD3,
        overlay_forced_b_after=0xA1,
        overlay_underlying_b_after=0xE2,
        overlay_forced_c_after=0xD0,
        overlay_underlying_c_after=0xE3,
        fetch_marker=0x22,
        fetch_pc=0xC303,
    )


def validate_mame_mapper_report(report: MameMapperReport) -> dict[str, object]:
    """Require all native observations implied by MAME 0.287's mapper source."""

    expected = expected_mame_mapper_report()
    if report != expected:
        raise MameRuntimeError(
            "MAME mapper report disagrees with the 0.287 source model"
        )
    profile = mapper_profile("mame")
    return {
        "source_model": {
            "mapped_ports": sorted(profile.mapped_ports),
            "unmapped_tested_ports": [0x0E, 0x0F, 0x27, 0x28],
            "reset_mapping": "Flash 3F/00/01/00 in paired mode",
            "fixed_page_handoff": (
                "reads from A and paired B clear the latch; independent B does not"
            ),
            "lua_program_reads_have_side_effects": True,
            "flash_selector_mask": profile.flash_selector_mask,
            "port5_write_mask": profile.port5_write_mask,
            "safe_ram_selectors_executed": [0x80, 0x81, 0x82, 0x83, 0x85, 0x86],
            "unsafe_ram_selector_87_executed": False,
            "mapped_ram_page_count": profile.accessible_ram_pages,
            "forced_ram_overlays": False,
            "fetch_discriminator": (
                "RAM page 2 marker 22 executed; RAM page 1 overlay marker 11 did not"
            ),
        },
        "native": report.to_dict(),
    }
