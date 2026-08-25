/* Execute an assembled hardware probe unchanged in the pinned TilEm core. */

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

int main(int argc, char **argv) {
    TilemCalc *calc;
    FILE *rom;
    byte *probe, *program, *frame, *fake;
    byte marker[8], display_bcall[] = {0xEF, 0x40, 0x45};
    size_t probe_size, frame_offset, display_offset, frame_size, index;
    unsigned long probe_id, payload_size, max_clocks;
    unsigned long create_intercepts = 0, run_clocks = 0;
    word display_stop;
    int display_breakpoint;
    dword reason = 0;
    int completed;

    if (argc < 6 || argc > 7 || strcmp(argv[1], "--exact-probe") != 0) {
        fprintf(
            stderr,
            "usage: %s --exact-probe INPUT.rom PROBE.bin ID PAYLOAD_SIZE "
            "[MAX_CLOCKS]\n",
            argv[0]
        );
        return 2;
    }
    probe_id = parse_number(argv[4], "ID");
    payload_size = parse_number(argv[5], "PAYLOAD_SIZE");
    max_clocks = argc == 7 ? parse_number(argv[6], "MAX_CLOCKS") : 100000000;
    if (probe_id > 255 || payload_size > 65535) {
        fail("probe ID or payload size is out of range");
    }
    probe = read_file(argv[3], &probe_size);
    marker[0] = 'H';
    marker[1] = 'W';
    marker[2] = 'P';
    marker[3] = '1';
    marker[4] = 1;
    marker[5] = (byte) probe_id;
    marker[6] = (byte) payload_size;
    marker[7] = (byte) (payload_size >> 8);
    frame_offset = find_unique(probe, probe_size, marker, sizeof(marker), "frame");
    display_offset = find_unique(
        probe, probe_size, display_bcall, sizeof(display_bcall), "display bcall"
    );
    frame_size = 10 + payload_size;
    if (probe_size > 0x4000 - (PROBE_ORIGIN & 0x3FFF) ||
        frame_offset + frame_size > probe_size) {
        fail("probe does not fit the expected RAM image");
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

    /* Establish the documented direct-Asm baseline without relying on a GUI
       transfer path. All three probes guard the portions they rely upon. */
    output(calc, 0x03, 0x00);
    output(calc, 0x03, 0x0B);
    output(calc, 0x04, 0x06);
    output(calc, 0x05, 0x00);
    output(calc, 0x06, 0x3F);
    output(calc, 0x07, 0x81);
    output(calc, 0x0E, 0x00);
    output(calc, 0x0F, 0x00);
    output(calc, 0x27, 0x00);
    output(calc, 0x28, 0x00);
    output(calc, 0x20, 0x01);
    output(calc, 0x30, 0x00);
    output(calc, 0x31, 0x00);
    calc->z80.clock += 100;
    calc->lcd.busy = 0;
    output(calc, 0x10, 0x01);
    write_logical(calc, 0x844F, 0x20);
    write_logical(calc, 0x8451, 0x80);

    program = calc->ram + PROBE_RAM_PAGE * 0x4000 +
        (PROBE_ORIGIN & 0x3FFF);
    memcpy(program, probe, probe_size);
    if (memcmp(program, probe, probe_size) != 0) {
        fail("probe injection did not read back");
    }
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

    display_stop = (word) (PROBE_ORIGIN + display_offset);
    display_breakpoint = tilem_z80_add_breakpoint(
        calc, TILEM_BREAK_MEM_EXEC, display_stop, display_stop, 0xFFFF, NULL, NULL
    );
    for (index = 0; index + 2 < probe_size; ++index) {
        word address;
        if (probe[index] != 0xCD || probe[index + 1] != 0x98 ||
            probe[index + 2] != 0x9D) {
            continue;
        }
        address = (word) (PROBE_ORIGIN + index);
        tilem_z80_add_breakpoint(
            calc, TILEM_BREAK_MEM_EXEC, address, address, 0xFFFF, NULL, NULL
        );
    }

    while (run_clocks < max_clocks) {
        dword before = calc->z80.clock;
        reason = tilem_z80_run(calc, 10000000, NULL);
        run_clocks += calc->z80.clock - before;
        if (reason & TILEM_STOP_EXCEPTION) {
            break;
        }
        if (!(reason & TILEM_STOP_BREAKPOINT)) {
            break;
        }
        if (calc->z80.stop_breakpoint == display_breakpoint &&
            calc->z80.r.pc.w.l == display_stop) {
            break;
        }
        if (calc->z80.r.pc.w.l >= PROBE_ORIGIN &&
            (size_t) (calc->z80.r.pc.w.l - PROBE_ORIGIN) + 2 < probe_size) {
            size_t offset = calc->z80.r.pc.w.l - PROBE_ORIGIN;
            if (probe[offset] == 0xCD && probe[offset + 1] == 0x98 &&
                probe[offset + 2] == 0x9D) {
                memcpy(fake, frame, frame_size);
                calc->z80.r.de.d = FAKE_APPVAR + frame_size;
                calc->z80.r.pc.d += 3;
                ++create_intercepts;
                continue;
            }
        }
        break;
    }

    completed = calc->z80.r.pc.w.l == display_stop &&
        !(reason & TILEM_STOP_EXCEPTION) && create_intercepts != 0 &&
        memcmp(fake, frame, frame_size) == 0;
    printf(
        "mode=tilem-exact-probe probe_id=%lu payload_size=%lu "
        "probe_size=%zu run_clocks=%lu create_intercepts=%lu "
        "display_stop=0x%04X final_pc=0x%04X stop_reason=0x%X "
        "exception=0x%X appvar_matches=%d completed=%d display_code=%u "
        "frame_hex=",
        probe_id, payload_size, probe_size, run_clocks, create_intercepts,
        display_stop, calc->z80.r.pc.w.l, reason, calc->z80.exception,
        memcmp(fake, frame, frame_size) == 0, completed, calc->z80.r.de.w.l
    );
    for (index = 0; index < frame_size; ++index) {
        printf("%02X", frame[index]);
    }
    printf(" appvar_frame_hex=");
    for (index = 0; index < frame_size; ++index) {
        printf("%02X", fake[index]);
    }
    putchar('\n');

    free(probe);
    tilem_calc_free(calc);
    return completed ? 0 : 3;
}
