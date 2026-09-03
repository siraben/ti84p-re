/* Direct-core reset and execution-violation probe for pinned TilEm 2.1. */

#include <stdio.h>
#include <string.h>

#include <tilem.h>
#include <z80.h>
#include <x4/x4.h>

#include "tilem_probe_support.h"

static void unused_timer(TilemCalc *calc, void *data) {
    (void) calc;
    (void) data;
}

static int unused_breakpoint(TilemCalc *calc, dword address, void *data) {
    (void) calc;
    (void) address;
    (void) data;
    return 0;
}

static int all_cpu_words_are_ffff(const TilemCalc *calc) {
    return calc->z80.r.af.d == 0xFFFF && calc->z80.r.bc.d == 0xFFFF &&
        calc->z80.r.de.d == 0xFFFF && calc->z80.r.hl.d == 0xFFFF &&
        calc->z80.r.af2.d == 0xFFFF && calc->z80.r.bc2.d == 0xFFFF &&
        calc->z80.r.de2.d == 0xFFFF && calc->z80.r.hl2.d == 0xFFFF &&
        calc->z80.r.ix.d == 0xFFFF && calc->z80.r.iy.d == 0xFFFF &&
        calc->z80.r.ir.d == 0xFFFF && calc->z80.r.sp.d == 0xFFFF &&
        calc->z80.r.wz.d == 0xFFFF && calc->z80.r.wz2.d == 0xFFFF;
}

static int all_keys_are_clear(const TilemCalc *calc) {
    int index;
    for (index = 0; index < 8; ++index) {
        if (calc->keypad.keysdown[index] != 0) {
            return 0;
        }
    }
    return 1;
}

static int all_md5_registers_are_clear(const TilemCalc *calc) {
    unsigned int index;
    for (index = 0; index < 6; ++index) {
        if (calc->md5assist.regs[index] != 0) {
            return 0;
        }
    }
    return 1;
}

static int all_user_timers_are_clear(const TilemCalc *calc) {
    unsigned int index;
    for (index = 0; index < TILEM_MAX_USER_TIMERS; ++index) {
        if (calc->usertimers[index].frequency != 0 ||
            calc->usertimers[index].loopvalue != 0 ||
            calc->usertimers[index].status != 0 ||
            tilem_z80_timer_running((TilemCalc *) calc, TILEM_TIMER_USER1 + index)) {
            return 0;
        }
    }
    return 1;
}

static int reset_ports_match(const TilemCalc *calc) {
    return calc->hwregs[PORT3] == 0x0B && calc->hwregs[PORT4] == 0x07 &&
        calc->hwregs[PORT6] == 0x3F && calc->hwregs[PORT7] == 0x3F &&
        calc->hwregs[PORT8] == 0x80 && calc->hwregs[PORT20] == 0x00 &&
        calc->hwregs[PORT21] == 0x00 && calc->hwregs[PORT22] == 0x08 &&
        calc->hwregs[PORT23] == 0x29 && calc->hwregs[PORT25] == 0x10 &&
        calc->hwregs[PORT26] == 0x20 && calc->hwregs[PORT27] == 0x00 &&
        calc->hwregs[PORT28] == 0x00 && calc->hwregs[PORT29] == 0x14 &&
        calc->hwregs[PORT2A] == 0x27 && calc->hwregs[PORT2B] == 0x2F &&
        calc->hwregs[PORT2C] == 0x3B && calc->hwregs[PORT2D] == 0x01 &&
        calc->hwregs[PORT2E] == 0x44 && calc->hwregs[PORT2F] == 0x4A;
}

static int reset_derived_fields_match(const TilemCalc *calc) {
    return calc->hwregs[FLASH_READ_DELAY] == 0 &&
        calc->hwregs[FLASH_WRITE_DELAY] == 0 &&
        calc->hwregs[FLASH_EXEC_DELAY] == 0 &&
        calc->hwregs[RAM_READ_DELAY] == 0 &&
        calc->hwregs[RAM_WRITE_DELAY] == 0 &&
        calc->hwregs[RAM_EXEC_DELAY] == 0 &&
        calc->hwregs[LCD_PORT_DELAY] == 5 &&
        calc->hwregs[NO_EXEC_RAM_MASK] == 0x7C00 &&
        calc->hwregs[NO_EXEC_RAM_LOWER] == 0x4000 &&
        calc->hwregs[NO_EXEC_RAM_UPPER] == 0x8000 &&
        calc->hwregs[PROTECTSTATE] == 0;
}

static int retained_hwregs_match(const TilemCalc *calc) {
    const int retained[] = {
        PORT5, PORT9, PORTA, PORTB, PORTC, PORTD, PORTE, PORTF,
        CLOCK_MODE, CLOCK_INPUT, CLOCK_DIFF, LCD_WAIT,
    };
    unsigned int index;
    for (index = 0; index < sizeof(retained) / sizeof(retained[0]); ++index) {
        if (calc->hwregs[retained[index]] != 0xDEADBEEF) {
            return 0;
        }
    }
    return 1;
}

int main(int argc, char **argv) {
    TilemCalc *calc;
    TilemCalc *violation;
    int dynamic_timer;
    int dynamic_breakpoint;
    int retained[9];
    int reset_groups[8];
    int index;
    dword violation_stop;

    if (argc != 2 || strcmp(argv[1], "--reset-probe") != 0) {
        fprintf(stderr, "usage: %s --reset-probe\n", argv[0]);
        return 2;
    }

    calc = tilem_probe_new_calc();
    memset(calc->hwregs, 0xEF, calc->hw.nhwregs * sizeof(*calc->hwregs));
    for (index = 0; index < calc->hw.nhwregs; ++index) {
        calc->hwregs[index] = 0xDEADBEEF;
    }

    calc->z80.r.af.d = 0xA1F1;
    calc->z80.r.bc.d = 0xB2C2;
    calc->z80.r.de.d = 0xD3E3;
    calc->z80.r.hl.d = 0xE4F4;
    calc->z80.r.pc.d = 0x4567;
    calc->z80.r.sp.d = 0x89AB;
    calc->z80.r.iff1 = 1;
    calc->z80.r.iff2 = 1;
    calc->z80.r.im = 2;
    calc->z80.interrupts = 0xFFFF;
    calc->z80.halted = 1;
    calc->z80.exception = 0x80;
    calc->z80.clock = 123456;
    calc->z80.lastwrite = 234567;
    calc->z80.lastlcdwrite = 345678;
    calc->z80.emuflags = 0x35;
    dynamic_timer = tilem_z80_add_timer(calc, 4321, 0, 0, unused_timer, NULL);
    dynamic_breakpoint = tilem_z80_add_breakpoint(
        calc, TILEM_BREAK_MEM_READ, 0x1234, 0x1234, 0xFFFF,
        unused_breakpoint, NULL
    );

    calc->mem[0x1234] = 0xA5;
    calc->ram[0x1234] = 0x5A;
    calc->lcdmem[0] = 0xC3;
    calc->lcd.active = 1;
    calc->lcd.contrast = 17;
    calc->lcd.addr = 0x1234;
    calc->lcd.mode = 0;
    calc->lcd.nextbyte = 0xA6;
    calc->lcd.x = 4;
    calc->lcd.y = 5;
    calc->lcd.inc = 6;
    calc->lcd.rowshift = 7;
    calc->lcd.busy = 1;
    calc->lcd.emuflags = 3;

    calc->linkport.lines = 3;
    calc->linkport.extlines = 2;
    calc->linkport.mode = 0x3F;
    calc->linkport.assistflags = 0x1F;
    calc->linkport.assistin = 0x12;
    calc->linkport.assistinbits = 3;
    calc->linkport.assistout = 0x34;
    calc->linkport.assistoutbits = 4;
    calc->linkport.assistlastbyte = 0x56;
    calc->linkport.linkemu = TILEM_LINK_EMULATOR_GRAY;
    calc->linkport.graylinkin = 0x67;
    calc->linkport.graylinkinbits = 5;
    calc->linkport.graylinkout = 0x89;
    calc->linkport.graylinkoutbits = 6;

    calc->keypad.group = 0;
    calc->keypad.onkeydown = 1;
    calc->keypad.onkeyint = 1;
    memset(calc->keypad.keysdown, 0xFF, sizeof(calc->keypad.keysdown));

    calc->flash.unlock = 1;
    calc->flash.state = 6;
    calc->flash.busy = 3;
    calc->flash.progaddr = 0x23456;
    calc->flash.progbyte = 0x9A;
    calc->flash.toggles = 0x44;
    calc->flash.overridegroup = 1;
    calc->flash.emuflags = 1;

    for (index = 0; index < 6; ++index) {
        calc->md5assist.regs[index] = 0x11111111U * (index + 1);
    }
    calc->md5assist.shift = 13;
    calc->md5assist.mode = 3;
    for (index = 0; index < TILEM_MAX_USER_TIMERS; ++index) {
        calc->usertimers[index].frequency = 0x41 + index;
        calc->usertimers[index].loopvalue = 0x20 + index;
        calc->usertimers[index].status = 0x103 + index;
        tilem_z80_set_timer(
            calc, TILEM_TIMER_USER1 + index, 100 + index, 0, 0
        );
    }
    calc->battery = 42;
    calc->poweronhalt = 0;

    tilem_calc_reset(calc);

    retained[0] = calc->mem[0x1234] == 0xA5 && calc->ram[0x1234] == 0x5A;
    retained[1] = calc->lcdmem[0] == 0xC3 && calc->lcd.emuflags == 3;
    retained[2] = calc->flash.progaddr == 0x23456 &&
        calc->flash.progbyte == 0x9A && calc->flash.toggles == 0x44 &&
        calc->flash.overridegroup == 1 && calc->flash.emuflags == 1;
    retained[3] = calc->linkport.extlines == 2 &&
        calc->linkport.linkemu == TILEM_LINK_EMULATOR_GRAY &&
        calc->linkport.graylinkin == 0x67 &&
        calc->linkport.graylinkinbits == 5 &&
        calc->linkport.graylinkout == 0x89 &&
        calc->linkport.graylinkoutbits == 6;
    retained[4] = retained_hwregs_match(calc);
    retained[5] = calc->battery == 42 && calc->poweronhalt == 0;
    retained[6] = calc->z80.clock == 123456 &&
        calc->z80.lastwrite == 234567 && calc->z80.lastlcdwrite == 345678 &&
        calc->z80.emuflags == 0x35 && calc->z80.exception == 0x80;
    retained[7] = tilem_z80_timer_running(calc, dynamic_timer) &&
        tilem_z80_get_timer_clocks(calc, dynamic_timer) == 4321;
    retained[8] = tilem_z80_get_breakpoint_type(calc, dynamic_breakpoint) ==
        TILEM_BREAK_MEM_READ &&
        tilem_z80_get_breakpoint_address_start(
            calc, dynamic_breakpoint
        ) == 0x1234 &&
        tilem_z80_get_breakpoint_address_end(calc, dynamic_breakpoint) == 0x1234;

    reset_groups[0] = all_cpu_words_are_ffff(calc) &&
        calc->z80.r.pc.d == 0x8000 && calc->z80.r.r7 == 0x80 &&
        calc->z80.r.iff1 == 0 && calc->z80.r.iff2 == 0 &&
        calc->z80.r.im == 0 && calc->z80.interrupts == 0 && !calc->z80.halted;
    reset_groups[1] = calc->lcd.active == 0 && calc->lcd.contrast == 32 &&
        calc->lcd.addr == 0 && calc->lcd.mode == 1 &&
        calc->lcd.nextbyte == 0 && calc->lcd.x == 0 && calc->lcd.y == 0 &&
        calc->lcd.inc == 7 && calc->lcd.rowshift == 0 && !calc->lcd.busy &&
        calc->lcd.rowstride == 16;
    reset_groups[2] = calc->linkport.lines == 0 && calc->linkport.mode == 0 &&
        calc->linkport.assistflags == 0 && calc->linkport.assistin == 0 &&
        calc->linkport.assistinbits == 0 && calc->linkport.assistout == 0 &&
        calc->linkport.assistoutbits == 0 && calc->linkport.assistlastbyte == 0;
    reset_groups[3] = calc->keypad.group == 0xFF &&
        !calc->keypad.onkeydown && !calc->keypad.onkeyint &&
        all_keys_are_clear(calc);
    reset_groups[4] = !calc->flash.unlock && calc->flash.state == 0 &&
        !calc->flash.busy;
    reset_groups[5] = all_md5_registers_are_clear(calc) &&
        calc->md5assist.shift == 0 && calc->md5assist.mode == 0;
    reset_groups[6] = all_user_timers_are_clear(calc);
    reset_groups[7] = reset_ports_match(calc) && reset_derived_fields_match(calc);

    violation = tilem_probe_new_calc();
    memset(
        violation->mem, 0,
        violation->hw.romsize + violation->hw.ramsize + violation->hw.lcdmemsize
    );
    violation->mem[0x20000] = 0x32; /* LD (0x8000),A */
    violation->mem[0x20001] = 0x00;
    violation->mem[0x20002] = 0x80;
    violation->mem[0xFC000] = 0x76; /* HALT if reset does not stop execution */
    violation->mempagemap[1] = 0x08;
    violation->mempagemap[2] = 0x40;
    violation->z80.r.pc.d = 0x4000;
    violation->z80.r.af.b.h = 0x5A;
    violation->z80.emuflags = TILEM_Z80_BREAK_EXCEPTIONS;
    violation_stop = tilem_z80_run(violation, 1000, NULL);

    printf(
        "mode=tilem-reset-probe reset_pc=0x%04X reset_sp=0x%04X "
        "reset_cpu_words_ffff=%d reset_r7=0x%02X reset_iff1=%d "
        "reset_iff2=%d reset_im=%d reset_interrupts=0x%X reset_halted=%d "
        "reset_pages=%02X,%02X,%02X,%02X reset_speed=%d "
        "reset_ports_match=%d reset_derived_match=%d "
        "reset_groups=%d,%d,%d,%d,%d,%d,%d,%d "
        "retained=%d,%d,%d,%d,%d,%d,%d,%d,%d "
        "reset_flash=%u,%u,%u reset_lcd=%u,%u,%u,%u,%u,%d,%d,%u,%d,%u,%d "
        "reset_link=%u,%u,%u,%u,%u,%u,%u,%u "
        "reset_keypad=%u,%u,%u,%d reset_md5=%d,%u,%u "
        "reset_user_timers=%d retained_clock=%u retained_dynamic_timer=%d "
        "violation_stop=0x%X violation_exception=0x%X "
        "violation_pc=0x%04X violation_af=0x%04X violation_sp=0x%04X "
        "violation_pages=%02X,%02X,%02X,%02X violation_ram_marker=0x%02X "
        "violation_flash=%u,%u,%u\n",
        calc->z80.r.pc.w.l, calc->z80.r.sp.w.l,
        all_cpu_words_are_ffff(calc), calc->z80.r.r7,
        calc->z80.r.iff1, calc->z80.r.iff2, calc->z80.r.im,
        calc->z80.interrupts, calc->z80.halted,
        calc->mempagemap[0], calc->mempagemap[1],
        calc->mempagemap[2], calc->mempagemap[3], calc->z80.clockspeed,
        reset_ports_match(calc), reset_derived_fields_match(calc),
        reset_groups[0], reset_groups[1], reset_groups[2], reset_groups[3],
        reset_groups[4], reset_groups[5], reset_groups[6], reset_groups[7],
        retained[0], retained[1], retained[2], retained[3], retained[4],
        retained[5], retained[6], retained[7], retained[8],
        calc->flash.unlock, calc->flash.state, calc->flash.busy,
        calc->lcd.active, calc->lcd.contrast, calc->lcd.addr, calc->lcd.mode,
        calc->lcd.nextbyte, calc->lcd.x, calc->lcd.y, calc->lcd.inc,
        calc->lcd.rowshift, calc->lcd.busy, calc->lcd.rowstride,
        calc->linkport.lines, calc->linkport.mode, calc->linkport.assistflags,
        calc->linkport.assistin, calc->linkport.assistinbits,
        calc->linkport.assistout, calc->linkport.assistoutbits,
        calc->linkport.assistlastbyte,
        calc->keypad.group, calc->keypad.onkeydown, calc->keypad.onkeyint,
        all_keys_are_clear(calc), all_md5_registers_are_clear(calc),
        calc->md5assist.shift, calc->md5assist.mode,
        all_user_timers_are_clear(calc), calc->z80.clock,
        tilem_z80_get_timer_clocks(calc, dynamic_timer),
        violation_stop, violation->z80.exception,
        violation->z80.r.pc.w.l, violation->z80.r.af.w.l,
        violation->z80.r.sp.w.l,
        violation->mempagemap[0], violation->mempagemap[1],
        violation->mempagemap[2], violation->mempagemap[3],
        violation->ram[0],
        violation->flash.unlock, violation->flash.state, violation->flash.busy
    );

    tilem_calc_free(violation);
    tilem_calc_free(calc);
    return 0;
}
