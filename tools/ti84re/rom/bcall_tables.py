"""Parse main, boot, and page-0 bjump tables from a retail TI ROM."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Iterator

from ti84re.rom.image import RomImage, RomLocation


BOOT_TABLE_PAGE = 0x3F
BOOT_TABLE_ID_RANGES = ((0x8018, 0x80D2), (0x80E4, 0x8129))
BOOTFREE_PAGE3F_PREFIX = bytes.fromhex("3e3fd306d307c32c81")
RETAIL_PAGE3F_PREFIX = bytes.fromhex("3e07d3043e7fd3063e03d30ec32c81")


@dataclass(frozen=True)
class BcallTarget:
    id: int
    address: int
    raw_page: int
    name: str | None = None

    @property
    def page(self) -> int:
        return self.raw_page & 0x3F

    @property
    def location(self) -> RomLocation:
        return RomLocation(self.page, self.address)

    @property
    def table_bytes(self) -> bytes:
        return self.address.to_bytes(2, "little") + bytes([self.raw_page])


@dataclass(frozen=True)
class BjumpTarget:
    trampoline: int
    address: int
    raw_page: int

    @property
    def page(self) -> int:
        return self.raw_page & 0x3F


def parse_target(id_value: int, raw: bytes, name: str | None = None) -> BcallTarget:
    if len(raw) != 3:
        raise ValueError(f"bcall entry must contain three bytes, got {len(raw)}")
    return BcallTarget(
        id=id_value,
        address=int.from_bytes(raw[:2], "little"),
        raw_page=raw[2],
        name=name,
    )


def main_target(
    rom: RomImage, table_page: int, id_value: int, name: str | None = None
) -> BcallTarget:
    if not 0x4000 <= id_value < 0x8000:
        raise ValueError(f"main bcall ID must be in 0x4000–0x7FFF, got 0x{id_value:X}")
    return parse_target(
        id_value, rom.bytes_at(table_page, id_value, 3), name=name
    )


def boot_target(
    rom: RomImage, id_value: int, name: str | None = None
) -> BcallTarget | None:
    if not 0x8000 <= id_value < 0xC000:
        raise ValueError(f"boot bcall ID must be in 0x8000–0xBFFF, got 0x{id_value:X}")
    if not any(
        first <= id_value <= last and (id_value - first) % 3 == 0
        for first, last in BOOT_TABLE_ID_RANGES
    ):
        return None
    table_address = 0x4000 + (id_value & 0x3FFF)
    raw = rom.bytes_at(BOOT_TABLE_PAGE, table_address, 3)
    if raw in (b"\0\0\0", b"\xFF\xFF\xFF"):
        return None
    return parse_target(id_value, raw, name=name)


def target_is_valid(rom: RomImage, target: BcallTarget) -> bool:
    return (
        target.page < rom.page_count
        and (target.address < 0x4000 or 0x4000 <= target.address <= 0x7FFF)
    )


def main_table_score(
    rom: RomImage, table_page: int, ids: Iterable[int]
) -> int:
    score = 0
    for id_value in ids:
        target = main_target(rom, table_page, id_value)
        if target.table_bytes in (b"\0\0\0", b"\xFF\xFF\xFF"):
            continue
        score += target_is_valid(rom, target)
    return score


def find_main_table_page(rom: RomImage, ids: Iterable[int]) -> tuple[int, int]:
    ids = tuple(ids)
    scores = [main_table_score(rom, page, ids) for page in range(rom.page_count)]
    page = max(range(rom.page_count), key=scores.__getitem__)
    if scores[page] == 0:
        raise ValueError("could not find a plausible main bcall table")
    return page, scores[page]


def classify_boot_page(rom: RomImage) -> str:
    prefix = rom.bytes_at(BOOT_TABLE_PAGE, 0x4000, 0x20)
    if prefix.startswith(BOOTFREE_PAGE3F_PREFIX):
        return "bootfree"
    if prefix.startswith(RETAIL_PAGE3F_PREFIX):
        return "retail"
    return "unknown"


def read_main_names(path: Path) -> dict[int, str]:
    names: dict[int, str] = {}
    with path.open(encoding="utf-8") as fp:
        for line in fp:
            fields = line.split()
            if len(fields) == 2:
                names[int(fields[0], 16)] = fields[1]
    return names


def read_equate_names(
    path: Path, minimum: int = 0x0000, maximum: int = 0xFFFF
) -> dict[int, str]:
    """Read the first assembly equate name for each value in a range."""

    names: dict[int, str] = {}
    pattern = re.compile(
        r"\s*([A-Za-z_][A-Za-z0-9_]*)\s+equ\s+([0-9A-Fa-f]+)h\b",
        re.IGNORECASE,
    )
    with path.open(encoding="latin1") as fp:
        for line in fp:
            match = pattern.match(line)
            if match:
                value = int(match.group(2), 16)
                if minimum <= value <= maximum:
                    names.setdefault(value, match.group(1))
    return names


def read_boot_names(path: Path) -> dict[int, str]:
    names: dict[int, str] = {}
    in_boot_section = False
    pattern = re.compile(
        r"\s*([A-Za-z_][A-Za-z0-9_]*)\s+equ\s+([0-9A-Fa-f]{4})h\b"
    )
    with path.open(encoding="latin1") as fp:
        for line in fp:
            if "bootbtf" in line and "equ" in line and "8000h" in line:
                in_boot_section = True
            if in_boot_section and line.strip().startswith(";RAM Equates"):
                break
            if not in_boot_section:
                continue
            match = pattern.match(line)
            if match:
                id_value = int(match.group(2), 16)
                if 0x8018 <= id_value <= 0x8129:
                    names[id_value] = match.group(1)
    return names


def iter_bjump_targets(
    rom: RomImage, start: int = 0x3B01, stop: int = 0x3E80
) -> Iterator[BjumpTarget]:
    address = start
    while address < stop:
        raw = rom.bytes_at(0, address, 6)
        if raw[:3] != bytes.fromhex("CD092B"):
            break
        yield BjumpTarget(
            trampoline=address,
            address=int.from_bytes(raw[3:5], "little"),
            raw_page=raw[5],
        )
        address += 6
