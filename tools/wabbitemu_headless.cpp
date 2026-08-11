// Minimal Linux runner for the pinned Wabbitemu TI-84 Plus core.
//
// This file deliberately uses only Wabbitemu's public core and hardware
// initialization functions.  Build it with tools/build_wabbitemu_headless.py;
// do not compile it against an unpinned checkout when collecting evidence.

#include "stdafx.h"

#include "83psehw.h"
#include "core.h"
#include "device.h"
#include "keys.h"

#undef max
#undef min

#include <cerrno>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

// The headless runner never installs debugger breakpoints or enables audio.
// These stubs satisfy optional Wabbitemu hooks without pulling in its GUI-side
// calculator registry and platform audio backend.
void add_breakpoint(memc *, BREAK_TYPE, waddr_t) {}
void rem_breakpoint(memc *, BREAK_TYPE, waddr_t) {}
int FlippedLeft(CPU_t *, int) { return 0; }
int FlippedRight(CPU_t *, int) { return 0; }
int nextsample(CPU_t *) { return 0; }

namespace {

constexpr std::size_t kTi84PlusFlashSize = 64 * PAGE_SIZE;
constexpr std::uint64_t kWakePressTstates = UINT64_C(24000000);
constexpr std::uint64_t kWakeReleaseTstates = UINT64_C(24900000);
constexpr unsigned short kRecoveryPoints[] = {
    0x7BC7, 0x7C1F, 0x7C43, 0x7C48, 0x7CC6,
    0x7CDA, 0x7CE3, 0x7CFB, 0x7D30,
};

[[noreturn]] void fail(const char *message, const char *detail = nullptr) {
    if (detail == nullptr) {
        std::fprintf(stderr, "wabbitemu-headless: %s\n", message);
    } else {
        std::fprintf(stderr, "wabbitemu-headless: %s: %s\n", message, detail);
    }
    std::exit(2);
}

std::uint64_t parse_count(const char *text, const char *name) {
    errno = 0;
    char *end = nullptr;
    const unsigned long long value = std::strtoull(text, &end, 0);
    if (errno != 0 || end == text || *end != '\0') {
        fail("invalid instruction count", name);
    }
    return static_cast<std::uint64_t>(value);
}

std::vector<unsigned char> read_image(const char *path) {
    FILE *stream = std::fopen(path, "rb");
    if (stream == nullptr) {
        fail("cannot open input image", path);
    }
    std::vector<unsigned char> image(kTi84PlusFlashSize);
    const std::size_t size = std::fread(image.data(), 1, image.size(), stream);
    const int trailing = std::fgetc(stream);
    if (std::fclose(stream) != 0) {
        fail("cannot close input image", path);
    }
    if (size != image.size() || trailing != EOF) {
        fail("input image is not exactly 1 MiB", path);
    }
    return image;
}

void write_image(const char *path, const unsigned char *image) {
    FILE *stream = std::fopen(path, "wb");
    if (stream == nullptr) {
        fail("cannot open output image", path);
    }
    if (std::fwrite(image, 1, kTi84PlusFlashSize, stream) !=
        kTi84PlusFlashSize) {
        fail("cannot write output image", path);
    }
    if (std::fclose(stream) != 0) {
        fail("cannot close output image", path);
    }
}

std::uint64_t fnv1a64(const unsigned char *data, std::size_t size) {
    std::uint64_t digest = UINT64_C(14695981039346656037);
    for (std::size_t index = 0; index < size; ++index) {
        digest ^= data[index];
        digest *= UINT64_C(1099511628211);
    }
    return digest;
}

std::size_t changed_bytes(
    const std::vector<unsigned char> &before,
    const unsigned char *after
) {
    std::size_t changed = 0;
    for (std::size_t index = 0; index < before.size(); ++index) {
        changed += before[index] != after[index];
    }
    return changed;
}

void usage(const char *program) {
    std::fprintf(
        stderr,
        "usage: %s INPUT.rom OUTPUT.rom [MAX_STEPS [MIN_STEPS "
        "[SAMPLE_INTERVAL [SETTLE_SAMPLES]]]]\n",
        program
    );
}

}  // namespace

int main(int argc, char **argv) {
    if (argc < 3 || argc > 7) {
        usage(argv[0]);
        return 2;
    }
    const std::uint64_t max_steps =
        argc >= 4 ? parse_count(argv[3], "MAX_STEPS") : UINT64_C(200000000);
    const std::uint64_t min_steps =
        argc >= 5 ? parse_count(argv[4], "MIN_STEPS") : UINT64_C(20000000);
    const std::uint64_t sample_interval =
        argc >= 6 ? parse_count(argv[5], "SAMPLE_INTERVAL") : UINT64_C(1000000);
    const std::uint64_t settle_samples =
        argc >= 7 ? parse_count(argv[6], "SETTLE_SAMPLES") : UINT64_C(10);
    if (max_steps == 0 || min_steps > max_steps || sample_interval == 0 ||
        settle_samples == 0) {
        fail("invalid step or settling bounds");
    }

    const std::vector<unsigned char> input = read_image(argv[1]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    int error = memory_init_84p(&memory);
    error |= tc_init(&timer, MHZ_6);
    error |= CPU_init(&cpu, &memory, &timer);
    ClearDevices(&cpu);
    error |= device_init_83pse(&cpu, TI_84P);
    if (error != 0) {
        fail("Wabbitemu initialization failed");
    }
    std::memcpy(memory.flash, input.data(), input.size());
    if (CPU_reset(&cpu) != 0) {
        fail("Wabbitemu CPU reset failed");
    }

    std::vector<unsigned char> sample(memory.flash, memory.flash + memory.flash_size);
    std::uint64_t unchanged_samples = 0;
    std::uint64_t steps = 0;
    bool wake_pressed = false;
    bool wake_released = false;
    bool recovery_visits[ARRAYSIZE(kRecoveryPoints)] = {};
    for (; steps < max_steps; ++steps) {
        if (!wake_pressed && timer.tstates >= kWakePressTstates) {
            keypad_press(&cpu, KEYGROUP_ON, KEYBIT_ON);
            wake_pressed = true;
        }
        if (wake_pressed && !wake_released &&
            timer.tstates >= kWakeReleaseTstates) {
            keypad_release(&cpu, KEYGROUP_ON, KEYBIT_ON);
            wake_released = true;
        }
        const bank_state_t &pc_bank = memory.banks[mc_bank(cpu.pc)];
        if (!pc_bank.ram && pc_bank.page == 0x3C) {
            for (std::size_t index = 0; index < ARRAYSIZE(kRecoveryPoints); ++index) {
                recovery_visits[index] |= cpu.pc == kRecoveryPoints[index];
            }
        }
        CPU_step(&cpu);
        if ((steps + 1) % sample_interval != 0) {
            continue;
        }
        if (std::memcmp(sample.data(), memory.flash, sample.size()) == 0) {
            ++unchanged_samples;
        } else {
            std::memcpy(sample.data(), memory.flash, sample.size());
            unchanged_samples = 0;
        }
        if (steps + 1 >= min_steps && unchanged_samples >= settle_samples) {
            ++steps;
            break;
        }
    }

    write_image(argv[2], memory.flash);
    std::printf(
        "steps=%" PRIu64 " tstates=%" PRIu64 " pc=0x%04X halted=%d "
        "changed_bytes=%zu input_fnv1a64=%016" PRIx64 " "
        "output_fnv1a64=%016" PRIx64 " wake=%s settled=%s visits=",
        steps,
        timer.tstates,
        cpu.pc,
        static_cast<int>(cpu.halt),
        changed_bytes(input, memory.flash),
        fnv1a64(input.data(), input.size()),
        fnv1a64(memory.flash, memory.flash_size),
        wake_released ? "pressed-released" : "incomplete",
        unchanged_samples >= settle_samples ? "yes" : "no"
    );
    bool first_visit = true;
    for (std::size_t index = 0; index < ARRAYSIZE(kRecoveryPoints); ++index) {
        if (!recovery_visits[index]) {
            continue;
        }
        std::printf("%s3C:%04X", first_visit ? "" : ",", kRecoveryPoints[index]);
        first_visit = false;
    }
    if (first_visit) {
        std::printf("-");
    }
    std::printf("\n");
    return unchanged_samples >= settle_samples ? 0 : 3;
}
