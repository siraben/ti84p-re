/* Direct-core MD5-assist edge probe for pinned TilEm 2.1. */

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include <tilem.h>
#include <z80.h>

#include "tilem_probe_support.h"

static byte input(TilemCalc *calc, byte port) {
    return calc->hw.z80_in(calc, port);
}

static void output(TilemCalc *calc, byte port, byte value) {
    calc->hw.z80_out(calc, port, value);
}

static void load_word(TilemCalc *calc, byte port, dword value) {
    int shift;
    for (shift = 0; shift < 32; shift += 8) {
        output(calc, port, (value >> shift) & 0xFF);
    }
}

static dword read_result(TilemCalc *calc) {
    dword value = 0;
    int index;
    for (index = 0; index < 4; ++index) {
        value |= ((dword) input(calc, 0x1C + index)) << (8 * index);
    }
    return value;
}

int main(int argc, char **argv) {
    static const dword control_operands[] = {1, 2, 3, 4, 5, 6};
    static const dword mutation_operands[] = {
        0x67452301, 0xEFCDAB89, 0x98BADCFE,
        0x10325476, 0x80636261, 0xD76AA478
    };
    TilemCalc *calc;
    byte reset_operand_reads[4], loaded_operand_reads[4];
    dword reset_result, one_write_result, three_write_result;
    dword four_write_result, five_write_result, masked_control_result;
    dword before_mutation_result, after_mutation_result, mixed_result;
    unsigned int masked_shift, masked_mode, reset_state[9];
    uint64_t start_clock, clock_delta;
    int index;

    if (argc != 2 || strcmp(argv[1], "--md5-probe") != 0) {
        fprintf(stderr, "usage: %s --md5-probe\n", argv[0]);
        return 2;
    }

    calc = tilem_probe_new_calc();
    start_clock = calc->z80.clock;
    for (index = 0; index < 4; ++index) {
        reset_operand_reads[index] = input(calc, 0x18 + index);
    }
    reset_result = read_result(calc);

    output(calc, 0x1F, 0x02);
    output(calc, 0x1E, 0);
    output(calc, 0x18, 0x11);
    one_write_result = read_result(calc);
    output(calc, 0x18, 0x22);
    output(calc, 0x18, 0x33);
    three_write_result = read_result(calc);
    output(calc, 0x18, 0x44);
    four_write_result = read_result(calc);
    output(calc, 0x18, 0x55);
    five_write_result = read_result(calc);

    for (index = 0; index < 6; ++index) {
        load_word(calc, 0x18 + index, control_operands[index]);
    }
    output(calc, 0x1E, 0xFF);
    output(calc, 0x1F, 0xFF);
    masked_shift = calc->md5assist.shift;
    masked_mode = calc->md5assist.mode;
    masked_control_result = read_result(calc);
    for (index = 0; index < 4; ++index) {
        loaded_operand_reads[index] = input(calc, 0x18 + index);
    }

    for (index = 0; index < 6; ++index) {
        load_word(calc, 0x18 + index, mutation_operands[index]);
    }
    output(calc, 0x1E, 7);
    output(calc, 0x1F, 0);
    before_mutation_result = read_result(calc);
    mixed_result = input(calc, 0x1C);
    load_word(calc, 0x18, 0xFFFFFFFF);
    after_mutation_result = read_result(calc);
    for (index = 1; index < 4; ++index) {
        mixed_result |= ((dword) input(calc, 0x1C + index)) << (8 * index);
    }
    clock_delta = calc->z80.clock - start_clock;

    for (index = 0; index < 6; ++index) {
        calc->md5assist.regs[index] = 0x11111111 * (index + 1);
    }
    calc->md5assist.shift = 31;
    calc->md5assist.mode = 3;
    tilem_calc_reset(calc);
    for (index = 0; index < 6; ++index) {
        reset_state[index] = calc->md5assist.regs[index];
    }
    reset_state[6] = calc->md5assist.shift;
    reset_state[7] = calc->md5assist.mode;
    reset_state[8] = read_result(calc);
    tilem_calc_free(calc);

    printf(
        "mode=tilem-md5-probe reset_operand_reads=%02X,%02X,%02X,%02X "
        "reset_result=%08X one_write_result=%08X three_write_result=%08X "
        "four_write_result=%08X five_write_result=%08X "
        "masked_controls=%X,%X masked_control_result=%08X "
        "loaded_operand_reads=%02X,%02X,%02X,%02X "
        "before_mutation_result=%08X after_mutation_result=%08X "
        "mixed_result=%08X clock_delta=%" PRIu64 " reset_state=",
        reset_operand_reads[0], reset_operand_reads[1],
        reset_operand_reads[2], reset_operand_reads[3], reset_result,
        one_write_result, three_write_result, four_write_result,
        five_write_result, masked_shift, masked_mode, masked_control_result,
        loaded_operand_reads[0], loaded_operand_reads[1],
        loaded_operand_reads[2], loaded_operand_reads[3],
        before_mutation_result, after_mutation_result, mixed_result,
        clock_delta
    );
    for (index = 0; index < 9; ++index) {
        printf("%s%X", index ? "," : "", reset_state[index]);
    }
    putchar('\n');
    return 0;
}
