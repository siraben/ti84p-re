// Minimal Linux runner for the pinned Wabbitemu TI-84 Plus core.
//
// This file deliberately uses Wabbitemu's core interfaces and exposed context
// structures.  Build it with tools/build_wabbitemu_headless.py; do not compile
// it against an unpinned checkout when collecting evidence.

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
constexpr unsigned short kProbeOrigin = 0x9D95;
constexpr unsigned short kProbeTarget = 0x7FF0;
constexpr unsigned char kProbeRamPage = 1;
constexpr unsigned short kProbeStack = 0xFF00;
constexpr unsigned short kBootFlashLower = 0x08;
constexpr unsigned short kBootFlashUpper = 0x29;
constexpr unsigned short kBootRamLower = 0x4000;
constexpr unsigned short kBootRamUpper = 0x83FF;
constexpr std::uint64_t kWakePressTstates = UINT64_C(24000000);
constexpr std::uint64_t kWakeReleaseTstates = UINT64_C(24900000);
constexpr unsigned short kRecoveryPoints[] = {
    0x7BC7, 0x7C1F, 0x7C43, 0x7C48, 0x7CC6,
    0x7CDA, 0x7CE3, 0x7CFB, 0x7D30,
};

struct GateTransition {
    bool ram;
    unsigned char page;
    unsigned short pc;
    bool before_locked;
    bool after_locked;
};

struct GateWrite {
    bool ram;
    unsigned char page;
    unsigned short pc;
    unsigned char value;
    bool before_locked;
    bool after_locked;
};

bool block_program_worker_loaded(const memory_context_t &memory) {
    constexpr unsigned char source_page = 0x3F;
    constexpr unsigned short source_address = 0x4CCA;
    constexpr std::size_t worker_size = 0x7C;
    const bank_state_t &destination = memory.banks[mc_bank(0x8100)];
    const unsigned char *source = memory.flash +
        source_page * PAGE_SIZE + mc_base(source_address);
    return destination.ram &&
        std::memcmp(
            destination.addr + mc_base(0x8100),
            source,
            worker_size
        ) == 0;
}

unsigned int execution_violation_resets = 0;

void record_execution_violation(CPU_t *cpu) {
    ++execution_violation_resets;
    CPU_reset(cpu);
}

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

std::vector<unsigned char> read_probe(const char *path) {
    FILE *stream = std::fopen(path, "rb");
    if (stream == nullptr) {
        fail("cannot open probe image", path);
    }
    std::vector<unsigned char> probe;
    for (int byte = std::fgetc(stream); byte != EOF; byte = std::fgetc(stream)) {
        probe.push_back(static_cast<unsigned char>(byte));
    }
    const bool read_failed = std::ferror(stream) != 0;
    const bool close_failed = std::fclose(stream) != 0;
    if (read_failed || close_failed) {
        fail("cannot read probe image", path);
    }
    if (probe.empty() || probe.size() > PAGE_SIZE - mc_base(kProbeOrigin)) {
        fail("probe does not fit at 0x9D95", path);
    }
    return probe;
}

std::size_t find_unique(
    const std::vector<unsigned char> &data,
    const unsigned char *pattern,
    std::size_t pattern_size,
    const char *name
) {
    std::size_t found = data.size();
    unsigned int matches = 0;
    for (std::size_t offset = 0; offset + pattern_size <= data.size(); ++offset) {
        if (std::memcmp(data.data() + offset, pattern, pattern_size) == 0) {
            found = offset;
            ++matches;
        }
    }
    if (matches != 1) {
        fail("probe must contain one exact sequence", name);
    }
    return found;
}

unsigned char parse_page(const char *text) {
    const std::uint64_t page = parse_count(text, "PAGE");
    if (page >= 64) {
        fail("Flash page must be between 0x00 and 0x3F");
    }
    return static_cast<unsigned char>(page);
}

unsigned int parse_bounded(
    const char *text,
    const char *name,
    unsigned int maximum
) {
    const std::uint64_t value = parse_count(text, name);
    if (value > maximum) {
        fail("numeric argument exceeds its allowed range", name);
    }
    return static_cast<unsigned int>(value);
}

const char *flash_step_name(FLASH_COMMAND step) {
    switch (step) {
    case FLASH_READ: return "read";
    case FLASH_AA: return "aa";
    case FLASH_55: return "55";
    case FLASH_PROGRAM: return "program";
    case FLASH_ERASE: return "erase";
    case FLASH_ERASE_AA: return "erase-aa";
    case FLASH_ERASE_55: return "erase-55";
    case FLASH_FASTMODE: return "fast";
    case FLASH_FASTMODE_PROG: return "fast-program";
    case FLASH_FASTMODE_EXIT: return "fast-exit";
    case FLASH_AUTOSELECT: return "autoselect";
    case FLASH_ERROR: return "error";
    }
    return "unknown";
}

bool boot_protection_ready(const memory_context_t &memory) {
    return memory.flash_locked && memory.prot_mode == MODE0 &&
        memory.flash_lower == kBootFlashLower &&
        memory.flash_upper == kBootFlashUpper &&
        memory.ram_lower == kBootRamLower && memory.ram_upper == kBootRamUpper;
}

void initialize(
    const std::vector<unsigned char> &input,
    memory_context_t *memory,
    timer_context_t *timer,
    CPU_t *cpu
) {
    int error = memory_init_84p(memory);
    error |= tc_init(timer, MHZ_6);
    error |= CPU_init(cpu, memory, timer);
    ClearDevices(cpu);
    error |= device_init_83pse(cpu, TI_84P);
    if (error != 0) {
        fail("Wabbitemu initialization failed");
    }
    std::memcpy(memory->flash, input.data(), input.size());
    if (CPU_reset(cpu) != 0) {
        fail("Wabbitemu CPU reset failed");
    }
}

void prepare_flash_command_probe(
    const std::vector<unsigned char> &input,
    memory_context_t *memory
) {
    std::memcpy(memory->flash, input.data(), input.size());
    memory->boot_mapped = FALSE;
    memory->banks = memory->normal_banks;
    memory->flash_locked = FALSE;
    memory->step = FLASH_READ;
    memory->flash_error = FALSE;
    memory->flash_toggles = 0;
}

void write_unlock_prefix(CPU_t *cpu) {
    change_page(cpu->mem_c, 1, 0x02, FALSE);
    CPU_mem_write(cpu, 0x6AAA, 0xAA);
    change_page(cpu->mem_c, 1, 0x01, FALSE);
    CPU_mem_write(cpu, 0x5555, 0x55);
}

void write_command(CPU_t *cpu, unsigned char command) {
    write_unlock_prefix(cpu);
    change_page(cpu->mem_c, 1, 0x02, FALSE);
    CPU_mem_write(cpu, 0x6AAA, command);
}

std::size_t count_non_ff(const unsigned char *data, std::size_t size) {
    std::size_t count = 0;
    for (std::size_t index = 0; index < size; ++index) {
        count += data[index] != 0xFF;
    }
    return count;
}

std::size_t count_differences(
    const std::vector<unsigned char> &before,
    const unsigned char *after,
    std::size_t begin,
    std::size_t end
) {
    std::size_t count = 0;
    for (std::size_t index = begin; index < end; ++index) {
        count += before[index] != after[index];
    }
    return count;
}

int run_flash_command_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(
            stderr,
            "usage: %s --flash-command-probe INPUT.rom\n",
            argv[0]
        );
        return 2;
    }

    constexpr unsigned char target_page = 0x08;
    constexpr unsigned short target_address = 0x4100;
    constexpr std::size_t target_physical = 0x20100;
    constexpr std::size_t sector_start = 0x20000;
    constexpr std::size_t sector_size = 0x10000;
    constexpr std::size_t sector_end = sector_start + sector_size;
    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);
    const int flash_version = memory.flash_version;

    prepare_flash_command_probe(input, &memory);
    const FLASH_COMMAND initial_step = memory.step;
    write_command(&cpu, 0x90);
    const FLASH_COMMAND autoselect_entry_step = memory.step;
    change_page(&memory, 1, target_page, FALSE);
    const unsigned char autoselect_maker = CPU_mem_read(&cpu, 0x4000);
    const unsigned char autoselect_device = CPU_mem_read(&cpu, 0x4002);
    const unsigned char autoselect_protection = CPU_mem_read(&cpu, 0x4004);
    CPU_mem_write(&cpu, 0x4000, 0xF0);
    const FLASH_COMMAND autoselect_reset_step = memory.step;
    const unsigned char autoselect_array_byte = CPU_mem_read(&cpu, 0x4000);

    prepare_flash_command_probe(input, &memory);
    change_page(&memory, 1, 0x02, FALSE);
    CPU_mem_write(&cpu, 0x6AAA, 0xAA);
    const FLASH_COMMAND partial_step_before_reset = memory.step;
    CPU_mem_write(&cpu, 0x6AAA, 0xF0);
    const FLASH_COMMAND partial_reset_step = memory.step;

    prepare_flash_command_probe(input, &memory);
    const std::vector<unsigned char> cfi_before(memory.flash, memory.flash + memory.flash_size);
    change_page(&memory, 1, target_page, FALSE);
    CPU_mem_write(&cpu, 0x4055, 0x98);
    const FLASH_COMMAND cfi_step = memory.step;
    const std::size_t cfi_changed_bytes = count_differences(
        cfi_before, memory.flash, 0, memory.flash_size
    );

    prepare_flash_command_probe(input, &memory);
    const std::vector<unsigned char> suspend_before(
        memory.flash, memory.flash + memory.flash_size
    );
    write_command(&cpu, 0x80);
    write_unlock_prefix(&cpu);
    const FLASH_COMMAND suspend_window_step = memory.step;
    change_page(&memory, 1, target_page, FALSE);
    CPU_mem_write(&cpu, target_address, 0xB0);
    const FLASH_COMMAND suspend_step = memory.step;
    const std::size_t suspend_changed_bytes = count_differences(
        suspend_before, memory.flash, 0, memory.flash_size
    );
    CPU_mem_write(&cpu, target_address, 0x30);
    const FLASH_COMMAND resume_step = memory.step;
    const std::size_t resume_changed_bytes = count_differences(
        suspend_before, memory.flash, 0, memory.flash_size
    );

    prepare_flash_command_probe(input, &memory);
    memory.flash[target_physical] = 0xF0;
    memory.flash[target_physical + 1] = 0xAA;
    write_command(&cpu, 0x20);
    const FLASH_COMMAND fast_entry_step = memory.step;
    CPU_mem_write(&cpu, 0x4000, 0xA0);
    const FLASH_COMMAND fast_first_select_step = memory.step;
    change_page(&memory, 1, target_page, FALSE);
    CPU_mem_write(&cpu, target_address, 0x50);
    const unsigned char fast_first_stored = memory.flash[target_physical];
    const FLASH_COMMAND fast_after_first_step = memory.step;
    CPU_mem_write(&cpu, 0x4000, 0xA0);
    const FLASH_COMMAND fast_second_select_step = memory.step;
    CPU_mem_write(&cpu, target_address + 1, 0xA0);
    const unsigned char fast_second_stored = memory.flash[target_physical + 1];
    const FLASH_COMMAND fast_after_second_step = memory.step;
    CPU_mem_write(&cpu, 0x4000, 0x90);
    const FLASH_COMMAND fast_exit_select_step = memory.step;
    CPU_mem_write(&cpu, 0x4000, 0xF0);
    const FLASH_COMMAND fast_exit_step = memory.step;

    prepare_flash_command_probe(input, &memory);
    std::memset(memory.flash + sector_start, 0, sector_size);
    memory.flash[sector_start - 1] = 0x5A;
    memory.flash[sector_end] = 0xA5;
    const std::vector<unsigned char> sector_before(
        memory.flash, memory.flash + memory.flash_size
    );
    write_command(&cpu, 0x80);
    write_unlock_prefix(&cpu);
    change_page(&memory, 1, target_page, FALSE);
    CPU_mem_write(&cpu, target_address, 0x30);
    const FLASH_COMMAND sector_step = memory.step;
    const std::size_t sector_erased_bytes = sector_size - count_non_ff(
        memory.flash + sector_start, sector_size
    );
    const std::size_t sector_changed_bytes = count_differences(
        sector_before, memory.flash, sector_start, sector_end
    );
    const std::size_t sector_outside_changed_bytes =
        count_differences(sector_before, memory.flash, 0, sector_start) +
        count_differences(
            sector_before, memory.flash, sector_end, memory.flash_size
        );

    prepare_flash_command_probe(input, &memory);
    memory.flash[memory.flash_size - 1] = 0;
    const unsigned char chip_boot_before = memory.flash[memory.flash_size - 1];
    const std::size_t chip_non_ff_before = count_non_ff(
        memory.flash, memory.flash_size
    );
    const std::vector<unsigned char> chip_before(
        memory.flash, memory.flash + memory.flash_size
    );
    write_command(&cpu, 0x80);
    write_unlock_prefix(&cpu);
    change_page(&memory, 1, 0x02, FALSE);
    CPU_mem_write(&cpu, 0x6AAA, 0x10);
    const FLASH_COMMAND chip_step = memory.step;
    const std::size_t chip_non_ff_after = count_non_ff(
        memory.flash, memory.flash_size
    );
    const std::size_t chip_changed_bytes = count_differences(
        chip_before, memory.flash, 0, memory.flash_size
    );
    const unsigned char chip_boot_after = memory.flash[memory.flash_size - 1];

    std::printf(
        "mode=flash-command-probe flash_size=0x%zX flash_version=%d "
        "configured_flash_locked=0 initial_step=%s "
        "autoselect_entry_step=%s autoselect_maker=0x%02X "
        "autoselect_device=0x%02X autoselect_protection=0x%02X "
        "autoselect_reset_step=%s autoselect_array_byte=0x%02X "
        "partial_step_before_reset=%s partial_reset_step=%s "
        "cfi_step=%s cfi_changed_bytes=%zu "
        "suspend_window_step=%s suspend_step=%s suspend_changed_bytes=%zu "
        "resume_step=%s resume_changed_bytes=%zu fast_entry_step=%s "
        "fast_first_select_step=%s fast_first_initial=0xF0 "
        "fast_first_requested=0x50 fast_first_stored=0x%02X "
        "fast_after_first_step=%s fast_second_select_step=%s "
        "fast_second_initial=0xAA fast_second_requested=0xA0 "
        "fast_second_stored=0x%02X fast_after_second_step=%s "
        "fast_exit_select_step=%s fast_exit_step=%s "
        "sector_target_page=0x%02X sector_target_address=0x%04X "
        "sector_start=0x%zX sector_size=0x%zX sector_step=%s "
        "sector_erased_bytes=%zu sector_changed_bytes=%zu "
        "sector_outside_changed_bytes=%zu chip_step=%s "
        "chip_non_ff_before=%zu chip_non_ff_after=%zu "
        "chip_changed_bytes=%zu chip_boot_before=0x%02X "
        "chip_boot_after=0x%02X tstates=%" PRIu64 "\n",
        static_cast<std::size_t>(memory.flash_size),
        flash_version,
        flash_step_name(initial_step),
        flash_step_name(autoselect_entry_step),
        autoselect_maker,
        autoselect_device,
        autoselect_protection,
        flash_step_name(autoselect_reset_step),
        autoselect_array_byte,
        flash_step_name(partial_step_before_reset),
        flash_step_name(partial_reset_step),
        flash_step_name(cfi_step),
        cfi_changed_bytes,
        flash_step_name(suspend_window_step),
        flash_step_name(suspend_step),
        suspend_changed_bytes,
        flash_step_name(resume_step),
        resume_changed_bytes,
        flash_step_name(fast_entry_step),
        flash_step_name(fast_first_select_step),
        fast_first_stored,
        flash_step_name(fast_after_first_step),
        flash_step_name(fast_second_select_step),
        fast_second_stored,
        flash_step_name(fast_after_second_step),
        flash_step_name(fast_exit_select_step),
        flash_step_name(fast_exit_step),
        target_page,
        target_address,
        sector_start,
        sector_size,
        flash_step_name(sector_step),
        sector_erased_bytes,
        sector_changed_bytes,
        sector_outside_changed_bytes,
        flash_step_name(chip_step),
        chip_non_ff_before,
        chip_non_ff_after,
        chip_changed_bytes,
        chip_boot_before,
        chip_boot_after,
        timer.tstates
    );
    return 0;
}

int run_flash_program_probe(int argc, char **argv) {
    if (argc < 5 || argc > 6) {
        std::fprintf(
            stderr,
            "usage: %s --flash-program-probe INPUT.rom INITIAL REQUESTED "
            "[INITIAL_TOGGLE]\n",
            argv[0]
        );
        return 2;
    }
    const unsigned char initial = static_cast<unsigned char>(
        parse_bounded(argv[3], "INITIAL", 0xFF)
    );
    const unsigned char requested = static_cast<unsigned char>(
        parse_bounded(argv[4], "REQUESTED", 0xFF)
    );
    const unsigned char initial_toggle = static_cast<unsigned char>(
        argc == 6 ? parse_bounded(argv[5], "INITIAL_TOGGLE", 0x40) : 0
    );
    if (initial_toggle != 0 && initial_toggle != 0x40) {
        fail("INITIAL_TOGGLE must be 0 or 0x40");
    }

    constexpr unsigned char target_page = 0x08;
    constexpr unsigned short target_offset = 0x0100;
    constexpr unsigned short target_address = 0x4100;
    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);

    memory.boot_mapped = FALSE;
    memory.banks = memory.normal_banks;
    memory.flash_locked = FALSE;
    memory.step = FLASH_READ;
    memory.flash_error = FALSE;
    memory.flash_toggles = initial_toggle;
    const std::size_t target_physical =
        static_cast<std::size_t>(target_page) * PAGE_SIZE + target_offset;
    const unsigned char original_rom_byte = memory.flash[target_physical];
    memory.flash[target_physical] = initial;

    change_page(&memory, 1, 0x02, FALSE);
    CPU_mem_write(&cpu, 0x6AAA, 0xAA);
    change_page(&memory, 1, 0x01, FALSE);
    CPU_mem_write(&cpu, 0x5555, 0x55);
    change_page(&memory, 1, 0x02, FALSE);
    CPU_mem_write(&cpu, 0x6AAA, 0xA0);
    change_page(&memory, 1, target_page, FALSE);
    CPU_mem_write(&cpu, target_address, requested);

    const unsigned char stored = memory.flash[target_physical];
    const FLASH_COMMAND step_after_write = memory.step;
    const bool error_after_write = memory.flash_error;
    const unsigned char toggle_after_write = memory.flash_toggles;
    const unsigned char first_read = CPU_mem_read(&cpu, target_address);
    const bool error_after_first = memory.flash_error;
    const unsigned char toggle_after_first = memory.flash_toggles;
    const unsigned char second_read = CPU_mem_read(&cpu, target_address);
    const bool error_after_second = memory.flash_error;
    const unsigned char toggle_after_second = memory.flash_toggles;

    std::printf(
        "mode=flash-program-probe target_page=0x%02X target_offset=0x%04X "
        "target_address=0x%04X target_physical=0x%05zX "
        "original_rom_byte=0x%02X initial=0x%02X requested=0x%02X "
        "configured_flash_locked=%d initial_toggle=0x%02X command_writes=4 "
        "stored=0x%02X step_after_write=%s error_after_write=%d "
        "toggle_after_write=0x%02X first_read=0x%02X "
        "error_after_first=%d toggle_after_first=0x%02X "
        "second_read=0x%02X error_after_second=%d "
        "toggle_after_second=0x%02X tstates=%" PRIu64 "\n",
        target_page,
        target_offset,
        target_address,
        target_physical,
        original_rom_byte,
        initial,
        requested,
        static_cast<int>(memory.flash_locked),
        initial_toggle,
        stored,
        flash_step_name(step_after_write),
        static_cast<int>(error_after_write),
        toggle_after_write,
        first_read,
        static_cast<int>(error_after_first),
        toggle_after_first,
        second_read,
        static_cast<int>(error_after_second),
        toggle_after_second,
        timer.tstates
    );
    return 0;
}

int run_flash_worker_probe(int argc, char **argv) {
    if (argc < 5 || argc > 8) {
        std::fprintf(
            stderr,
            "usage: %s --flash-worker-probe INPUT.rom INITIAL REQUESTED "
            "[INITIAL_TOGGLE [MAX_BOOT_STEPS [MAX_PROBE_STEPS]]]\n",
            argv[0]
        );
        return 2;
    }
    const unsigned char initial = static_cast<unsigned char>(
        parse_bounded(argv[3], "INITIAL", 0xFF)
    );
    const unsigned char requested = static_cast<unsigned char>(
        parse_bounded(argv[4], "REQUESTED", 0xFF)
    );
    const unsigned char initial_toggle = static_cast<unsigned char>(
        argc >= 6 ? parse_bounded(argv[5], "INITIAL_TOGGLE", 0x40) : 0
    );
    if (initial_toggle != 0 && initial_toggle != 0x40) {
        fail("INITIAL_TOGGLE must be 0 or 0x40");
    }
    const std::uint64_t max_boot_steps =
        argc >= 7 ? parse_count(argv[6], "MAX_BOOT_STEPS") : UINT64_C(5000000);
    const std::uint64_t max_probe_steps =
        argc >= 8 ? parse_count(argv[7], "MAX_PROBE_STEPS") : UINT64_C(10000);
    if (max_boot_steps == 0 || max_probe_steps == 0) {
        fail("Flash worker probe step bounds must be positive");
    }

    constexpr unsigned char target_page = 0x08;
    constexpr unsigned short target_offset = 0x0100;
    constexpr unsigned short target_address = 0x4100;
    constexpr unsigned short source_address = kProbeOrigin + 4;
    constexpr unsigned short return_address = kProbeOrigin + 3;
    const unsigned char harness[] = {0xEF, 0x87, 0x80, 0x76};
    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);

    std::uint64_t boot_steps = 0;
    while (boot_steps < max_boot_steps && !boot_protection_ready(memory)) {
        CPU_step(&cpu);
        ++boot_steps;
    }
    if (!boot_protection_ready(memory)) {
        fail("retail boot did not establish and relock the expected protection bounds");
    }
    const std::uint64_t boot_tstates = timer.tstates;
    const unsigned short boot_pc = cpu.pc;
    const bank_state_t boot_bank = memory.banks[mc_bank(boot_pc)];
    const bool boot_flash_locked = memory.flash_locked;
    const unsigned short boot_flash_lower = memory.flash_lower;
    const unsigned short boot_flash_upper = memory.flash_upper;

    memory.boot_mapped = FALSE;
    memory.banks = memory.normal_banks;
    memory.port07 = 0x80 | kProbeRamPage;
    change_page(&memory, 2, kProbeRamPage, TRUE);
    const std::size_t source_physical =
        kProbeRamPage * PAGE_SIZE + mc_base(kProbeOrigin);
    std::memcpy(memory.ram + source_physical, harness, sizeof(harness));
    memory.ram[source_physical + sizeof(harness)] = requested;
    if (std::memcmp(
            memory.banks[2].addr + mc_base(kProbeOrigin),
            harness,
            sizeof(harness)
        ) != 0 || CPU_mem_read(&cpu, source_address) != requested) {
        fail("injected Flash worker harness does not read back from logical RAM");
    }

    const std::size_t target_physical =
        static_cast<std::size_t>(target_page) * PAGE_SIZE + target_offset;
    const unsigned char original_rom_byte = memory.flash[target_physical];
    memory.flash[target_physical] = initial;
    const bool configured_flash_locked = false;
    memory.flash_locked = configured_flash_locked;
    memory.step = FLASH_READ;
    memory.flash_error = FALSE;
    memory.flash_toggles = initial_toggle;

    cpu.a = target_page;
    cpu.f = 0;
    cpu.bc = 1;
    cpu.de = target_address;
    cpu.hl = source_address;
    cpu.pc = kProbeOrigin;
    cpu.sp = kProbeStack;
    cpu.halt = FALSE;
    cpu.iff1 = FALSE;
    cpu.iff2 = FALSE;
    cpu.interrupt = FALSE;
    cpu.ei_block = FALSE;
    cpu.prefix = 0;
    execution_violation_resets = 0;
    cpu.exe_violation_callback = record_execution_violation;

    unsigned int bcall_visits = 0;
    unsigned int worker_entry_visits = 0;
    unsigned int program_write_visits = 0;
    unsigned int dq7_read_visits = 0;
    unsigned int final_dq7_read_visits = 0;
    unsigned int success_reset_visits = 0;
    unsigned int failure_reset_visits = 0;
    unsigned int return_visits = 0;
    std::vector<unsigned char> poll_reads;
    std::uint64_t probe_steps = 0;
    for (; probe_steps < max_probe_steps; ++probe_steps) {
        if (cpu.pc == return_address) {
            ++return_visits;
            break;
        }
        const bank_state_t &pc_bank = memory.banks[mc_bank(cpu.pc)];
        const bool in_worker = cpu.pc >= 0x8100 && cpu.pc <= 0x817B &&
            pc_bank.ram && pc_bank.page == kProbeRamPage;
        const unsigned short executing_pc = cpu.pc;
        const bool captured_poll_read = in_worker &&
            (cpu.pc == 0x814D || cpu.pc == 0x8159);
        if (cpu.pc == kProbeOrigin) {
            ++bcall_visits;
        }
        if (in_worker && cpu.pc == 0x8100) {
            ++worker_entry_visits;
        }
        if (in_worker && cpu.pc == 0x8149) {
            ++program_write_visits;
        }
        if (in_worker && cpu.pc == 0x814D) {
            ++dq7_read_visits;
        }
        if (in_worker && cpu.pc == 0x8159) {
            ++final_dq7_read_visits;
        }
        if (in_worker && cpu.pc == 0x816B) {
            ++success_reset_visits;
        }
        if (in_worker && cpu.pc == 0x8175) {
            ++failure_reset_visits;
        }
        CPU_step(&cpu);
        if (captured_poll_read && poll_reads.size() < 8) {
            poll_reads.push_back(cpu.a);
        }
        if (execution_violation_resets != 0) {
            ++probe_steps;
            break;
        }
    }

    const bool returned_success = return_visits == 1 &&
        worker_entry_visits == 1 && program_write_visits == 1 &&
        success_reset_visits == 1 && failure_reset_visits == 0 &&
        cpu.a == 0 && (cpu.f & 0x40) != 0;
    const bool returned_failure = return_visits == 1 &&
        worker_entry_visits == 1 && program_write_visits == 1 &&
        success_reset_visits == 0 && failure_reset_visits == 1 &&
        cpu.a == 0x3F && (cpu.f & 0x40) == 0;
    const bool bounded_poll = return_visits == 0 &&
        worker_entry_visits == 1 && program_write_visits == 1 &&
        dq7_read_visits >= 2 && success_reset_visits == 0 &&
        failure_reset_visits == 0 && execution_violation_resets == 0 &&
        probe_steps == max_probe_steps;
    const char *classification = returned_success ? "success" :
        returned_failure ? "failure" : bounded_poll ? "step-limit" :
        "indeterminate";
    const unsigned char stored = memory.flash[target_physical];
    const bank_state_t final_bank = memory.banks[1];
    std::printf(
        "mode=flash-worker-probe target_page=0x%02X target_offset=0x%04X "
        "target_address=0x%04X target_physical=0x%05zX "
        "original_rom_byte=0x%02X initial=0x%02X requested=0x%02X "
        "initial_toggle=0x%02X boot_steps=%" PRIu64 " "
        "boot_tstates=%" PRIu64 " boot_pc=0x%04X boot_page=%s%02X "
        "boot_flash_locked=%d boot_flash_lower=0x%02X "
        "boot_flash_upper=0x%02X configured_flash_locked=%d "
        "source_page=0x%02X source_address=0x%04X "
        "harness_size=%zu return_address=0x%04X max_probe_steps=%" PRIu64 " "
        "probe_steps=%" PRIu64 " probe_tstates=%" PRIu64 " "
        "bcall_visits=%u worker_entry_visits=%u program_write_visits=%u "
        "dq7_read_visits=%u final_dq7_read_visits=%u "
        "success_reset_visits=%u failure_reset_visits=%u return_visits=%u "
        "violation_resets=%u poll_reads=",
        target_page,
        target_offset,
        target_address,
        target_physical,
        original_rom_byte,
        initial,
        requested,
        initial_toggle,
        boot_steps,
        boot_tstates,
        boot_pc,
        boot_bank.ram ? "RAM:" : "",
        boot_bank.page,
        static_cast<int>(boot_flash_locked),
        boot_flash_lower,
        boot_flash_upper,
        static_cast<int>(configured_flash_locked),
        kProbeRamPage,
        source_address,
        sizeof(harness),
        return_address,
        max_probe_steps,
        probe_steps,
        timer.tstates - boot_tstates,
        bcall_visits,
        worker_entry_visits,
        program_write_visits,
        dq7_read_visits,
        final_dq7_read_visits,
        success_reset_visits,
        failure_reset_visits,
        return_visits,
        execution_violation_resets
    );
    if (poll_reads.empty()) {
        std::printf("-");
    } else {
        for (std::size_t index = 0; index < poll_reads.size(); ++index) {
            std::printf("%s%02X", index == 0 ? "" : ",", poll_reads[index]);
        }
    }
    std::printf(
        " stored=0x%02X flash_step=%s flash_error=%d "
        "flash_toggle=0x%02X return_af=0x%04X return_bc=0x%04X "
        "return_de=0x%04X return_hl=0x%04X port06=0x%02X "
        "bank1_page=%s%02X final_pc=0x%04X classification=%s\n",
        stored,
        flash_step_name(memory.step),
        static_cast<int>(memory.flash_error),
        memory.flash_toggles,
        cpu.af,
        cpu.bc,
        cpu.de,
        cpu.hl,
        memory.port06,
        final_bank.ram ? "RAM:" : "",
        final_bank.page,
        cpu.pc,
        classification
    );
    return std::strcmp(classification, "indeterminate") == 0 ? 3 : 0;
}

int run_execution_probe(int argc, char **argv) {
    if (argc < 5 || argc > 7) {
        std::fprintf(
            stderr,
            "usage: %s --execution-probe INPUT.rom PROBE.bin PAGE "
            "[MAX_BOOT_STEPS [MAX_PROBE_STEPS]]\n",
            argv[0]
        );
        return 2;
    }
    const unsigned char page = parse_page(argv[4]);
    const std::uint64_t max_boot_steps =
        argc >= 6 ? parse_count(argv[5], "MAX_BOOT_STEPS") : UINT64_C(5000000);
    const std::uint64_t max_probe_steps =
        argc >= 7 ? parse_count(argv[6], "MAX_PROBE_STEPS") : UINT64_C(1000);
    if (max_boot_steps == 0 || max_probe_steps == 0) {
        fail("execution-probe step bounds must be positive");
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    const std::vector<unsigned char> probe = read_probe(argv[3]);
    const unsigned char call[] = {0xCD, 0xF0, 0x7F};
    const unsigned char marker[] = {0x3E, page, 0x32, 0x78, 0x84, 0xC9};
    const unsigned char map_page[] = {0x3E, page, 0xD3, 0x06};
    const std::size_t call_offset = find_unique(probe, call, sizeof(call), "CALL 0x7FF0");
    find_unique(probe, marker, sizeof(marker), "target marker signature");
    find_unique(probe, map_page, sizeof(map_page), "target page mapping");
    const unsigned short call_address =
        static_cast<unsigned short>(kProbeOrigin + call_offset);
    const unsigned short return_address = call_address + sizeof(call);
    const std::size_t target_offset =
        static_cast<std::size_t>(page) * PAGE_SIZE + mc_base(kProbeTarget);
    if (std::memcmp(input.data() + target_offset, marker, sizeof(marker)) != 0) {
        fail("fixture ROM lacks the exact target marker");
    }

    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);

    std::uint64_t boot_steps = 0;
    while (boot_steps < max_boot_steps && !boot_protection_ready(memory)) {
        CPU_step(&cpu);
        ++boot_steps;
    }
    if (!boot_protection_ready(memory)) {
        fail("retail boot did not establish and relock the expected protection bounds");
    }
    const std::uint64_t boot_tstates = timer.tstates;
    const unsigned short boot_pc = cpu.pc;
    const bank_state_t boot_bank = memory.banks[mc_bank(boot_pc)];
    const bool boot_flash_locked = memory.flash_locked;
    const unsigned short boot_flash_lower = memory.flash_lower;
    const unsigned short boot_flash_upper = memory.flash_upper;
    const unsigned short boot_ram_lower = memory.ram_lower;
    const unsigned short boot_ram_upper = memory.ram_upper;
    const RAM_PROT_MODE boot_ram_mode = memory.prot_mode;

    // This is an explicit emulator-core injection.  It preserves the bounds
    // established by the retail boot, but selects known executable RAM for the
    // guarded probe instead of reproducing an OS variable/UI launch.
    memory.boot_mapped = FALSE;
    memory.banks = memory.normal_banks;
    memory.port07 = 0x80 | kProbeRamPage;
    change_page(&memory, 2, kProbeRamPage, TRUE);
    std::memcpy(
        memory.ram + kProbeRamPage * PAGE_SIZE + mc_base(kProbeOrigin),
        probe.data(),
        probe.size()
    );
    if (std::memcmp(
            memory.banks[2].addr + mc_base(kProbeOrigin),
            probe.data(),
            probe.size()
        ) != 0) {
        fail("injected probe does not read back from logical RAM");
    }

    cpu.pc = kProbeOrigin;
    cpu.sp = kProbeStack;
    cpu.halt = FALSE;
    cpu.iff1 = FALSE;
    cpu.iff2 = FALSE;
    cpu.interrupt = FALSE;
    cpu.prefix = 0;
    execution_violation_resets = 0;
    cpu.exe_violation_callback = record_execution_violation;

    unsigned int call_visits = 0;
    unsigned int target_visits = 0;
    unsigned int target_followup_visits = 0;
    unsigned int return_visits = 0;
    std::uint64_t probe_steps = 0;
    for (; probe_steps < max_probe_steps; ++probe_steps) {
        if (cpu.pc == call_address) {
            ++call_visits;
        }
        if (cpu.pc == kProbeTarget) {
            ++target_visits;
        }
        if (cpu.pc == kProbeTarget + 2) {
            ++target_followup_visits;
        }
        if (cpu.pc == return_address) {
            ++return_visits;
            break;
        }
        CPU_step(&cpu);
        if (execution_violation_resets != 0) {
            ++probe_steps;
            break;
        }
    }

    const char *classification = "indeterminate";
    if (call_visits == 1 && target_visits == 1 &&
        target_followup_visits == 1 && return_visits == 1 &&
        execution_violation_resets == 0) {
        classification = "returned";
    } else if (call_visits == 1 && target_visits == 1 &&
               target_followup_visits == 0 && return_visits == 0 &&
               execution_violation_resets == 1) {
        classification = "violation-reset";
    }
    const unsigned char observed_marker =
        memory.ram[kProbeRamPage * PAGE_SIZE + mc_base(0x8478)];
    std::printf(
        "mode=execution-probe page=0x%02X boot_steps=%" PRIu64 " "
        "boot_tstates=%" PRIu64 " boot_pc=0x%04X boot_page=%s%02X "
        "flash_locked=%d flash_lower=0x%02X flash_upper=0x%02X "
        "ram_lower=0x%04X ram_upper=0x%04X ram_mode=%d "
        "injected_page=0x%02X injected_address=0x%04X probe_size=%zu "
        "call_address=0x%04X return_address=0x%04X probe_steps=%" PRIu64 " "
        "call_visits=%u target_visits=%u target_followup_visits=%u "
        "return_visits=%u violation_resets=%u marker=0x%02X "
        "classification=%s\n",
        page,
        boot_steps,
        boot_tstates,
        boot_pc,
        boot_bank.ram ? "RAM:" : "",
        boot_bank.page,
        static_cast<int>(boot_flash_locked),
        boot_flash_lower,
        boot_flash_upper,
        boot_ram_lower,
        boot_ram_upper,
        static_cast<int>(boot_ram_mode),
        kProbeRamPage,
        kProbeOrigin,
        probe.size(),
        call_address,
        return_address,
        probe_steps,
        call_visits,
        target_visits,
        target_followup_visits,
        return_visits,
        execution_violation_resets,
        observed_marker,
        classification
    );
    return std::strcmp(classification, "indeterminate") == 0 ? 3 : 0;
}

int run_ram_execution_probe(int argc, char **argv) {
    if (argc < 9 || argc > 11) {
        std::fprintf(
            stderr,
            "usage: %s --ram-execution-probe INPUT.rom PROBE.bin "
            "TARGET_PAGE TARGET_OFFSET RAM_MODE LOWER_CHUNK UPPER_CHUNK "
            "[MAX_BOOT_STEPS [MAX_PROBE_STEPS]]\n",
            argv[0]
        );
        return 2;
    }
    const unsigned char target_page = static_cast<unsigned char>(
        parse_bounded(argv[4], "TARGET_PAGE", 7)
    );
    const unsigned short target_offset = static_cast<unsigned short>(
        parse_bounded(argv[5], "TARGET_OFFSET", PAGE_SIZE - 6)
    );
    const unsigned char ram_mode = static_cast<unsigned char>(
        parse_bounded(argv[6], "RAM_MODE", 3)
    );
    const unsigned char lower_chunk = static_cast<unsigned char>(
        parse_bounded(argv[7], "LOWER_CHUNK", 0xFF)
    );
    const unsigned char upper_chunk = static_cast<unsigned char>(
        parse_bounded(argv[8], "UPPER_CHUNK", 0xFF)
    );
    const std::uint64_t max_boot_steps =
        argc >= 10 ? parse_count(argv[9], "MAX_BOOT_STEPS") : UINT64_C(5000000);
    const std::uint64_t max_probe_steps =
        argc >= 11 ? parse_count(argv[10], "MAX_PROBE_STEPS") : UINT64_C(1000);
    if (max_boot_steps == 0 || max_probe_steps == 0) {
        fail("RAM execution-probe step bounds must be positive");
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    const std::vector<unsigned char> probe = read_probe(argv[3]);
    const unsigned short target_address = 0x4000 + target_offset;
    const unsigned char selector = 0x80 | target_page;
    const unsigned char marker_value = static_cast<unsigned char>(
        0x40 | (ram_mode << 3) | target_page
    );
    const unsigned char call[] = {
        0xCD,
        static_cast<unsigned char>(target_address & 0xFF),
        static_cast<unsigned char>(target_address >> 8),
    };
    const unsigned char marker[] = {
        0x3E, marker_value, 0x32, 0x78, 0x84, 0xC9,
    };
    const unsigned char map_page[] = {0x3E, selector, 0xD3, 0x06};
    const unsigned char read_target[] = {
        0x21,
        static_cast<unsigned char>(target_address & 0xFF),
        static_cast<unsigned char>(target_address >> 8),
    };
    const std::size_t call_offset =
        find_unique(probe, call, sizeof(call), "RAM target CALL");
    find_unique(probe, marker, sizeof(marker), "RAM target marker signature");
    find_unique(probe, map_page, sizeof(map_page), "RAM target page mapping");
    find_unique(probe, read_target, sizeof(read_target), "RAM target data read");
    const unsigned short call_address =
        static_cast<unsigned short>(kProbeOrigin + call_offset);
    const unsigned short return_address = call_address + sizeof(call);

    const std::size_t source_start =
        kProbeRamPage * PAGE_SIZE + mc_base(kProbeOrigin);
    const std::size_t source_end = source_start + probe.size();
    const std::size_t target_start = target_page * PAGE_SIZE + target_offset;
    const std::size_t target_end = target_start + sizeof(marker);
    const std::size_t state_marker =
        kProbeRamPage * PAGE_SIZE + mc_base(0x8478);
    if (source_start < target_end && target_start < source_end) {
        fail("RAM target overlaps the injected probe");
    }
    if (target_start <= state_marker && state_marker < target_end) {
        fail("RAM target overlaps the observed-marker byte");
    }

    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);

    std::uint64_t boot_steps = 0;
    while (boot_steps < max_boot_steps && !boot_protection_ready(memory)) {
        CPU_step(&cpu);
        ++boot_steps;
    }
    if (!boot_protection_ready(memory)) {
        fail("retail boot did not establish and relock the expected protection bounds");
    }
    const std::uint64_t boot_tstates = timer.tstates;
    const unsigned short boot_pc = cpu.pc;
    const bank_state_t boot_bank = memory.banks[mc_bank(boot_pc)];
    const unsigned short boot_ram_lower = memory.ram_lower;
    const unsigned short boot_ram_upper = memory.ram_upper;
    const RAM_PROT_MODE boot_ram_mode = memory.prot_mode;

    // This mode tests Wabbitemu's core predicate directly.  The retail boot
    // establishes the baseline first; the harness then configures the requested
    // RAM fields and injects both source and target bytes.
    memory.boot_mapped = FALSE;
    memory.banks = memory.normal_banks;
    memory.port07 = 0x80 | kProbeRamPage;
    change_page(&memory, 2, kProbeRamPage, TRUE);
    memory.prot_mode = static_cast<RAM_PROT_MODE>(ram_mode);
    memory.ram_lower = lower_chunk * 0x400;
    memory.ram_upper = upper_chunk * 0x400 + 0x3FF;
    const unsigned short configured_ram_lower = memory.ram_lower;
    const unsigned short configured_ram_upper = memory.ram_upper;
    std::memcpy(memory.ram + source_start, probe.data(), probe.size());
    std::memcpy(memory.ram + target_start, marker, sizeof(marker));
    if (std::memcmp(
            memory.banks[2].addr + mc_base(kProbeOrigin),
            probe.data(),
            probe.size()
        ) != 0) {
        fail("injected RAM probe does not read back from its logical mapping");
    }
    change_page(&memory, 1, target_page, TRUE);
    if (std::memcmp(
            memory.banks[1].addr + target_offset,
            marker,
            sizeof(marker)
        ) != 0) {
        fail("injected RAM target does not read back from its logical mapping");
    }
    change_page(&memory, 1, 0, FALSE);

    cpu.pc = kProbeOrigin;
    cpu.sp = kProbeStack;
    cpu.halt = FALSE;
    cpu.iff1 = FALSE;
    cpu.iff2 = FALSE;
    cpu.interrupt = FALSE;
    cpu.prefix = 0;
    execution_violation_resets = 0;
    cpu.exe_violation_callback = record_execution_violation;

    unsigned int call_visits = 0;
    unsigned int target_visits = 0;
    unsigned int target_followup_visits = 0;
    unsigned int return_visits = 0;
    std::uint64_t probe_steps = 0;
    for (; probe_steps < max_probe_steps; ++probe_steps) {
        if (cpu.pc == call_address) {
            ++call_visits;
        }
        if (cpu.pc == target_address) {
            ++target_visits;
        }
        if (cpu.pc == target_address + 2) {
            ++target_followup_visits;
        }
        if (cpu.pc == return_address) {
            ++return_visits;
            break;
        }
        CPU_step(&cpu);
        if (execution_violation_resets != 0) {
            ++probe_steps;
            break;
        }
    }

    const char *classification = "indeterminate";
    if (call_visits == 1 && target_visits == 1 &&
        target_followup_visits == 1 && return_visits == 1 &&
        execution_violation_resets == 0) {
        classification = "returned";
    } else if (call_visits == 1 && target_visits == 1 &&
               target_followup_visits == 0 && return_visits == 0 &&
               execution_violation_resets == 1) {
        classification = "violation-reset";
    }
    const unsigned char observed_marker = memory.ram[state_marker];
    const unsigned int target_physical = target_page * PAGE_SIZE + target_offset;
    std::printf(
        "mode=ram-execution-probe target_page=0x%02X target_offset=0x%04X "
        "target_address=0x%04X target_physical=0x%05X "
        "boot_steps=%" PRIu64 " boot_tstates=%" PRIu64 " "
        "boot_pc=0x%04X boot_page=%s%02X "
        "boot_ram_lower=0x%04X boot_ram_upper=0x%04X boot_ram_mode=%d "
        "configured_lower_chunk=0x%02X configured_upper_chunk=0x%02X "
        "configured_ram_lower=0x%04X configured_ram_upper=0x%04X "
        "configured_ram_mode=%d source_page=0x%02X source_address=0x%04X "
        "probe_size=%zu call_address=0x%04X return_address=0x%04X "
        "probe_steps=%" PRIu64 " call_visits=%u target_visits=%u "
        "target_followup_visits=%u return_visits=%u violation_resets=%u "
        "expected_marker=0x%02X marker=0x%02X classification=%s\n",
        target_page,
        target_offset,
        target_address,
        target_physical,
        boot_steps,
        boot_tstates,
        boot_pc,
        boot_bank.ram ? "RAM:" : "",
        boot_bank.page,
        boot_ram_lower,
        boot_ram_upper,
        static_cast<int>(boot_ram_mode),
        lower_chunk,
        upper_chunk,
        configured_ram_lower,
        configured_ram_upper,
        static_cast<int>(ram_mode),
        kProbeRamPage,
        kProbeOrigin,
        probe.size(),
        call_address,
        return_address,
        probe_steps,
        call_visits,
        target_visits,
        target_followup_visits,
        return_visits,
        execution_violation_resets,
        marker_value,
        observed_marker,
        classification
    );
    return std::strcmp(classification, "indeterminate") == 0 ? 3 : 0;
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
    if (argc >= 2 && std::strcmp(argv[1], "--flash-command-probe") == 0) {
        return run_flash_command_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--flash-worker-probe") == 0) {
        return run_flash_worker_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--flash-program-probe") == 0) {
        return run_flash_program_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--ram-execution-probe") == 0) {
        return run_ram_execution_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--execution-probe") == 0) {
        return run_execution_probe(argc, argv);
    }
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
    initialize(input, &memory, &timer, &cpu);

    std::vector<unsigned char> sample(memory.flash, memory.flash + memory.flash_size);
    std::uint64_t unchanged_samples = 0;
    std::uint64_t steps = 0;
    bool wake_pressed = false;
    bool wake_released = false;
    bool recovery_visits[ARRAYSIZE(kRecoveryPoints)] = {};
    std::vector<GateWrite> gate_writes;
    std::vector<GateTransition> gate_transitions;
    unsigned int unlocked_write_bcall_visits = 0;
    unsigned int unlocked_erase_bcall_visits = 0;
    unsigned int unlocked_program_worker_entry_visits = 0;
    unsigned int unlocked_program_write_visits = 0;
    unsigned int unlocked_program_success_reset_visits = 0;
    unsigned int unlocked_program_failure_reset_visits = 0;
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
        const bool program_worker = cpu.pc >= 0x8100 && cpu.pc <= 0x817B &&
            block_program_worker_loaded(memory);
        if (!memory.flash_locked) {
            if (!pc_bank.ram && pc_bank.page == 0x3F && cpu.pc == 0x4CA6) {
                ++unlocked_write_bcall_visits;
            }
            if (!pc_bank.ram && pc_bank.page == 0x3F && cpu.pc == 0x4C2A) {
                ++unlocked_erase_bcall_visits;
            }
            if (program_worker && cpu.pc == 0x8100) {
                ++unlocked_program_worker_entry_visits;
            }
            if (program_worker && cpu.pc == 0x8149) {
                ++unlocked_program_write_visits;
            }
            if (program_worker && cpu.pc == 0x816B) {
                ++unlocked_program_success_reset_visits;
            }
            if (program_worker && cpu.pc == 0x8175) {
                ++unlocked_program_failure_reset_visits;
            }
        }
        const unsigned short executing_pc = cpu.pc;
        const bank_state_t executing_bank = pc_bank;
        const bool locked_before = memory.flash_locked;
        const bool gate_write = mc_base(executing_pc) + 1 < PAGE_SIZE &&
            executing_bank.addr[mc_base(executing_pc)] == 0xD3 &&
            executing_bank.addr[mc_base(executing_pc) + 1] == 0x14;
        const unsigned char gate_value = cpu.a;
        CPU_step(&cpu);
        if (gate_write) {
            gate_writes.push_back({
                executing_bank.ram != 0,
                static_cast<unsigned char>(executing_bank.page),
                executing_pc,
                gate_value,
                locked_before,
                memory.flash_locked != 0,
            });
        }
        if (memory.flash_locked != locked_before) {
            gate_transitions.push_back({
                executing_bank.ram != 0,
                static_cast<unsigned char>(executing_bank.page),
                executing_pc,
                locked_before,
                memory.flash_locked != 0,
            });
        }
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
    std::printf(" gate_writes=");
    if (gate_writes.empty()) {
        std::printf("-");
    } else {
        for (std::size_t index = 0; index < gate_writes.size(); ++index) {
            const GateWrite &write = gate_writes[index];
            std::printf(
                "%s%s%02X:%04X:%02X:%d>%d",
                index == 0 ? "" : ",",
                write.ram ? "RAM:" : "",
                write.page,
                write.pc,
                write.value,
                static_cast<int>(write.before_locked),
                static_cast<int>(write.after_locked)
            );
        }
    }
    std::printf(" gate_transitions=");
    if (gate_transitions.empty()) {
        std::printf("-");
    } else {
        for (std::size_t index = 0; index < gate_transitions.size(); ++index) {
            const GateTransition &transition = gate_transitions[index];
            std::printf(
                "%s%s%02X:%04X:%d>%d",
                index == 0 ? "" : ",",
                transition.ram ? "RAM:" : "",
                transition.page,
                transition.pc,
                static_cast<int>(transition.before_locked),
                static_cast<int>(transition.after_locked)
            );
        }
    }
    std::printf(
        " unlocked_write_bcall_visits=%u unlocked_erase_bcall_visits=%u "
        "unlocked_program_worker_entry_visits=%u "
        "unlocked_program_write_visits=%u "
        "unlocked_program_success_reset_visits=%u "
        "unlocked_program_failure_reset_visits=%u\n",
        unlocked_write_bcall_visits,
        unlocked_erase_bcall_visits,
        unlocked_program_worker_entry_visits,
        unlocked_program_write_visits,
        unlocked_program_success_reset_visits,
        unlocked_program_failure_reset_visits
    );
    return unchanged_samples >= settle_samples ? 0 : 3;
}
