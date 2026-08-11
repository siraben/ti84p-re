/* Direct-core Flash command and status probe for pinned TilEm 2.1. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <tilem.h>
#include <z80.h>

#include "tilem_probe_support.h"

#define FLASH_READ 0

#define TARGET 0x020100
#define SECTOR_START 0x020000
#define SECTOR_SIZE 0x010000
#define SECTOR_END (SECTOR_START + SECTOR_SIZE)

static TilemCalc *new_flash_calc(byte fill, byte overridegroup) {
    TilemCalc *calc = tilem_probe_new_calc();
    memset(calc->mem, fill, calc->hw.romsize);
    calc->flash.unlock = 1;
    calc->flash.state = FLASH_READ;
    calc->flash.busy = 0;
    calc->flash.progaddr = 0;
    calc->flash.progbyte = 0;
    calc->flash.toggles = 0;
    calc->flash.overridegroup = overridegroup;
    calc->flash.emuflags = TILEM_FLASH_REQUIRE_DELAY;
    return calc;
}

static void write_unlock_prefix(TilemCalc *calc) {
    tilem_flash_write_byte(calc, 0x000AAA, 0xAA);
    tilem_flash_write_byte(calc, 0x000555, 0x55);
}

static void write_command(TilemCalc *calc, byte command) {
    write_unlock_prefix(calc);
    tilem_flash_write_byte(calc, 0x000AAA, command);
}

static void write_program(TilemCalc *calc, dword address, byte value) {
    write_command(calc, 0xA0);
    tilem_flash_write_byte(calc, address, value);
}

static void write_sector_erase(TilemCalc *calc, dword address) {
    write_command(calc, 0x80);
    write_unlock_prefix(calc);
    tilem_flash_write_byte(calc, address, 0x30);
}

static void write_chip_erase(TilemCalc *calc) {
    write_command(calc, 0x80);
    write_unlock_prefix(calc);
    tilem_flash_write_byte(calc, 0x000AAA, 0x10);
}

static void expire_flash_timer(TilemCalc *calc) {
    tilem_z80_set_timer(calc, TILEM_TIMER_FLASH_DELAY, 0, 0, 1);
    tilem_flash_delay_timer(calc, NULL);
}

static size_t count_non_ff(const byte *bytes, size_t size) {
    size_t count = 0;
    size_t index;
    for (index = 0; index < size; ++index) {
        if (bytes[index] != 0xFF) {
            ++count;
        }
    }
    return count;
}

static size_t count_differences(
    const byte *before,
    const byte *after,
    size_t start,
    size_t end
) {
    size_t count = 0;
    size_t index;
    for (index = start; index < end; ++index) {
        if (before[index] != after[index]) {
            ++count;
        }
    }
    return count;
}

int main(int argc, char **argv) {
    TilemCalc *locked;
    TilemCalc *autoselect;
    TilemCalc *partial;
    TilemCalc *cfi;
    TilemCalc *suspend;
    TilemCalc *fast;
    TilemCalc *legal;
    TilemCalc *illegal;
    TilemCalc *sector;
    TilemCalc *chip_default;
    TilemCalc *chip_override;
    byte *sector_before;
    size_t sector_erased;
    size_t sector_changed;
    size_t sector_outside_changed;
    size_t chip_default_non_ff;
    size_t chip_override_non_ff;
    byte legal_read1;
    byte legal_read2;
    byte illegal_busy_read1;
    byte illegal_busy_read2;
    byte illegal_error_read1;
    byte illegal_error_read2;
    byte erase_wait_read1;
    byte erase_wait_read2;
    byte erase_busy_read1;
    byte erase_busy_read2;
    int legal_timer;
    int illegal_timer;
    int sector_wait_timer;
    int sector_erase_timer;
    int erase_busy;
    int initial_sector_count;
    int partial_state_before_reset;
    int suspend_window_state;
    int suspend_state;
    int resume_state;
    int fast_entry_state;
    int fast_first_select_state;
    int fast_after_first_state;
    int fast_second_select_state;
    int fast_after_second_state;
    int fast_exit_select_state;
    int legal_state;
    int legal_busy;
    int legal_final_busy;
    byte legal_final_read;
    int illegal_initial_state;
    int illegal_initial_busy;
    int illegal_error_state;
    int illegal_reset_state;
    byte illegal_final_read;
    int sector_state;
    int sector_busy;
    dword sector_progaddr;
    int sector_final_busy;
    byte sector_final_read;

    if (argc != 2 || strcmp(argv[1], "--flash-probe") != 0) {
        fprintf(stderr, "usage: %s --flash-probe\n", argv[0]);
        return 2;
    }

    locked = new_flash_calc(0xFF, 0);
    initial_sector_count = locked->hw.nflashsectors;
    locked->flash.unlock = 0;
    write_program(locked, TARGET, 0x50);

    autoselect = new_flash_calc(0xFF, 0);
    write_command(autoselect, 0x90);

    partial = new_flash_calc(0xFF, 0);
    tilem_flash_write_byte(partial, 0x000AAA, 0xAA);
    partial_state_before_reset = partial->flash.state;
    tilem_flash_write_byte(partial, 0x000AAA, 0xF0);

    cfi = new_flash_calc(0xFF, 0);
    tilem_flash_write_byte(cfi, 0x000055, 0x98);

    suspend = new_flash_calc(0x00, 0);
    write_command(suspend, 0x80);
    write_unlock_prefix(suspend);
    suspend_window_state = suspend->flash.state;
    tilem_flash_write_byte(suspend, TARGET, 0xB0);
    suspend_state = suspend->flash.state;
    tilem_flash_write_byte(suspend, TARGET, 0x30);
    resume_state = suspend->flash.state;

    fast = new_flash_calc(0xFF, 0);
    fast->mem[TARGET] = 0xF0;
    fast->mem[TARGET + 1] = 0xAA;
    write_command(fast, 0x20);
    fast_entry_state = fast->flash.state;
    tilem_flash_write_byte(fast, TARGET, 0xA0);
    fast_first_select_state = fast->flash.state;
    tilem_flash_write_byte(fast, TARGET, 0x50);
    fast_after_first_state = fast->flash.state;
    expire_flash_timer(fast);
    tilem_flash_write_byte(fast, TARGET, 0xA0);
    fast_second_select_state = fast->flash.state;
    tilem_flash_write_byte(fast, TARGET + 1, 0xA0);
    fast_after_second_state = fast->flash.state;
    expire_flash_timer(fast);
    tilem_flash_write_byte(fast, TARGET, 0x90);
    fast_exit_select_state = fast->flash.state;
    tilem_flash_write_byte(fast, TARGET, 0xF0);

    legal = new_flash_calc(0xFF, 0);
    legal->mem[TARGET] = 0xFF;
    write_program(legal, TARGET, 0x50);
    legal_state = legal->flash.state;
    legal_busy = legal->flash.busy;
    legal_timer = tilem_z80_get_timer_clocks(legal, TILEM_TIMER_FLASH_DELAY);
    legal_read1 = tilem_flash_read_byte(legal, TARGET);
    legal_read2 = tilem_flash_read_byte(legal, TARGET);
    expire_flash_timer(legal);
    legal_final_busy = legal->flash.busy;
    legal_final_read = tilem_flash_read_byte(legal, TARGET);

    illegal = new_flash_calc(0xFF, 0);
    illegal->mem[TARGET] = 0x50;
    write_program(illegal, TARGET, 0xD0);
    illegal_initial_state = illegal->flash.state;
    illegal_initial_busy = illegal->flash.busy;
    illegal_timer = tilem_z80_get_timer_clocks(illegal, TILEM_TIMER_FLASH_DELAY);
    illegal_busy_read1 = tilem_flash_read_byte(illegal, TARGET);
    illegal_busy_read2 = tilem_flash_read_byte(illegal, TARGET);
    expire_flash_timer(illegal);
    illegal_error_state = illegal->flash.state;
    illegal_error_read1 = tilem_flash_read_byte(illegal, TARGET);
    illegal_error_read2 = tilem_flash_read_byte(illegal, TARGET);
    tilem_flash_write_byte(illegal, TARGET, 0xF0);
    illegal_reset_state = illegal->flash.state;
    illegal_final_read = tilem_flash_read_byte(illegal, TARGET);

    sector = new_flash_calc(0xFF, 0);
    memset(sector->mem + SECTOR_START, 0, SECTOR_SIZE);
    sector->mem[SECTOR_START - 1] = 0x5A;
    sector->mem[SECTOR_END] = 0xA5;
    sector_before = malloc(sector->hw.romsize);
    if (sector_before == NULL) {
        fputs("cannot allocate sector snapshot\n", stderr);
        return 1;
    }
    memcpy(sector_before, sector->mem, sector->hw.romsize);
    write_sector_erase(sector, TARGET);
    sector_state = sector->flash.state;
    sector_busy = sector->flash.busy;
    sector_progaddr = sector->flash.progaddr;
    sector_wait_timer = tilem_z80_get_timer_clocks(
        sector, TILEM_TIMER_FLASH_DELAY
    );
    sector_erased = SECTOR_SIZE - count_non_ff(
        sector->mem + SECTOR_START, SECTOR_SIZE
    );
    sector_changed = count_differences(
        sector_before, sector->mem, SECTOR_START, SECTOR_END
    );
    sector_outside_changed = count_differences(
        sector_before, sector->mem, 0, SECTOR_START
    ) + count_differences(
        sector_before, sector->mem, SECTOR_END, sector->hw.romsize
    );
    erase_wait_read1 = tilem_flash_read_byte(sector, TARGET);
    erase_wait_read2 = tilem_flash_read_byte(sector, TARGET);
    expire_flash_timer(sector);
    erase_busy = sector->flash.busy;
    sector_erase_timer = tilem_z80_get_timer_clocks(
        sector, TILEM_TIMER_FLASH_DELAY
    );
    erase_busy_read1 = tilem_flash_read_byte(sector, TARGET);
    erase_busy_read2 = tilem_flash_read_byte(sector, TARGET);
    expire_flash_timer(sector);
    sector_final_busy = sector->flash.busy;
    sector_final_read = tilem_flash_read_byte(sector, TARGET);

    chip_default = new_flash_calc(0x00, 0);
    write_chip_erase(chip_default);
    chip_default_non_ff = count_non_ff(
        chip_default->mem, chip_default->hw.romsize
    );

    chip_override = new_flash_calc(0x00, 1);
    write_chip_erase(chip_override);
    chip_override_non_ff = count_non_ff(
        chip_override->mem, chip_override->hw.romsize
    );

    printf(
        "mode=tilem-flash-probe flash_size=0x%X "
        "sector_count=%d locked_state=%u locked_byte=0x%02X "
        "autoselect_state=%u autoselect_byte=0x%02X "
        "partial_state_before_reset=%d partial_reset_state=%u "
        "cfi_state=%u cfi_byte=0x%02X "
        "suspend_window_state=%d suspend_state=%u "
        "resume_state=%u suspend_changed=%zu "
        "fast_entry_state=%d fast_first_select_state=%d "
        "fast_first_stored=0x%02X fast_after_first_state=%d "
        "fast_second_select_state=%d fast_second_stored=0x%02X "
        "fast_after_second_state=%d fast_exit_select_state=%d "
        "fast_exit_state=%u legal_state=%d legal_busy=%d "
        "legal_timer=%d legal_stored=0x%02X "
        "legal_reads=%02X,%02X legal_final_busy=%d "
        "legal_final_read=0x%02X illegal_initial_state=%d "
        "illegal_initial_busy=%d illegal_timer=%d "
        "illegal_stored=0x%02X illegal_busy_reads=%02X,%02X "
        "illegal_error_state=%d illegal_error_reads=%02X,%02X "
        "illegal_reset_state=%d illegal_final_read=0x%02X "
        "sector_start=0x%X sector_size=0x%X "
        "sector_state=%d sector_busy=%d sector_wait_timer=%d "
        "sector_progaddr=0x%X sector_erased=%zu "
        "sector_changed=%zu sector_outside_changed=%zu "
        "erase_wait_reads=%02X,%02X erase_busy=%u "
        "sector_erase_timer=%d erase_busy_reads=%02X,%02X "
        "sector_final_busy=%d sector_final_read=0x%02X "
        "chip_default_non_ff=%zu chip_default_changed=%zu "
        "chip_default_b_byte=0x%02X chip_default_boot_byte=0x%02X "
        "chip_default_state=%u chip_default_busy=%u "
        "chip_default_timer=%d chip_default_progaddr=0x%X "
        "chip_override_non_ff=%zu chip_override_changed=%zu "
        "chip_override_boot_byte=0x%02X chip_override_state=%u "
        "chip_override_busy=%u chip_override_timer=%d "
        "chip_override_progaddr=0x%X\n",
        locked->hw.romsize,
        initial_sector_count,
        locked->flash.state,
        locked->mem[TARGET],
        autoselect->flash.state,
        autoselect->mem[TARGET],
        partial_state_before_reset,
        partial->flash.state,
        cfi->flash.state,
        cfi->mem[TARGET],
        suspend_window_state,
        suspend_state,
        resume_state,
        suspend->hw.romsize - count_non_ff(suspend->mem, suspend->hw.romsize),
        fast_entry_state,
        fast_first_select_state,
        fast->mem[TARGET],
        fast_after_first_state,
        fast_second_select_state,
        fast->mem[TARGET + 1],
        fast_after_second_state,
        fast_exit_select_state,
        fast->flash.state,
        legal_state,
        legal_busy,
        legal_timer,
        legal->mem[TARGET],
        legal_read1,
        legal_read2,
        legal_final_busy,
        legal_final_read,
        illegal_initial_state,
        illegal_initial_busy,
        illegal_timer,
        illegal->mem[TARGET],
        illegal_busy_read1,
        illegal_busy_read2,
        illegal_error_state,
        illegal_error_read1,
        illegal_error_read2,
        illegal_reset_state,
        illegal_final_read,
        SECTOR_START,
        SECTOR_SIZE,
        sector_state,
        sector_busy,
        sector_wait_timer,
        sector_progaddr,
        sector_erased,
        sector_changed,
        sector_outside_changed,
        erase_wait_read1,
        erase_wait_read2,
        erase_busy,
        sector_erase_timer,
        erase_busy_read1,
        erase_busy_read2,
        sector_final_busy,
        sector_final_read,
        chip_default_non_ff,
        chip_default->hw.romsize - chip_default_non_ff,
        chip_default->mem[0x0B0000],
        chip_default->mem[0x0FFFFF],
        chip_default->flash.state,
        chip_default->flash.busy,
        tilem_z80_get_timer_clocks(chip_default, TILEM_TIMER_FLASH_DELAY),
        chip_default->flash.progaddr,
        chip_override_non_ff,
        chip_override->hw.romsize - chip_override_non_ff,
        chip_override->mem[0x0FFFFF],
        chip_override->flash.state,
        chip_override->flash.busy,
        tilem_z80_get_timer_clocks(chip_override, TILEM_TIMER_FLASH_DELAY),
        chip_override->flash.progaddr
    );

    free(sector_before);
    tilem_calc_free(chip_override);
    tilem_calc_free(chip_default);
    tilem_calc_free(sector);
    tilem_calc_free(illegal);
    tilem_calc_free(legal);
    tilem_calc_free(fast);
    tilem_calc_free(suspend);
    tilem_calc_free(cfi);
    tilem_calc_free(partial);
    tilem_calc_free(autoselect);
    tilem_calc_free(locked);
    return 0;
}
