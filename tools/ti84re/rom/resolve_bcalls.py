#!/usr/bin/env python3
"""Resolve main, bjump, and retail boot bcall targets from the raw ROM."""


from ti84re.rom.bcall_tables import (
    BOOTFREE_PAGE3F_PREFIX,
    boot_target,
    classify_boot_page,
    find_main_table_page,
    iter_bjump_targets,
    main_target,
    read_boot_names,
    read_main_names,
    target_is_valid,
)
from ti84re.rom.image import RomImage
from ti84re.paths import SYMBOLS, DEFAULT_ROM


rom = RomImage.from_path(DEFAULT_ROM)
main_names = read_main_names(SYMBOLS / "bcalls.txt")
main_ids = sorted(id_value for id_value in main_names if 0x4000 <= id_value < 0x8000)
table_page, _score = find_main_table_page(rom, main_ids)

valid_count = 0
with (SYMBOLS / "bcall_targets.txt").open("w", encoding="utf-8") as fp:
    for id_value in main_ids:
        target = main_target(rom, table_page, id_value, main_names[id_value])
        fp.write(
            f"{target.name}\t{target.id:04X}\t{target.address:04X}\t{target.page:02X}\n"
        )
        valid_count += target_is_valid(rom, target)
print(
    f"table page = 0x{table_page:02X}; wrote {len(main_ids)} main targets "
    f"({valid_count} valid)"
)

bjumps = list(iter_bjump_targets(rom))
with (SYMBOLS / "bjumps.txt").open("w", encoding="utf-8") as fp:
    for target in bjumps:
        fp.write(
            f"{target.trampoline:04X}\t{target.address:04X}\t{target.page:02X}\n"
        )
end = bjumps[-1].trampoline + 6 if bjumps else 0x3B01
print(f"wrote {len(bjumps)} bjump trampoline entries (0x3B01..0x{end:04X})")

kind = classify_boot_page(rom)
with (SYMBOLS / "bcalls8x_targets.txt").open("w", encoding="utf-8") as fp:
    if kind == "bootfree":
        prefix = rom.bytes_at(0x3F, 0x4000, len(BOOTFREE_PAGE3F_PREFIX))
        fp.write("# 0x8xxx body targets intentionally unresolved.\n")
        fp.write(
            "# Skipped: page 0x3F starts with the BootFree replacement prefix "
            f"{prefix.hex(' ').upper()}.\n"
        )
    elif kind == "retail":
        count = 0
        for id_value, name in sorted(read_boot_names(SYMBOLS / "ti83plus.inc").items()):
            target = boot_target(rom, id_value, name)
            if target is None or not target_is_valid(rom, target):
                continue
            fp.write(
                f"{target.name}\t{target.id:04X}\t{target.address:04X}"
                f"\t{target.page:02X}\n"
            )
            count += 1
        print(f"wrote {count} retail 0x8xxx boot targets")
    else:
        prefix = rom.bytes_at(0x3F, 0x4000, 16)
        fp.write("# 0x8xxx body targets intentionally unresolved.\n")
        fp.write(
            "# Skipped: page 0x3F has an unknown boot prefix "
            f"{prefix.hex(' ').upper()}.\n"
        )
print(f"0x8xxx body target status: page 0x3F kind={kind}")
