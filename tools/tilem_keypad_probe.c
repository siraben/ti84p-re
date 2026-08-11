/* Direct-core keypad and ON-edge probe for pinned TilEm 2.1. */

#include <stdio.h>
#include <string.h>

#include <scancodes.h>
#include <tilem.h>
#include <z80.h>

#include "tilem_probe_support.h"

typedef struct {
    byte group;
    byte count;
    byte keys[5];
} MatrixCase;

static byte input(TilemCalc *calc, byte port) {
    return calc->hw.z80_in(calc, port);
}

static void output(TilemCalc *calc, byte port, byte value) {
    calc->hw.z80_out(calc, port, value);
}

static byte run_matrix_case(const MatrixCase *test) {
    TilemCalc *calc = tilem_probe_new_calc();
    int index;
    output(calc, 0x01, test->group);
    for (index = 0; index < test->count; ++index) {
        tilem_keypad_press_key(calc, test->keys[index]);
    }
    {
        byte value = input(calc, 0x01);
        tilem_calc_free(calc);
        return value;
    }
}

int main(int argc, char **argv) {
    static const MatrixCase cases[] = {
        {0xFF, 1, {1}},
        {0xFE, 1, {1}},
        {0xFE, 1, {9}},
        {0xFC, 2, {1, 9}},
        {0xFE, 3, {1, 9, 10}},
        {0xFE, 5, {1, 9, 10, 18, 19}},
        {0xF7, 1, {32}},
        {0x00, 3, {1, 9, 18}},
        {0x7F, 1, {57}},
    };
    static const byte groups[] = {0x00, 0x7F, 0x80, 0xFE, 0xFF};
    TilemCalc *calc;
    byte matrix[9], group_readback[5], scancode[8], on[12], reset[12];
    int index;

    if (argc != 2 || strcmp(argv[1], "--keypad-probe") != 0) {
        fprintf(stderr, "usage: %s --keypad-probe\n", argv[0]);
        return 2;
    }

    for (index = 0; index < 9; ++index) {
        matrix[index] = run_matrix_case(&cases[index]);
    }

    calc = tilem_probe_new_calc();
    for (index = 0; index < 5; ++index) {
        tilem_keypad_set_group(calc, groups[index]);
        group_readback[index] = calc->keypad.group;
    }
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    output(calc, 0x01, 0xFE);
    scancode[0] = input(calc, 0x01);
    tilem_keypad_press_key(calc, 1);
    scancode[1] = input(calc, 0x01);
    scancode[2] = calc->keypad.keysdown[0];
    tilem_keypad_press_key(calc, 1);
    scancode[3] = calc->keypad.keysdown[0];
    tilem_keypad_release_key(calc, 1);
    scancode[4] = input(calc, 0x01);
    scancode[5] = calc->keypad.keysdown[0];
    tilem_keypad_release_key(calc, 1);
    tilem_keypad_press_key(calc, 0);
    scancode[6] = calc->keypad.keysdown[0];
    tilem_keypad_press_key(calc, 65);
    scancode[7] = calc->keypad.keysdown[0];
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    output(calc, 0x01, 0xDF);
    output(calc, 0x03, 0x01);
    on[0] = input(calc, 0x01);
    on[1] = calc->keypad.onkeydown;
    on[2] = calc->keypad.onkeyint;
    tilem_keypad_press_key(calc, TILEM_KEY_ON);
    on[3] = input(calc, 0x01);
    on[4] = calc->keypad.onkeydown;
    on[5] = input(calc, 0x04);
    output(calc, 0x02, 0xFE);
    tilem_keypad_press_key(calc, TILEM_KEY_ON);
    on[6] = input(calc, 0x04);
    tilem_keypad_release_key(calc, TILEM_KEY_ON);
    on[7] = input(calc, 0x01);
    on[8] = calc->keypad.onkeydown;
    on[9] = input(calc, 0x04);
    output(calc, 0x02, 0xFE);
    tilem_keypad_release_key(calc, TILEM_KEY_ON);
    on[10] = input(calc, 0x04);
    on[11] = calc->keypad.keysdown[5];
    tilem_calc_free(calc);

    calc = tilem_probe_new_calc();
    calc->keypad.group = 0x00;
    calc->keypad.onkeydown = 1;
    calc->keypad.onkeyint = 1;
    for (index = 0; index < 8; ++index) {
        calc->keypad.keysdown[index] = 0xFF;
    }
    tilem_calc_reset(calc);
    reset[0] = calc->keypad.group;
    reset[1] = input(calc, 0x01);
    for (index = 0; index < 8; ++index) {
        reset[index + 2] = calc->keypad.keysdown[index];
    }
    reset[10] = calc->keypad.onkeydown;
    reset[11] = calc->keypad.onkeyint;
    tilem_calc_free(calc);

    printf("mode=tilem-keypad-probe matrix=");
    for (index = 0; index < 9; ++index) {
        printf("%s%02X", index ? "," : "", matrix[index]);
    }
    printf(" group_readback=");
    for (index = 0; index < 5; ++index) {
        printf("%s%02X", index ? "," : "", group_readback[index]);
    }
    printf(" scancode=");
    for (index = 0; index < 8; ++index) {
        printf("%s%02X", index ? "," : "", scancode[index]);
    }
    printf(" on=");
    for (index = 0; index < 12; ++index) {
        printf("%s%02X", index ? "," : "", on[index]);
    }
    printf(" reset=");
    for (index = 0; index < 12; ++index) {
        printf("%s%02X", index ? "," : "", reset[index]);
    }
    putchar('\n');
    return 0;
}
