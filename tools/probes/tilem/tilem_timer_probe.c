/* Direct-core programmable-timer and RTC probe for pinned TilEm 2.1. */

#include <stdio.h>
#include <string.h>
#include <time.h>

#include <tilem.h>
#include <z80.h>
#include <x4/x4.h>

#include "tilem_probe_support.h"

static time_t fake_time_value;

time_t time(time_t *result) {
    if (result != NULL) {
        *result = fake_time_value;
    }
    return fake_time_value;
}

static byte input(TilemCalc *calc, byte port) {
    return calc->hw.z80_in(calc, port);
}

static void output(TilemCalc *calc, byte port, byte value) {
    calc->hw.z80_out(calc, port, value);
}

static dword read_word(TilemCalc *calc, byte first_port) {
    dword value = 0;
    int index;
    for (index = 3; index >= 0; --index) {
        value = (value << 8) | input(calc, first_port + index);
    }
    return value;
}

static void write_word(TilemCalc *calc, byte first_port, dword value) {
    int index;
    for (index = 0; index < 4; ++index) {
        output(calc, first_port + index, (value >> (index * 8)) & 0xFF);
    }
}

static TilemCalc *timer_case(byte source, byte mode, byte counter) {
    TilemCalc *calc = tilem_probe_new_calc();
    output(calc, 0x30, source);
    output(calc, 0x31, mode);
    output(calc, 0x32, counter);
    return calc;
}

static void expiry_case(
    byte mode, byte counter, int expiries, unsigned int *values
) {
    TilemCalc *calc = timer_case(0x80, mode, counter);
    int index;
    calc->z80.interrupts = 0;
    for (index = 0; index < expiries; ++index) {
        tilem_user_timer_expired(calc, TILEM_DWORD_TO_PTR(0));
    }
    values[0] = calc->usertimers[0].status;
    values[1] = input(calc, 0x31);
    values[2] = input(calc, 0x04);
    values[3] = calc->z80.interrupts;
    values[4] = calc->z80.timers[TILEM_TIMER_USER1].period;
    tilem_calc_free(calc);
}

int main(int argc, char **argv) {
    static const byte crystal_sources[] = {
        0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47
    };
    static const byte cpu_sources[] = {
        0x80, 0x81, 0x82, 0x84, 0x88, 0x90, 0xA0
    };
    static const byte off_sources[] = {0x00, 0x01, 0x3F};
    static const byte port2f_values[] = {0x00, 0x4A, 0xFF};
    TilemCalc *calc;
    unsigned int reset[15];
    int crystal_us[8], crystal_count[8], cpu_clocks[7];
    unsigned int off_running[3], off_count[3], mode3_clocks[3];
    unsigned int mode_mask[4], expiry[25], acknowledged[4];
    unsigned int restarted[5], mapping_status[3], mapping_interrupts[3];
    unsigned int source_stop[5];
    dword rtc[13];
    int index;

    if (argc != 2 || strcmp(argv[1], "--timer-probe") != 0) {
        fprintf(stderr, "usage: %s --timer-probe\n", argv[0]);
        return 2;
    }

    fake_time_value = 1000000;
    calc = tilem_probe_new_calc();
    for (index = 0; index < 9; ++index) {
        reset[index] = input(calc, 0x30 + index);
    }
    reset[9] = input(calc, 0x04);
    reset[10] = input(calc, 0x40);
    reset[11] = read_word(calc, 0x41);
    reset[12] = read_word(calc, 0x45);
    reset[13] = calc->hwregs[CLOCK_INPUT];
    reset[14] = calc->hwregs[CLOCK_DIFF];
    tilem_calc_free(calc);

    for (index = 0; index < 8; ++index) {
        calc = timer_case(crystal_sources[index], 0, 1);
        crystal_us[index] = tilem_z80_get_timer_microseconds(
            calc, TILEM_TIMER_USER1
        );
        crystal_count[index] = input(calc, 0x32);
        tilem_calc_free(calc);
    }

    for (index = 0; index < 7; ++index) {
        calc = timer_case(cpu_sources[index], 0, 1);
        cpu_clocks[index] = tilem_z80_get_timer_clocks(
            calc, TILEM_TIMER_USER1
        );
        tilem_calc_free(calc);
    }

    for (index = 0; index < 3; ++index) {
        calc = timer_case(off_sources[index], 0, 5);
        off_running[index] = tilem_z80_timer_running(
            calc, TILEM_TIMER_USER1
        );
        off_count[index] = input(calc, 0x32);
        tilem_calc_free(calc);

        calc = tilem_probe_new_calc();
        output(calc, 0x2F, port2f_values[index]);
        output(calc, 0x30, 0xC0);
        output(calc, 0x31, 0);
        output(calc, 0x32, 1);
        mode3_clocks[index] = tilem_z80_get_timer_clocks(
            calc, TILEM_TIMER_USER1
        );
        tilem_calc_free(calc);
    }

    calc = tilem_probe_new_calc();
    output(calc, 0x03, 0x00);
    output(calc, 0x31, 0xFF);
    mode_mask[0] = calc->usertimers[0].status;
    mode_mask[1] = input(calc, 0x31);
    output(calc, 0x31, 0xFC);
    mode_mask[2] = calc->usertimers[0].status;
    mode_mask[3] = input(calc, 0x31);
    tilem_calc_free(calc);

    expiry_case(0x02, 0, 1, &expiry[0]);
    expiry_case(0x00, 1, 1, &expiry[5]);
    expiry_case(0x00, 1, 2, &expiry[10]);
    expiry_case(0x02, 1, 1, &expiry[15]);
    expiry_case(0x03, 1, 2, &expiry[20]);

    calc = timer_case(0x80, 0x02, 1);
    tilem_user_timer_expired(calc, TILEM_DWORD_TO_PTR(0));
    output(calc, 0x31, 0x02);
    acknowledged[0] = calc->usertimers[0].status;
    acknowledged[1] = input(calc, 0x31);
    acknowledged[2] = input(calc, 0x04);
    acknowledged[3] = calc->z80.interrupts;
    tilem_calc_free(calc);

    calc = timer_case(0x80, 0x00, 1);
    tilem_user_timer_expired(calc, TILEM_DWORD_TO_PTR(0));
    output(calc, 0x32, 1);
    restarted[0] = calc->usertimers[0].status;
    restarted[1] = input(calc, 0x31);
    restarted[2] = input(calc, 0x04);
    restarted[3] = calc->z80.timers[TILEM_TIMER_USER1].period;
    restarted[4] = tilem_z80_timer_running(calc, TILEM_TIMER_USER1);
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    for (index = 0; index < 3; ++index) {
        output(calc, 0x30 + index * 3, 0x80);
        output(calc, 0x31 + index * 3, 0x02);
        output(calc, 0x32 + index * 3, 1);
        tilem_user_timer_expired(calc, TILEM_DWORD_TO_PTR(index));
        mapping_status[index] = input(calc, 0x04);
        mapping_interrupts[index] = calc->z80.interrupts;
    }
    tilem_calc_free(calc);

    calc = timer_case(0x80, 0x03, 10);
    calc->z80.clock += 4;
    source_stop[0] = input(calc, 0x32);
    output(calc, 0x30, 0x81);
    source_stop[1] = input(calc, 0x32);
    source_stop[2] = tilem_z80_timer_running(calc, TILEM_TIMER_USER1);
    source_stop[3] = input(calc, 0x30);
    source_stop[4] = input(calc, 0x31);
    tilem_calc_free(calc);

    fake_time_value = 1000000;
    calc = tilem_probe_new_calc();
    rtc[0] = read_word(calc, 0x45);
    write_word(calc, 0x41, 0x12345678);
    rtc[1] = read_word(calc, 0x41);
    output(calc, 0x40, 0x01);
    output(calc, 0x40, 0x03);
    rtc[2] = read_word(calc, 0x45);
    fake_time_value += 10;
    rtc[3] = read_word(calc, 0x45);
    output(calc, 0x40, 0x00);
    fake_time_value += 90;
    rtc[4] = read_word(calc, 0x45);
    output(calc, 0x40, 0x01);
    fake_time_value += 5;
    rtc[5] = read_word(calc, 0x45);
    output(calc, 0x40, 0x00);
    write_word(calc, 0x41, 0xDEADBEEF);
    output(calc, 0x40, 0x02);
    rtc[6] = read_word(calc, 0x45);
    tilem_calc_reset(calc);
    rtc[7] = read_word(calc, 0x45);
    rtc[8] = input(calc, 0x40);
    rtc[9] = read_word(calc, 0x41);
    tilem_calc_free(calc);

    fake_time_value = 2000000;
    calc = tilem_probe_new_calc();
    write_word(calc, 0x41, 0x00FFFFFF);
    output(calc, 0x40, 0x01);
    output(calc, 0x40, 0x03);
    rtc[10] = read_word(calc, 0x45);
    rtc[11] = ((dword) input(calc, 0x48)) << 24;
    fake_time_value += 1;
    rtc[11] |= ((dword) input(calc, 0x47)) << 16;
    rtc[11] |= ((dword) input(calc, 0x46)) << 8;
    rtc[11] |= input(calc, 0x45);
    rtc[12] = read_word(calc, 0x45);
    tilem_calc_free(calc);

    printf("mode=tilem-timer-probe reset=");
    for (index = 0; index < 15; ++index) {
        printf("%s%X", index ? "," : "", reset[index]);
    }
    printf(" crystal_us=");
    for (index = 0; index < 8; ++index) {
        printf("%s%d", index ? "," : "", crystal_us[index]);
    }
    printf(" crystal_count=");
    for (index = 0; index < 8; ++index) {
        printf("%s%d", index ? "," : "", crystal_count[index]);
    }
    printf(" cpu_clocks=");
    for (index = 0; index < 7; ++index) {
        printf("%s%d", index ? "," : "", cpu_clocks[index]);
    }
    printf(" off_running=%u,%u,%u off_count=%u,%u,%u mode3_clocks=%u,%u,%u ",
        off_running[0], off_running[1], off_running[2],
        off_count[0], off_count[1], off_count[2],
        mode3_clocks[0], mode3_clocks[1], mode3_clocks[2]);
    printf("mode_mask=%X,%X,%X,%X expiry=", mode_mask[0], mode_mask[1],
        mode_mask[2], mode_mask[3]);
    for (index = 0; index < 25; ++index) {
        printf("%s%X", index ? "," : "", expiry[index]);
    }
    printf(" acknowledged=%X,%X,%X,%X restarted=%X,%X,%X,%X,%X ",
        acknowledged[0], acknowledged[1], acknowledged[2], acknowledged[3],
        restarted[0], restarted[1], restarted[2], restarted[3], restarted[4]);
    printf("mapping_status=%X,%X,%X mapping_interrupts=%X,%X,%X ",
        mapping_status[0], mapping_status[1], mapping_status[2],
        mapping_interrupts[0], mapping_interrupts[1], mapping_interrupts[2]);
    printf("source_stop=%X,%X,%X,%X,%X rtc=", source_stop[0], source_stop[1],
        source_stop[2], source_stop[3], source_stop[4]);
    for (index = 0; index < 13; ++index) {
        printf("%s%08X", index ? "," : "", rtc[index]);
    }
    putchar('\n');
    return 0;
}
