/* Direct-core legacy-interrupt probe for pinned TilEm 2.1. */

#include <stdio.h>
#include <string.h>

#include <scancodes.h>
#include <tilem.h>
#include <z80.h>
#include <x4/x4.h>

#include "tilem_probe_support.h"

static byte input(TilemCalc *calc, byte port) {
    return calc->hw.z80_in(calc, port);
}

static void output(TilemCalc *calc, byte port, byte value) {
    calc->hw.z80_out(calc, port, value);
}

static int user_no_halt(const TilemCalc *calc) {
    return !!(calc->usertimers[0].status & TILEM_USER_TIMER_NO_HALT_INT);
}

static int user_no_halt_agrees(const TilemCalc *calc) {
    unsigned int first = calc->usertimers[0].status & TILEM_USER_TIMER_NO_HALT_INT;
    return !!(calc->usertimers[1].status & TILEM_USER_TIMER_NO_HALT_INT) == !!first &&
        !!(calc->usertimers[2].status & TILEM_USER_TIMER_NO_HALT_INT) == !!first;
}

static void seed_pending(TilemCalc *calc) {
    calc->z80.interrupts = TILEM_INTERRUPT_ON_KEY | TILEM_INTERRUPT_TIMER1 |
        TILEM_INTERRUPT_TIMER2 | TILEM_INTERRUPT_USER_TIMER1 |
        TILEM_INTERRUPT_USER_TIMER2 | TILEM_INTERRUPT_USER_TIMER3 |
        TILEM_INTERRUPT_LINK_ACTIVE;
    calc->usertimers[0].status |= TILEM_USER_TIMER_FINISHED;
    calc->usertimers[1].status |= TILEM_USER_TIMER_FINISHED;
    calc->usertimers[2].status |= TILEM_USER_TIMER_FINISHED;
}

static void programmable_case(
    int mask, int halted, unsigned int *status, unsigned int *interrupts,
    unsigned int *port04
) {
    TilemCalc *calc = tilem_probe_new_calc();
    output(calc, 0x03, mask);
    tilem_user_timer_set_mode(calc, 0, TILEM_USER_TIMER_INTERRUPT);
    calc->usertimers[0].loopvalue = 1;
    calc->z80.halted = halted;
    calc->z80.interrupts = 0;
    tilem_user_timer_expired(calc, TILEM_DWORD_TO_PTR(0));
    *status = calc->usertimers[0].status;
    *interrupts = calc->z80.interrupts;
    *port04 = input(calc, 0x04);
    tilem_calc_free(calc);
}

int main(int argc, char **argv) {
    static const byte masks[] = {0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0xFF};
    static const byte timer_configs[] = {0x00, 0x02, 0x04, 0x06};
    TilemCalc *calc;
    byte mask_readback[7], mask_on[7], mask_power[7], mask_link[7];
    byte mask_no_halt[7], ack03_status[7], ack02_status[7];
    byte ack03_other[7], ack02_other[7];
    byte on_status[9], timer_status[7], link_status[5];
    int timer_before[3], timer_after[3], timer_periods[12];
    unsigned int programmable[9];
    unsigned int initial_reset[8], reset[8], reset_synced[8];
    int mask_agree = 1;
    int index, timer;

    if (argc != 2 || strcmp(argv[1], "--interrupt-probe") != 0) {
        fprintf(stderr, "usage: %s --interrupt-probe\n", argv[0]);
        return 2;
    }

    calc = tilem_probe_new_calc();
    initial_reset[0] = input(calc, 0x03);
    initial_reset[1] = input(calc, 0x04);
    initial_reset[2] = calc->keypad.onkeyint;
    initial_reset[3] = calc->poweronhalt;
    initial_reset[4] = !!(calc->linkport.mode & TILEM_LINK_MODE_INT_ON_ACTIVE);
    initial_reset[5] = !!(calc->usertimers[0].status & TILEM_USER_TIMER_NO_HALT_INT);
    initial_reset[6] = !!(calc->usertimers[1].status & TILEM_USER_TIMER_NO_HALT_INT);
    initial_reset[7] = !!(calc->usertimers[2].status & TILEM_USER_TIMER_NO_HALT_INT);
    tilem_calc_free(calc);

    for (index = 0; index < 7; ++index) {
        calc = tilem_probe_new_calc();
        output(calc, 0x03, masks[index]);
        mask_readback[index] = input(calc, 0x03);
        mask_on[index] = calc->keypad.onkeyint;
        mask_power[index] = calc->poweronhalt;
        mask_link[index] = !!(
            calc->linkport.mode & TILEM_LINK_MODE_INT_ON_ACTIVE
        );
        mask_no_halt[index] = user_no_halt(calc);
        mask_agree &= user_no_halt_agrees(calc);
        tilem_calc_free(calc);

        calc = tilem_probe_new_calc();
        seed_pending(calc);
        output(calc, 0x03, masks[index]);
        ack03_status[index] = input(calc, 0x04);
        ack03_other[index] = calc->z80.interrupts & 0x38;
        tilem_calc_free(calc);

        calc = tilem_probe_new_calc();
        seed_pending(calc);
        output(calc, 0x02, masks[index]);
        ack02_status[index] = input(calc, 0x04);
        ack02_other[index] = calc->z80.interrupts & 0x38;
        tilem_calc_free(calc);
    }

    calc = tilem_probe_new_calc();
    tilem_keypad_press_key(calc, TILEM_KEY_ON);
    on_status[0] = input(calc, 0x04);
    output(calc, 0x03, 0x01);
    on_status[1] = input(calc, 0x04);
    tilem_keypad_release_key(calc, TILEM_KEY_ON);
    on_status[2] = input(calc, 0x04);
    output(calc, 0x02, 0xFE);
    on_status[3] = input(calc, 0x04);
    tilem_keypad_press_key(calc, TILEM_KEY_ON);
    on_status[4] = input(calc, 0x04);
    output(calc, 0x02, 0xFE);
    on_status[5] = input(calc, 0x04);
    tilem_keypad_release_key(calc, TILEM_KEY_ON);
    on_status[6] = input(calc, 0x04);
    output(calc, 0x03, 0x00);
    on_status[7] = input(calc, 0x04);
    tilem_keypad_press_key(calc, TILEM_KEY_ON);
    on_status[8] = input(calc, 0x04);
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    output(calc, 0x03, 0x00);
    calc->hw.z80_ptimer(calc, TIMER_INT1);
    timer_status[0] = input(calc, 0x04);
    calc->hw.z80_ptimer(calc, TIMER_INT2A);
    timer_status[1] = input(calc, 0x04);
    calc->hw.z80_ptimer(calc, TIMER_INT2B);
    timer_status[2] = input(calc, 0x04);
    output(calc, 0x03, 0x06);
    calc->hw.z80_ptimer(calc, TIMER_INT1);
    timer_status[3] = input(calc, 0x04);
    output(calc, 0x02, 0xFD);
    calc->hw.z80_ptimer(calc, TIMER_INT2A);
    timer_status[4] = input(calc, 0x04);
    output(calc, 0x02, 0xFB);
    calc->hw.z80_ptimer(calc, TIMER_INT2B);
    timer_status[5] = input(calc, 0x04);
    calc->hw.z80_ptimer(calc, TIMER_INT1);
    timer_status[6] = input(calc, 0x04);
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    timer_before[0] = tilem_z80_get_timer_microseconds(calc, TIMER_INT1);
    timer_before[1] = tilem_z80_get_timer_microseconds(calc, TIMER_INT2A);
    timer_before[2] = tilem_z80_get_timer_microseconds(calc, TIMER_INT2B);
    for (index = 0; index < 4; ++index) {
        output(calc, 0x04, timer_configs[index]);
        for (timer = 0; timer < 3; ++timer) {
            timer_periods[index * 3 + timer] =
                calc->z80.timers[TIMER_INT1 + timer].period;
        }
    }
    timer_after[0] = tilem_z80_get_timer_microseconds(calc, TIMER_INT1);
    timer_after[1] = tilem_z80_get_timer_microseconds(calc, TIMER_INT2A);
    timer_after[2] = tilem_z80_get_timer_microseconds(calc, TIMER_INT2B);
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    output(calc, 0x03, 0x10);
    tilem_linkport_blacklink_set_lines(calc, 1);
    link_status[0] = input(calc, 0x04);
    output(calc, 0x02, 0xEF);
    link_status[1] = input(calc, 0x04);
    tilem_linkport_blacklink_set_lines(calc, 0);
    link_status[2] = input(calc, 0x04);
    output(calc, 0x03, 0x00);
    link_status[3] = input(calc, 0x04);
    tilem_linkport_blacklink_set_lines(calc, 1);
    link_status[4] = input(calc, 0x04);
    tilem_calc_free(calc);

    programmable_case(0x00, 1, &programmable[0], &programmable[1], &programmable[2]);
    programmable_case(0x02, 1, &programmable[3], &programmable[4], &programmable[5]);
    programmable_case(0x00, 0, &programmable[6], &programmable[7], &programmable[8]);

    calc = tilem_probe_new_calc();
    output(calc, 0x03, 0x00);
    calc->z80.interrupts = 0xFFFF;
    calc->keypad.onkeydown = 1;
    calc->keypad.onkeyint = 1;
    calc->poweronhalt = 0;
    calc->linkport.mode |= TILEM_LINK_MODE_INT_ON_ACTIVE;
    for (index = 0; index < 3; ++index) {
        calc->usertimers[index].status = TILEM_USER_TIMER_NO_HALT_INT |
            TILEM_USER_TIMER_FINISHED;
    }
    tilem_calc_reset(calc);
    reset[0] = input(calc, 0x03);
    reset[1] = input(calc, 0x04);
    reset[2] = calc->keypad.onkeyint;
    reset[3] = calc->poweronhalt;
    reset[4] = !!(calc->linkport.mode & TILEM_LINK_MODE_INT_ON_ACTIVE);
    reset[5] = !!(calc->usertimers[0].status & TILEM_USER_TIMER_NO_HALT_INT);
    reset[6] = !!(calc->usertimers[1].status & TILEM_USER_TIMER_NO_HALT_INT);
    reset[7] = !!(calc->usertimers[2].status & TILEM_USER_TIMER_NO_HALT_INT);
    output(calc, 0x03, 0x0B);
    reset_synced[0] = input(calc, 0x03);
    reset_synced[1] = input(calc, 0x04);
    reset_synced[2] = calc->keypad.onkeyint;
    reset_synced[3] = calc->poweronhalt;
    reset_synced[4] = !!(calc->linkport.mode & TILEM_LINK_MODE_INT_ON_ACTIVE);
    reset_synced[5] = !!(calc->usertimers[0].status & TILEM_USER_TIMER_NO_HALT_INT);
    reset_synced[6] = !!(calc->usertimers[1].status & TILEM_USER_TIMER_NO_HALT_INT);
    reset_synced[7] = !!(calc->usertimers[2].status & TILEM_USER_TIMER_NO_HALT_INT);
    tilem_calc_free(calc);

    printf("mode=tilem-interrupt-probe initial_reset=%02X,%02X,%u,%u,%u,%u,%u,%u ",
        initial_reset[0], initial_reset[1], initial_reset[2], initial_reset[3],
        initial_reset[4], initial_reset[5], initial_reset[6], initial_reset[7]);
    printf("reset=%02X,%02X,%u,%u,%u,%u,%u,%u ",
        reset[0], reset[1], reset[2], reset[3], reset[4], reset[5], reset[6], reset[7]);
    printf("reset_synced=%02X,%02X,%u,%u,%u,%u,%u,%u ",
        reset_synced[0], reset_synced[1], reset_synced[2], reset_synced[3],
        reset_synced[4], reset_synced[5], reset_synced[6], reset_synced[7]);
#define PRINT_HEX7(name, values) printf(name "=%02X,%02X,%02X,%02X,%02X,%02X,%02X ", values[0], values[1], values[2], values[3], values[4], values[5], values[6])
    PRINT_HEX7("mask_readback", mask_readback);
    PRINT_HEX7("mask_on", mask_on);
    PRINT_HEX7("mask_power", mask_power);
    PRINT_HEX7("mask_link", mask_link);
    PRINT_HEX7("mask_no_halt", mask_no_halt);
    printf("mask_agree=%d ", mask_agree);
    PRINT_HEX7("ack03_status", ack03_status);
    PRINT_HEX7("ack03_other", ack03_other);
    PRINT_HEX7("ack02_status", ack02_status);
    PRINT_HEX7("ack02_other", ack02_other);
#undef PRINT_HEX7
    printf("on_status=%02X,%02X,%02X,%02X,%02X,%02X,%02X,%02X,%02X ",
        on_status[0], on_status[1], on_status[2], on_status[3], on_status[4],
        on_status[5], on_status[6], on_status[7], on_status[8]);
    printf("timer_status=%02X,%02X,%02X,%02X,%02X,%02X,%02X ",
        timer_status[0], timer_status[1], timer_status[2], timer_status[3],
        timer_status[4], timer_status[5], timer_status[6]);
    printf("timer_before=%d,%d,%d timer_after=%d,%d,%d ",
        timer_before[0], timer_before[1], timer_before[2],
        timer_after[0], timer_after[1], timer_after[2]);
    printf("timer_periods=%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d ",
        timer_periods[0], timer_periods[1], timer_periods[2],
        timer_periods[3], timer_periods[4], timer_periods[5],
        timer_periods[6], timer_periods[7], timer_periods[8],
        timer_periods[9], timer_periods[10], timer_periods[11]);
    printf("link_status=%02X,%02X,%02X,%02X,%02X ",
        link_status[0], link_status[1], link_status[2], link_status[3], link_status[4]);
    printf("programmable=%X,%X,%X,%X,%X,%X,%X,%X,%X\n",
        programmable[0], programmable[1], programmable[2],
        programmable[3], programmable[4], programmable[5],
        programmable[6], programmable[7], programmable[8]);
    return 0;
}
