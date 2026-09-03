"""Reusable oracle for the native Wabbitemu memory-mapper edge probe."""

from __future__ import annotations

import json

from ti84re.hardware.memory_mapper import MAPPING_PORTS, Ti83PlusMapper
from ti84re.emulators.wabbitemu.headless import WabbitemuHeadlessError, WabbitemuMapperReport


def _marker_read(
    mapper: Ti83PlusMapper,
    logical: int,
    markers: dict[tuple[str, int, int], int],
) -> int:
    kind, page = mapper.mapped_address(logical)
    if kind is None or page is None:
        raise ValueError(f"mapper did not resolve logical address 0x{logical:04X}")
    physical_page = page & 0x7F if kind == "ram" else page
    return markers[(kind, physical_page, logical & 0x3FFF)]


def expected_mapper_values() -> dict[str, object]:
    """Return the pinned source-model value for every native mapper case."""

    mapper = Ti83PlusMapper.ti84p_reset("wabbitemu")
    initial_pages = tuple(mapper.mapped_page(region) for region in range(4))
    mapper.read_address(0x4000)
    changed_after_data = not mapper.boot_latch
    fixed_after_data = mapper.fixed_page
    mapper.read_address(0x4000, opcode_fetch=True)
    changed_after_opcode = not mapper.boot_latch
    fixed_after_opcode = mapper.fixed_page

    mapper.write_port(0x05, 0xFF)
    port05_ff_read = mapper.read_port(0x05)
    mapper.write_port(0x0E, 0xFF)
    mapper.write_port(0x06, 0x7F)
    port0e_ff_read = mapper.read_port(0x0E)
    port06_flash_read = mapper.read_port(0x06)
    stored_port06_flash = mapper.bank_a
    mapper.write_port(0x0F, 0xFF)
    mapper.write_port(0x07, 0x7F)
    port0f_ff_read = mapper.read_port(0x0F)
    port07_flash_read = mapper.read_port(0x07)
    stored_port07_flash = mapper.bank_b
    mapper.write_port(0x06, 0xFF)
    port06_ram_ff_read = mapper.read_port(0x06)
    stored_port06_ram = mapper.bank_a
    mapper.write_port(0x07, 0xFE)
    port07_ram_fe_read = mapper.read_port(0x07)
    stored_port07_ram = mapper.bank_b

    mapper.write_port(0x05, 0x05)
    mapper.write_port(0x06, 0x02)
    mapper.write_port(0x07, 0x83)
    mapper.write_port(0x04, 0x01)
    paired_pages = tuple(mapper.mapped_page(region) for region in range(1, 4))
    paired_reads = tuple(mapper.read_port(port) for port in (0x05, 0x06, 0x07))

    mapper.write_port(0x04, 0x00)
    mapper.write_port(0x06, 0x04)
    mapper.write_port(0x07, 0x02)
    mapper.write_port(0x05, 0x05)
    mapper.write_port(0x28, 0x01)
    mapper.write_port(0x27, 0xFF)
    independent_markers = {
        ("ram", 1, 0x0000): 0xB0,
        ("ram", 1, 0x003F): 0xB1,
        ("flash", 2, 0x0040): 0xA2,
        ("ram", 5, 0x3B63): 0xC3,
        ("ram", 0, 0x3B64): 0xD4,
    }
    independent_reads = tuple(
        _marker_read(mapper, logical, independent_markers)
        for logical in (0x8000, 0x803F, 0x8040, 0xFB63, 0xFB64)
    )

    mapper.write_port(0x04, 0x01)
    paired_markers = {
        ("flash", 4, 0x0000): 0xE0,
        ("flash", 4, 0x003F): 0xE1,
        ("flash", 4, 0x0040): 0xE2,
        ("flash", 2, 0x3B63): 0xF3,
        ("flash", 2, 0x3B64): 0xF4,
    }
    paired_overlay_reads = tuple(
        _marker_read(mapper, logical, paired_markers)
        for logical in (0x8000, 0x803F, 0x8040, 0xFB63, 0xFB64)
    )

    return {
        **{f"port{port:02x}_active": port in MAPPING_PORTS for port in MAPPING_PORTS},
        "initial_port04_status": 0x08,
        "initial_port05": 0,
        "initial_port06": 0,
        "initial_port07": 0,
        "initial_port0e": 0,
        "initial_port0f": 0,
        "initial_port27": 0,
        "initial_port28": 0,
        "initial_boot_mapped": False,
        "initial_page0_changed": False,
        "initial_fixed_page": initial_pages[0][1],
        "initial_a_page": initial_pages[1][1],
        "initial_b_page": initial_pages[2][1],
        "initial_c_page": initial_pages[3][1] & 0x7F,
        "initial_a_ram": initial_pages[1][0] == "ram",
        "initial_b_ram": initial_pages[2][0] == "ram",
        "initial_c_ram": initial_pages[3][0] == "ram",
        "fixed_page_after_data_read": fixed_after_data,
        "page0_changed_after_data_read": changed_after_data,
        "fixed_page_after_opcode": fixed_after_opcode,
        "page0_changed_after_opcode": changed_after_opcode,
        "handoff_pc": 0x4001,
        "port05_ff_read": port05_ff_read,
        "port0e_ff_read": port0e_ff_read,
        "port06_flash_read": port06_flash_read,
        "stored_port06_flash": stored_port06_flash,
        "port0f_ff_read": port0f_ff_read,
        "port07_flash_read": port07_flash_read,
        "stored_port07_flash": stored_port07_flash,
        "port06_ram_ff_read": port06_ram_ff_read,
        "stored_port06_ram": stored_port06_ram,
        "port07_ram_fe_read": port07_ram_fe_read,
        "stored_port07_ram": stored_port07_ram,
        "paired_port04_status": 0x08,
        "paired_port05": paired_reads[0],
        "paired_port06": paired_reads[1],
        "paired_port07": paired_reads[2],
        "paired_boot_mapped": True,
        "paired_a_page": paired_pages[0][1],
        "paired_b_page": paired_pages[1][1],
        "paired_c_page": paired_pages[2][1] & 0x7F,
        "paired_a_ram": paired_pages[0][0] == "ram",
        "paired_b_ram": paired_pages[1][0] == "ram",
        "paired_c_ram": paired_pages[2][0] == "ram",
        "port27_ff_read": 0xFF,
        "port28_one_read": 0x01,
        "independent_8000": independent_reads[0],
        "independent_803f": independent_reads[1],
        "independent_8040": independent_reads[2],
        "independent_fb63": independent_reads[3],
        "independent_fb64": independent_reads[4],
        "independent_write_ram1": 0xC1,
        "independent_write_underlying_b": 0xA0,
        "independent_write_ram0": 0xC2,
        "independent_write_underlying_c": 0xC4,
        "independent_fetch_halted": False,
        "paired_8000": paired_overlay_reads[0],
        "paired_803f": paired_overlay_reads[1],
        "paired_8040": paired_overlay_reads[2],
        "paired_fb63": paired_overlay_reads[3],
        "paired_fb64": paired_overlay_reads[4],
        "paired_fetch_halted": True,
        "paired_write_ram1": 0x00,
        "paired_write_underlying_b": 0xD1,
        "paired_write_ram0": 0xC2,
        "paired_write_underlying_c": 0xD2,
        "tstates": 12,
    }


def validate_mapper_report(report: WabbitemuMapperReport) -> dict[str, object]:
    """Check native mapper observations against the reusable source model."""

    expected = expected_mapper_values()
    observed = report.to_dict()
    disagreements = {
        name: {"expected": value, "observed": observed[name]}
        for name, value in expected.items()
        if observed[name] != value
    }
    if disagreements:
        raise WabbitemuHeadlessError(
            "native mapper report disagrees with the pinned model: "
            + json.dumps(disagreements, sort_keys=True)
        )
    return {
        "source_model": {
            "mapped_ports": sorted(MAPPING_PORTS),
            "reset_mapping": "Flash 3F/00/00 and RAM 80 in independent mode",
            "fixed_page_handoff": "first qualifying opcode fetch, not a data read",
            "selector_readback": "visible mapped pages rather than raw selector latches",
            "paired_even_selector": "A and B both expose the even page",
            "independent_overlays": "reads, writes, and fetch bytes route through RAM",
            "paired_overlays": "port 0x04 bit 0 disables both forced-RAM ranges",
            "direct_seed_scope": (
                "backing bytes and low-level writes isolate mapper routing; "
                "they do not model Flash command acceptance"
            ),
        },
        "native": observed,
    }
