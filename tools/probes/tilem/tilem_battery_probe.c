/* Direct-core battery-comparator probe for pinned TilEm 2.1. */

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

static unsigned int level_from_mask(unsigned int mask) {
    if (!(mask & 0x01)) {
        return 0;
    }
    if (mask & 0x08) {
        return 4;
    }
    if (mask & 0x04) {
        return 3;
    }
    if (mask & 0x02) {
        return 2;
    }
    return 1;
}

int main(int argc, char **argv) {
    static const byte selectors[] = {0x06, 0x46, 0x86, 0xC6};
    TilemCalc *calc;
    unsigned int masks[16], levels[16];
    unsigned int reset_battery, reset_port4, reset_status;
    int voltage, selector, index;

    if (argc != 2 || strcmp(argv[1], "--battery-probe") != 0) {
        fprintf(stderr, "usage: %s --battery-probe\n", argv[0]);
        return 2;
    }

    calc = tilem_probe_new_calc();
    reset_battery = calc->battery;
    reset_port4 = calc->hwregs[PORT4];
    reset_status = input(calc, 0x02);
    for (voltage = 30; voltage <= 45; ++voltage) {
        index = voltage - 30;
        calc->battery = voltage;
        masks[index] = 0;
        for (selector = 0; selector < 4; ++selector) {
            output(calc, 0x04, selectors[selector]);
            if (input(calc, 0x02) & 0x01) {
                masks[index] |= 1U << selector;
            }
        }
        levels[index] = level_from_mask(masks[index]);
    }
    tilem_calc_free(calc);

    printf(
        "mode=tilem-battery-probe reset_battery=%u reset_port4=%02X "
        "reset_status=%02X voltages=",
        reset_battery, reset_port4, reset_status
    );
    for (index = 0; index < 16; ++index) {
        printf("%s%d", index ? "," : "", index + 30);
    }
    printf(" masks=");
    for (index = 0; index < 16; ++index) {
        printf("%s%X", index ? "," : "", masks[index]);
    }
    printf(" levels=");
    for (index = 0; index < 16; ++index) {
        printf("%s%u", index ? "," : "", levels[index]);
    }
    putchar('\n');
    return 0;
}
