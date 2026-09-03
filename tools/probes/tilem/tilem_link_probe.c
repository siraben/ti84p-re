/* Direct-core raw-link and link-assist probe for pinned TilEm 2.1. */

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

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

int main(int argc, char **argv) {
    TilemCalc *calc;
    byte initial[9], aux_stored[4], aux_reads[5], raw_reads[16];
    byte raw_high_write, raw_peer[2], idle[3];
    byte send_drives[8], send[5], receive[4], error[4];
    unsigned int reset[17];
    uint64_t start_clock, clock_delta;
    int index, local, remote;

    if (argc != 2 || strcmp(argv[1], "--link-probe") != 0) {
        fprintf(stderr, "usage: %s --link-probe\n", argv[0]);
        return 2;
    }

    calc = tilem_probe_new_calc();
    initial[0] = input(calc, 0x08);
    initial[1] = input(calc, 0x09);
    initial[2] = input(calc, 0x0A);
    initial[3] = input(calc, 0x0B);
    initial[4] = input(calc, 0x0C);
    initial[5] = input(calc, 0x0D);
    initial[6] = calc->linkport.mode;
    initial[7] = calc->linkport.assistflags;
    initial[8] = calc->z80.interrupts & 0x1E00;
    output(calc, 0x09, 0x91);
    output(calc, 0x0A, 0xA2);
    output(calc, 0x0B, 0xB3);
    output(calc, 0x0C, 0xC4);
    aux_stored[0] = calc->hwregs[PORT9];
    aux_stored[1] = calc->hwregs[PORTA];
    aux_stored[2] = calc->hwregs[PORTB];
    aux_stored[3] = calc->hwregs[PORTC];
    for (index = 0; index < 5; ++index) {
        aux_reads[index] = input(calc, 0x09 + index);
    }
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    index = 0;
    for (local = 0; local < 4; ++local) {
        for (remote = 0; remote < 4; ++remote) {
            tilem_linkport_blacklink_set_lines(calc, remote);
            output(calc, 0x00, local);
            raw_reads[index++] = input(calc, 0x00);
        }
    }
    tilem_linkport_blacklink_set_lines(calc, 0);
    output(calc, 0x00, 0xA6);
    raw_high_write = input(calc, 0x00);
    output(calc, 0x00, 0);
    output(calc, 0x03, 0x10);
    calc->z80.interrupts = 0;
    tilem_linkport_blacklink_set_lines(calc, 1);
    raw_peer[0] = input(calc, 0x00);
    raw_peer[1] = !!(calc->z80.interrupts & TILEM_INTERRUPT_LINK_ACTIVE);
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    output(calc, 0x08, 0x02);
    idle[0] = input(calc, 0x09);
    idle[1] = !!(calc->z80.interrupts & TILEM_INTERRUPT_LINK_IDLE);
    (void) input(calc, 0x0D);
    idle[2] = input(calc, 0x09);
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    start_clock = calc->z80.clock;
    output(calc, 0x08, 0x02);
    calc->z80.interrupts = 0;
    output(calc, 0x0D, 0xA5);
    for (index = 0; index < 8; ++index) {
        send_drives[index] = calc->linkport.lines;
        tilem_linkport_blacklink_set_lines(
            calc, calc->linkport.lines == 1 ? 2 : 1
        );
        tilem_linkport_blacklink_set_lines(calc, 0);
    }
    send[0] = input(calc, 0x09);
    send[1] = !!(calc->z80.interrupts & TILEM_INTERRUPT_LINK_IDLE);
    send[2] = input(calc, 0x0D);
    send[3] = input(calc, 0x09);
    send[4] = calc->linkport.assistflags;
    clock_delta = calc->z80.clock - start_clock;
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    output(calc, 0x08, 0x01);
    calc->z80.interrupts = 0;
    for (index = 0; index < 8; ++index) {
        tilem_linkport_blacklink_set_lines(
            calc, (0xA5 & (1 << index)) ? 2 : 1
        );
        tilem_linkport_blacklink_set_lines(calc, 0);
    }
    receive[0] = input(calc, 0x09);
    receive[1] = !!(calc->z80.interrupts & TILEM_INTERRUPT_LINK_READ);
    receive[2] = input(calc, 0x0A);
    receive[3] = input(calc, 0x09);
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    output(calc, 0x08, 0x04);
    calc->z80.interrupts = 0;
    tilem_linkport_blacklink_set_lines(calc, 3);
    error[1] = !!(calc->z80.interrupts & TILEM_INTERRUPT_LINK_ERROR);
    error[0] = input(calc, 0x09);
    error[2] = input(calc, 0x09);
    error[3] = calc->linkport.assistflags;
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    calc->hwregs[PORT8] = 0x55;
    calc->hwregs[PORT9] = 0x91;
    calc->hwregs[PORTA] = 0xA2;
    calc->hwregs[PORTB] = 0xB3;
    calc->hwregs[PORTC] = 0xC4;
    calc->linkport.lines = 2;
    calc->linkport.extlines = 1;
    calc->linkport.mode = 0x3F;
    calc->linkport.assistflags = 0x1F;
    calc->linkport.assistin = 0x11;
    calc->linkport.assistinbits = 7;
    calc->linkport.assistout = 0x22;
    calc->linkport.assistoutbits = 6;
    calc->linkport.assistlastbyte = 0x33;
    calc->z80.interrupts = 0x1E00;
    tilem_calc_reset(calc);
    reset[0] = calc->hwregs[PORT8];
    reset[1] = calc->hwregs[PORT9];
    reset[2] = calc->hwregs[PORTA];
    reset[3] = calc->hwregs[PORTB];
    reset[4] = calc->hwregs[PORTC];
    reset[5] = calc->linkport.mode;
    reset[6] = calc->linkport.assistflags;
    reset[7] = calc->linkport.assistin;
    reset[8] = calc->linkport.assistinbits;
    reset[9] = calc->linkport.assistout;
    reset[10] = calc->linkport.assistoutbits;
    reset[11] = calc->linkport.assistlastbyte;
    reset[12] = calc->linkport.lines;
    reset[13] = calc->linkport.extlines;
    reset[14] = calc->z80.interrupts & 0x1E00;
    reset[15] = input(calc, 0x00);
    reset[16] = input(calc, 0x09);
    tilem_calc_free(calc);

#define PRINT_VECTOR(name, values, length) do { \
    printf(name "="); \
    for (index = 0; index < length; ++index) \
        printf("%s%X", index ? "," : "", values[index]); \
    putchar(' '); \
} while (0)
    printf("mode=tilem-link-probe ");
    PRINT_VECTOR("initial", initial, 9);
    PRINT_VECTOR("aux_stored", aux_stored, 4);
    PRINT_VECTOR("aux_reads", aux_reads, 5);
    PRINT_VECTOR("raw_reads", raw_reads, 16);
    printf("raw_high_write=%X ", raw_high_write);
    PRINT_VECTOR("raw_peer", raw_peer, 2);
    PRINT_VECTOR("idle", idle, 3);
    PRINT_VECTOR("send_drives", send_drives, 8);
    PRINT_VECTOR("send", send, 5);
    PRINT_VECTOR("receive", receive, 4);
    PRINT_VECTOR("error", error, 4);
    printf("clock_delta=%" PRIu64 " ", clock_delta);
    PRINT_VECTOR("reset", reset, 17);
    putchar('\n');
#undef PRINT_VECTOR
    return 0;
}
