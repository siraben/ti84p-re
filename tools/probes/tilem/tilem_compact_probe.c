/* Execute the complete compact-code display path in the pinned TilEm core. */

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <tilem.h>

#include "tilem_probe_support.h"

#define PROBE_ORIGIN 0x9D95
#define PROBE_RAM_PAGE 1
#define PROBE_STACK 0xFF00
#define FAKE_APPVAR 0xB800
#define RETURN_SENTINEL 0x9D94

static void fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    exit(1);
}

static unsigned long parse_number(const char *text, const char *name) {
    char *end;
    unsigned long value;
    errno = 0;
    value = strtoul(text, &end, 0);
    if (errno || *text == '\0' || *end != '\0') {
        fprintf(stderr, "invalid %s: %s\n", name, text);
        exit(2);
    }
    return value;
}

static byte *read_file(const char *path, size_t *size) {
    FILE *file = fopen(path, "rb");
    byte *data;
    long length;
    if (!file) {
        perror(path);
        exit(1);
    }
    if (fseek(file, 0, SEEK_END) || (length = ftell(file)) < 0 ||
        fseek(file, 0, SEEK_SET)) {
        fclose(file);
        fail("cannot measure input file");
    }
    data = malloc((size_t) length);
    if (!data || fread(data, 1, (size_t) length, file) != (size_t) length) {
        fclose(file);
        fail("cannot read input file");
    }
    fclose(file);
    *size = (size_t) length;
    return data;
}

static size_t find_unique(
    const byte *data, size_t data_size, const byte *needle, size_t needle_size,
    const char *name
) {
    size_t index, found = (size_t) -1;
    for (index = 0; index + needle_size <= data_size; ++index) {
        if (memcmp(data + index, needle, needle_size) != 0) {
            continue;
        }
        if (found != (size_t) -1) {
            fprintf(stderr, "%s is not unique\n", name);
            exit(1);
        }
        found = index;
    }
    if (found == (size_t) -1) {
        fprintf(stderr, "%s was not found\n", name);
        exit(1);
    }
    return found;
}

static void output(TilemCalc *calc, byte port, byte value) {
    calc->hw.z80_out(calc, port, value);
}

static void write_logical(TilemCalc *calc, word address, byte value) {
    calc->hw.z80_wrmem(calc, address, value);
}

static int recognized_display_bcall(word id) {
    return id == 0x4507 || id == 0x455E || id == 0x4972 ||
        id == 0x450A || id == 0x4540 || id == 0x4543 || id == 0x4558;
}

int main(int argc, char **argv) {
    TilemCalc *calc;
    FILE *rom;
    byte *probe, *program, *frame, *fake, *compact;
    byte marker[8], done_marker[] = {0x3E, 0xC7, 0xFE, 0xC7, 0xC9};
    size_t probe_size, frame_offset, done_offset, frame_size, index;
    size_t compact_size = 0, compact_capacity;
    unsigned long probe_id, payload_size, max_clocks;
    unsigned long create_intercepts = 0, run_clocks = 0, key_pages = 0;
    unsigned long marker_visits = 0;
    word done_stop, display_code = 0;
    unsigned long long lcd_hash;
    int done_breakpoint, return_breakpoint;
    dword reason = 0;
    int completed;

    if (argc != 7 || strcmp(argv[1], "--compact-probe") != 0) {
        fprintf(
            stderr,
            "usage: %s --compact-probe INPUT.rom PROBE.bin ID PAYLOAD_SIZE MAX_CLOCKS\n",
            argv[0]
        );
        return 2;
    }
    probe_id = parse_number(argv[4], "ID");
    payload_size = parse_number(argv[5], "PAYLOAD_SIZE");
    max_clocks = parse_number(argv[6], "MAX_CLOCKS");
    if (probe_id > 255 || payload_size > 65535) {
        fail("probe ID or payload size is out of range");
    }
    probe = read_file(argv[3], &probe_size);
    marker[0] = 'H'; marker[1] = 'W'; marker[2] = 'P'; marker[3] = '1';
    marker[4] = 1; marker[5] = (byte) probe_id;
    marker[6] = (byte) payload_size; marker[7] = (byte) (payload_size >> 8);
    frame_offset = find_unique(probe, probe_size, marker, sizeof(marker), "frame");
    done_offset = find_unique(
        probe, probe_size, done_marker, sizeof(done_marker), "compact display marker"
    );
    frame_size = 10 + payload_size;
    if (probe_size > 0x4000 - (PROBE_ORIGIN & 0x3FFF) ||
        frame_offset + frame_size > probe_size) {
        fail("probe does not fit the expected RAM image");
    }
    compact_capacity = frame_size * 5 + 64;
    compact = malloc(compact_capacity);
    if (!compact) {
        fail("cannot allocate compact-code buffer");
    }

    calc = tilem_probe_new_calc();
    rom = fopen(argv[2], "rb");
    if (!rom) {
        perror(argv[2]);
        return 1;
    }
    if (tilem_calc_load_state(calc, rom, NULL)) {
        fclose(rom);
        fail("TilEm could not load the ROM image");
    }
    fclose(rom);

    output(calc, 0x03, 0x00); output(calc, 0x03, 0x0B);
    output(calc, 0x04, 0x06); output(calc, 0x05, 0x00);
    output(calc, 0x06, 0x3F); output(calc, 0x07, 0x81);
    output(calc, 0x0E, 0x00); output(calc, 0x0F, 0x00);
    output(calc, 0x27, 0x00); output(calc, 0x28, 0x00);
    output(calc, 0x20, 0x01); output(calc, 0x30, 0x00);
    output(calc, 0x31, 0x00);
    calc->z80.clock += 100;
    calc->lcd.busy = 0;
    output(calc, 0x10, 0x01);
    write_logical(calc, 0x844F, 0x20);
    write_logical(calc, 0x8451, 0x80);

    program = calc->ram + PROBE_RAM_PAGE * 0x4000 + (PROBE_ORIGIN & 0x3FFF);
    memcpy(program, probe, probe_size);
    frame = program + frame_offset;
    fake = calc->ram + PROBE_RAM_PAGE * 0x4000 + (FAKE_APPVAR & 0x3FFF);
    memset(&calc->z80.r, 0, sizeof(calc->z80.r));
    calc->z80.r.pc.d = PROBE_ORIGIN;
    calc->z80.r.sp.d = PROBE_STACK;
    calc->z80.r.iy.d = 0x89F0;
    calc->z80.r.iff1 = 1;
    calc->z80.r.iff2 = 1;
    calc->z80.r.im = 1;
    calc->z80.interrupts = 0;
    calc->z80.halted = 0;
    calc->z80.exception = 0;
    calc->z80.emuflags = TILEM_Z80_BREAK_EXCEPTIONS;
    write_logical(calc, PROBE_STACK, RETURN_SENTINEL & 0xFF);
    write_logical(calc, PROBE_STACK + 1, RETURN_SENTINEL >> 8);

    done_stop = (word) (PROBE_ORIGIN + done_offset);
    done_breakpoint = tilem_z80_add_breakpoint(
        calc, TILEM_BREAK_MEM_EXEC, done_stop, done_stop, 0xFFFF, NULL, NULL
    );
    return_breakpoint = tilem_z80_add_breakpoint(
        calc, TILEM_BREAK_MEM_EXEC, RETURN_SENTINEL, RETURN_SENTINEL,
        0xFFFF, NULL, NULL
    );
    for (index = 0; index + 2 < probe_size; ++index) {
        word address, id;
        int intercept = 0;
        if (probe[index] == 0xCD && probe[index + 1] == 0x98 &&
            probe[index + 2] == 0x9D) {
            intercept = 1;
        } else if (probe[index] == 0xEF) {
            id = (word) (probe[index + 1] | (probe[index + 2] << 8));
            intercept = recognized_display_bcall(id);
        }
        if (intercept) {
            address = (word) (PROBE_ORIGIN + index);
            tilem_z80_add_breakpoint(
                calc, TILEM_BREAK_MEM_EXEC, address, address, 0xFFFF, NULL, NULL
            );
        }
    }

    while (run_clocks < max_clocks) {
        if (calc->z80.r.pc.w.l == RETURN_SENTINEL) {
            break;
        }
        if (calc->z80.r.pc.w.l == done_stop) {
            ++marker_visits;
            if (done_breakpoint >= 0) {
                tilem_z80_remove_breakpoint(calc, done_breakpoint);
                done_breakpoint = -1;
            }
        }
        if (calc->z80.r.pc.w.l >= PROBE_ORIGIN &&
            (size_t) (calc->z80.r.pc.w.l - PROBE_ORIGIN) + 2 < probe_size) {
            size_t offset = calc->z80.r.pc.w.l - PROBE_ORIGIN;
            if (probe[offset] == 0xCD && probe[offset + 1] == 0x98 &&
                probe[offset + 2] == 0x9D) {
                memcpy(fake, frame, frame_size);
                calc->z80.r.de.d = FAKE_APPVAR + frame_size;
                calc->z80.r.pc.d += 3;
                calc->z80.r.iff1 = 1;
                calc->z80.r.iff2 = 1;
                ++create_intercepts;
                continue;
            }
            if (probe[offset] == 0xEF) {
                word id = (word) (probe[offset + 1] | (probe[offset + 2] << 8));
                if (id == 0x4507) {
                    display_code = calc->z80.r.hl.w.l;
                } else if (id == 0x455E) {
                    if (compact_size + 1 >= compact_capacity) {
                        fail("compact-code output exceeded its bound");
                    }
                    compact[compact_size++] = calc->z80.r.af.b.h;
                } else if (id == 0x4972) {
                    ++key_pages;
                    calc->z80.r.af.b.h = 0x05;
                } else if (!recognized_display_bcall(id)) {
                    break;
                }
                calc->z80.r.pc.d += 3;
                continue;
            }
        }
        dword before = calc->z80.clock;
        reason = tilem_z80_run(calc, 10000000, NULL);
        run_clocks += calc->z80.clock - before;
        if (reason & TILEM_STOP_EXCEPTION) {
            break;
        }
        if (reason == 0) {
            continue;
        }
        if (!(reason & TILEM_STOP_BREAKPOINT)) {
            break;
        }
        if (done_breakpoint >= 0 &&
            calc->z80.stop_breakpoint == done_breakpoint &&
            calc->z80.r.pc.w.l == done_stop) {
            continue;
        }
        if (calc->z80.stop_breakpoint == return_breakpoint &&
            calc->z80.r.pc.w.l == RETURN_SENTINEL) {
            break;
        }
        continue;
    }
    compact[compact_size] = 0;
    completed = calc->z80.r.pc.w.l == RETURN_SENTINEL &&
        calc->z80.r.sp.w.l == PROBE_STACK + 2 &&
        !(reason & TILEM_STOP_EXCEPTION) && create_intercepts == 1 &&
        marker_visits == 1 &&
        memcmp(fake, frame, frame_size) == 0 && compact_size >= 6 &&
        memcmp(compact, "HWPZ1-", 6) == 0;
    lcd_hash = 14695981039346656037ULL;
    for (index = 0; index < calc->hw.lcdmemsize; ++index) {
        lcd_hash ^= calc->lcdmem[index];
        lcd_hash *= 1099511628211ULL;
    }
    printf(
        "mode=tilem-compact probe_id=%lu payload_size=%lu probe_size=%zu "
        "run_clocks=%lu create_intercepts=%lu key_pages=%lu final_pc=0x%04X "
        "final_sp=0x%04X marker_visits=%lu returned=%d exception=0x%X appvar_matches=%d "
        "completed=%d display_code=%u "
        "rendered=0 lcd_fnv1a64=%016llx "
        "compact_code=%s frame_hex=",
        probe_id, payload_size, probe_size, run_clocks, create_intercepts,
        key_pages, calc->z80.r.pc.w.l, calc->z80.r.sp.w.l, marker_visits,
        calc->z80.r.pc.w.l == RETURN_SENTINEL, calc->z80.exception,
        memcmp(fake, frame, frame_size) == 0, completed, display_code,
        lcd_hash, compact
    );
    for (index = 0; index < frame_size; ++index) {
        printf("%02X", frame[index]);
    }
    putchar('\n');

    free(compact);
    free(probe);
    tilem_calc_free(calc);
    return completed ? 0 : 3;
}
