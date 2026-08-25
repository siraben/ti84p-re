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
#include "lcd.h"
#include "link.h"

#undef max
#undef min

#include <cerrno>
#include <cmath>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
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

struct UsbRomIoWrite {
    unsigned char port;
    unsigned char value;
};

struct UsbRomHarness {
    bool handshake_success;
    bool frame_success;
    bool scripted_transfer;
    bool script_error;
    bool controller_status_controlled;
    devp controller_status_code;
    void *controller_status_aux;
    unsigned char registers[MAX_DEVICES];
    std::uint64_t input_counts[MAX_DEVICES];
    std::uint64_t output_counts[MAX_DEVICES];
    std::vector<UsbRomIoWrite> writes;
    std::vector<std::vector<unsigned char>> receive_packets;
    std::size_t receive_packet_index;
    std::size_t receive_byte_index;
    std::vector<std::vector<unsigned char>> transmit_packets;
    std::vector<unsigned char> transmit_packet;
};

struct UsbRomCaseResult {
    const char *name;
    bool handshake_success;
    bool frame_success;
    std::uint64_t boot_steps;
    std::uint64_t boot_tstates;
    std::uint64_t probe_steps;
    std::uint64_t probe_tstates;
    unsigned int init_visits;
    unsigned int reset_helper_visits;
    unsigned int timeout_tick_visits;
    unsigned int cleanup_visits;
    unsigned int receive_boundary_visits;
    unsigned int return_visits;
    unsigned int violation_resets;
    unsigned int flash_changed_bytes;
    unsigned char final_a;
    unsigned char final_f;
    unsigned short final_pc;
    bool completed;
    UsbRomHarness io;
};

struct UsbRomReceiveResult {
    std::uint64_t boot_steps;
    std::uint64_t boot_tstates;
    std::uint64_t probe_steps;
    std::uint64_t probe_tstates;
    unsigned int init_visits;
    unsigned int receive_entry_visits;
    unsigned int control_start_visits;
    unsigned int ack_parse_visits;
    unsigned int power_gate_value;
    unsigned int receive_iy;
    unsigned int page_check_visits;
    unsigned int page_check_value;
    unsigned int progress_visits;
    bool progress_state_seeded;
    unsigned int stream_receive_visits;
    unsigned int record_dispatch_visits;
    unsigned int invalid_page_visits;
    unsigned int cleanup_visits;
    unsigned int stop_visits;
    unsigned int violation_resets;
    unsigned int flash_changed_bytes;
    unsigned short final_pc;
    bool completed;
    UsbRomHarness io;
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
    std::memset(timer, 0, sizeof(*timer));
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
    cpu->pio.lcd->reset(cpu);
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

void write_device_port(CPU_t *cpu, unsigned char port, unsigned char value) {
    cpu->bus = value;
    if (device_output(cpu, port) != 0) {
        fail("native device rejected an output", "direct device probe");
    }
}

unsigned char read_device_port(CPU_t *cpu, unsigned char port) {
    if (device_input(cpu, port) != 0) {
        fail("native device rejected an input", "direct device probe");
    }
    return cpu->bus;
}

bool try_write_device_port(CPU_t *cpu, unsigned char port, unsigned char value) {
    if (!cpu->pio.devices[port].active) {
        return false;
    }
    cpu->bus = value;
    return device_output(cpu, port) == 0;
}

struct DeviceReadResult {
    bool accepted;
    unsigned char value;
};

DeviceReadResult try_read_device_port(CPU_t *cpu, unsigned char port) {
    cpu->bus = 0;
    const bool accepted = device_input(cpu, port) == 0;
    return {accepted, cpu->bus};
}

struct KeyPosition {
    int group;
    int bit;
};

unsigned char read_keypad_case(
    CPU_t *cpu,
    unsigned char group_mask,
    const std::vector<KeyPosition> &keys
) {
    for (const KeyPosition &key : keys) {
        keypad_press(cpu, key.group, key.bit);
    }
    write_device_port(cpu, 0x01, group_mask);
    const unsigned char result = read_device_port(cpu, 0x01);
    write_device_port(cpu, 0x01, 0xFF);
    for (const KeyPosition &key : keys) {
        keypad_release(cpu, key.group, key.bit);
    }
    return result;
}

void evaluate_device_port(CPU_t *cpu, unsigned char port, const char *context) {
    device_t *device = &cpu->pio.devices[port];
    if (!device->active || device->code == nullptr) {
        fail("requested device is unavailable", context);
    }
    cpu->input = FALSE;
    cpu->output = FALSE;
    device->code(cpu, device);
}

int run_keypad_edge_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s --keypad-edge-probe INPUT.rom\n", argv[0]);
        return 2;
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);

    const unsigned char single_read = read_keypad_case(
        &cpu, 0xFE, {{0, 0}}
    );
    const unsigned char same_column_read = read_keypad_case(
        &cpu, 0xFC, {{0, 0}, {1, 0}}
    );
    const unsigned char rectangle_read = read_keypad_case(
        &cpu, 0xFE, {{0, 0}, {1, 0}, {1, 1}}
    );
    const unsigned char transitive_read = read_keypad_case(
        &cpu, 0xFE, {{0, 0}, {1, 0}, {1, 1}, {2, 1}, {2, 2}}
    );
    const unsigned char unwired_read = read_keypad_case(
        &cpu, 0x7F, {{7, 0}}
    );

    const unsigned char on_initial_status = read_device_port(&cpu, 0x04);
    write_device_port(&cpu, 0x03, 0x01);
    const unsigned char on_enabled_status = read_device_port(&cpu, 0x04);
    keypad_press(&cpu, KEYGROUP_ON, KEYBIT_ON);
    const unsigned char on_press_before_eval = read_device_port(&cpu, 0x04);
    evaluate_device_port(&cpu, 0x03, "keypad probe");
    const unsigned char on_press_after_eval = read_device_port(&cpu, 0x04);

    write_device_port(&cpu, 0x03, 0x00);
    write_device_port(&cpu, 0x03, 0x01);
    const unsigned char on_held_after_ack = read_device_port(&cpu, 0x04);
    evaluate_device_port(&cpu, 0x03, "keypad probe");
    const unsigned char on_held_after_eval = read_device_port(&cpu, 0x04);

    keypad_release(&cpu, KEYGROUP_ON, KEYBIT_ON);
    const unsigned char on_release_before_eval = read_device_port(&cpu, 0x04);
    evaluate_device_port(&cpu, 0x03, "keypad probe");
    const unsigned char on_release_after_eval = read_device_port(&cpu, 0x04);
    keypad_press(&cpu, KEYGROUP_ON, KEYBIT_ON);
    const unsigned char on_second_press_before_eval = read_device_port(&cpu, 0x04);
    evaluate_device_port(&cpu, 0x03, "keypad probe");
    const unsigned char on_second_press_after_eval = read_device_port(&cpu, 0x04);

    std::printf(
        "mode=keypad-edge-probe single_mask=0xFE single_read=0x%02X "
        "same_column_mask=0xFC same_column_read=0x%02X "
        "rectangle_mask=0xFE rectangle_read=0x%02X "
        "transitive_mask=0xFE transitive_read=0x%02X "
        "unwired_mask=0x7F unwired_read=0x%02X "
        "on_initial_status=0x%02X on_enabled_status=0x%02X "
        "on_press_before_eval=0x%02X on_press_after_eval=0x%02X "
        "on_held_after_ack=0x%02X on_held_after_eval=0x%02X "
        "on_release_before_eval=0x%02X on_release_after_eval=0x%02X "
        "on_second_press_before_eval=0x%02X "
        "on_second_press_after_eval=0x%02X tstates=%" PRIu64 "\n",
        single_read,
        same_column_read,
        rectangle_read,
        transitive_read,
        unwired_read,
        on_initial_status,
        on_enabled_status,
        on_press_before_eval,
        on_press_after_eval,
        on_held_after_ack,
        on_held_after_eval,
        on_release_before_eval,
        on_release_after_eval,
        on_second_press_before_eval,
        on_second_press_after_eval,
        timer.tstates
    );
    return 0;
}

void reset_programmable_timer(CPU_t *cpu) {
    cpu->timer_c->tstates = 0;
    cpu->timer_c->elapsed = 0.0;
    write_device_port(cpu, 0x30, 0x00);
    write_device_port(cpu, 0x31, 0x00);
}

void configure_programmable_timer(
    CPU_t *cpu,
    unsigned char source,
    unsigned char mode,
    unsigned char count
) {
    write_device_port(cpu, 0x30, source);
    write_device_port(cpu, 0x31, mode);
    write_device_port(cpu, 0x32, count);
}

std::uint32_t read_clock_word(CPU_t *cpu) {
    std::uint32_t value = 0;
    for (unsigned int index = 0; index < 4; ++index) {
        value |= static_cast<std::uint32_t>(
            read_device_port(cpu, static_cast<unsigned char>(0x45 + index))
        ) << (8 * index);
    }
    return value;
}

void write_clock_word(CPU_t *cpu, std::uint32_t value) {
    for (unsigned int index = 0; index < 4; ++index) {
        write_device_port(
            cpu,
            static_cast<unsigned char>(0x41 + index),
            static_cast<unsigned char>((value >> (8 * index)) & 0xFF)
        );
    }
}

int run_timer_edge_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s --timer-edge-probe INPUT.rom\n", argv[0]);
        return 2;
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);

    reset_programmable_timer(&cpu);
    configure_programmable_timer(&cpu, 0x41, 0x00, 0x03);
    timer.elapsed = 320.0 / 32768.0;
    const unsigned char crystal_first_read = read_device_port(&cpu, 0x32);
    const unsigned char crystal_second_read = read_device_port(&cpu, 0x32);
    const unsigned char crystal_third_read = read_device_port(&cpu, 0x32);
    const unsigned char crystal_status = read_device_port(&cpu, 0x31);
    const unsigned char crystal_port4 = read_device_port(&cpu, 0x04);

    reset_programmable_timer(&cpu);
    configure_programmable_timer(&cpu, 0x80, 0x00, 0x03);
    timer.tstates = 4;
    const unsigned char cpu_count_read = read_device_port(&cpu, 0x32);
    const unsigned char cpu_status = read_device_port(&cpu, 0x31);
    const unsigned char cpu_port4 = read_device_port(&cpu, 0x04);

    reset_programmable_timer(&cpu);
    configure_programmable_timer(&cpu, 0x80, 0x00, 0x00);
    timer.tstates = 257;
    const unsigned char zero_count_read = read_device_port(&cpu, 0x32);
    const unsigned char zero_status = read_device_port(&cpu, 0x31);
    const unsigned char zero_port4 = read_device_port(&cpu, 0x04);
    write_device_port(&cpu, 0x31, 0x00);
    const unsigned char acknowledged_status = read_device_port(&cpu, 0x31);
    const unsigned char acknowledged_port4 = read_device_port(&cpu, 0x04);

    reset_programmable_timer(&cpu);
    configure_programmable_timer(&cpu, 0x80, 0x02, 0x01);
    cpu.interrupt = FALSE;
    cpu.halt = TRUE;
    timer.tstates = 2;
    const unsigned char halted_count_read = read_device_port(&cpu, 0x32);
    const unsigned char halted_status = read_device_port(&cpu, 0x31);
    const bool interrupt_while_halted = cpu.interrupt != FALSE;
    cpu.halt = FALSE;
    read_device_port(&cpu, 0x32);
    const bool interrupt_after_resume = cpu.interrupt != FALSE;

    timer.tstates = 0;
    timer.elapsed = 0.0;
    const std::uint32_t rtc_initial = read_clock_word(&cpu);
    write_clock_word(&cpu, UINT32_C(0x12345678));
    write_device_port(&cpu, 0x40, 0x01);
    write_device_port(&cpu, 0x40, 0x03);
    const std::uint32_t rtc_committed = read_clock_word(&cpu);
    timer.elapsed = 10.75;
    const std::uint32_t rtc_running = read_clock_word(&cpu);
    write_device_port(&cpu, 0x40, 0x00);
    const std::uint32_t rtc_frozen = read_clock_word(&cpu);
    timer.elapsed = 100.0;
    const std::uint32_t rtc_late_disabled = read_clock_word(&cpu);

    std::printf(
        "mode=timer-edge-probe crystal_source=0x41 crystal_divisor=32 "
        "crystal_elapsed_ticks=320 crystal_reads=%02X,%02X,%02X "
        "crystal_status=0x%02X crystal_port4=0x%02X "
        "cpu_source=0x80 cpu_divisor=1 cpu_elapsed_tstates=4 "
        "cpu_count_read=0x%02X cpu_status=0x%02X cpu_port4=0x%02X "
        "zero_elapsed_tstates=257 zero_count_read=0x%02X "
        "zero_status=0x%02X zero_port4=0x%02X "
        "acknowledged_status=0x%02X acknowledged_port4=0x%02X "
        "halted_count_read=0x%02X halted_status=0x%02X "
        "interrupt_while_halted=%d interrupt_after_resume=%d "
        "rtc_initial=0x%08" PRIX32 " rtc_committed=0x%08" PRIX32 " "
        "rtc_running=0x%08" PRIX32 " rtc_frozen=0x%08" PRIX32 " "
        "rtc_late_disabled=0x%08" PRIX32 " final_elapsed=100\n",
        crystal_first_read,
        crystal_second_read,
        crystal_third_read,
        crystal_status,
        crystal_port4,
        cpu_count_read,
        cpu_status,
        cpu_port4,
        zero_count_read,
        zero_status,
        zero_port4,
        acknowledged_status,
        acknowledged_port4,
        halted_count_read,
        halted_status,
        interrupt_while_halted ? 1 : 0,
        interrupt_after_resume ? 1 : 0,
        rtc_initial,
        rtc_committed,
        rtc_running,
        rtc_frozen,
        rtc_late_disabled
    );
    return 0;
}

int run_asic_edge_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s --asic-edge-probe INPUT.rom\n", argv[0]);
        return 2;
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);

    const bool initial_flash_locked = memory.flash_locked != FALSE;
    const unsigned char port02_locked = read_device_port(&cpu, 0x02);
    const unsigned char port15_ram_v0 = read_device_port(&cpu, 0x15);
    memory.ram_version = 2;
    const unsigned char port15_ram_v2 = read_device_port(&cpu, 0x15);
    memory.ram_version = 0;

    const bool port39_active = cpu.pio.devices[0x39].active != FALSE;
    const DeviceReadResult port39_read = try_read_device_port(&cpu, 0x39);
    const bool port3a_active = cpu.pio.devices[0x3A].active != FALSE;
    const unsigned char port3a_initial = read_device_port(&cpu, 0x3A);
    write_device_port(&cpu, 0x3A, 0xA5);
    const unsigned char port3a_first_read = read_device_port(&cpu, 0x3A);
    write_device_port(&cpu, 0x3A, 0x5A);
    const unsigned char port3a_second_read = read_device_port(&cpu, 0x3A);

    const bool port21_active = cpu.pio.devices[0x21].active != FALSE;
    const bool port21_protected = cpu.pio.devices[0x21].protected_port != FALSE;
    const bool locked_write_accepted = try_write_device_port(&cpu, 0x21, 0x33);
    const unsigned char locked_read = read_device_port(&cpu, 0x21);
    const unsigned int locked_internal_mode = memory.prot_mode;
    const unsigned int locked_model_bits = cpu.model_bits;

    memory.flash_locked = FALSE;
    const unsigned char port02_unlocked = read_device_port(&cpu, 0x02);
    const bool mode3_write_accepted = try_write_device_port(&cpu, 0x21, 0x30);
    const unsigned char mode3_read = read_device_port(&cpu, 0x21);
    const unsigned int mode3_internal_mode = memory.prot_mode;
    const unsigned int mode3_model_bits = cpu.model_bits;
    const bool group3_write_accepted = try_write_device_port(&cpu, 0x21, 0x03);
    const unsigned char group3_read = read_device_port(&cpu, 0x21);
    const unsigned int group3_internal_mode = memory.prot_mode;
    const unsigned int group3_model_bits = cpu.model_bits;
    const bool combined_write_accepted = try_write_device_port(&cpu, 0x21, 0x33);
    const unsigned char combined_read = read_device_port(&cpu, 0x21);
    const unsigned int combined_internal_mode = memory.prot_mode;
    const unsigned int combined_model_bits = cpu.model_bits;
    memory.flash_locked = TRUE;

    std::printf(
        "mode=asic-edge-probe initial_flash_locked=%d "
        "port02_locked=0x%02X port02_unlocked=0x%02X "
        "port15_ram_v0=0x%02X port15_ram_v2=0x%02X "
        "port39_active=%d port39_read_accepted=%d port39_read=0x%02X "
        "port3a_active=%d port3a_initial=0x%02X "
        "port3a_first_written=0xA5 port3a_first_read=0x%02X "
        "port3a_second_written=0x5A port3a_second_read=0x%02X "
        "port21_active=%d port21_protected=%d "
        "locked_write_accepted=%d locked_read=0x%02X "
        "locked_internal_mode=%u locked_model_bits=%u "
        "mode3_write_accepted=%d mode3_written=0x30 mode3_read=0x%02X "
        "mode3_internal_mode=%u mode3_model_bits=%u "
        "group3_write_accepted=%d group3_written=0x03 group3_read=0x%02X "
        "group3_internal_mode=%u group3_model_bits=%u "
        "combined_write_accepted=%d combined_written=0x33 "
        "combined_read=0x%02X combined_internal_mode=%u "
        "combined_model_bits=%u tstates=%" PRIu64 "\n",
        initial_flash_locked ? 1 : 0,
        port02_locked,
        port02_unlocked,
        port15_ram_v0,
        port15_ram_v2,
        port39_active ? 1 : 0,
        port39_read.accepted ? 1 : 0,
        port39_read.value,
        port3a_active ? 1 : 0,
        port3a_initial,
        port3a_first_read,
        port3a_second_read,
        port21_active ? 1 : 0,
        port21_protected ? 1 : 0,
        locked_write_accepted ? 1 : 0,
        locked_read,
        locked_internal_mode,
        locked_model_bits,
        mode3_write_accepted ? 1 : 0,
        mode3_read,
        mode3_internal_mode,
        mode3_model_bits,
        group3_write_accepted ? 1 : 0,
        group3_read,
        group3_internal_mode,
        group3_model_bits,
        combined_write_accepted ? 1 : 0,
        combined_read,
        combined_internal_mode,
        combined_model_bits,
        timer.tstates
    );
    return 0;
}

void write_lcd_after(CPU_t *cpu, unsigned char port, unsigned char value, unsigned int delta) {
    cpu->timer_c->tstates += delta;
    write_device_port(cpu, port, value);
}

int run_lcd_edge_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s --lcd-edge-probe INPUT.rom\n", argv[0]);
        return 2;
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);
    LCD_t *lcd = reinterpret_cast<LCD_t *>(cpu.pio.lcd);
    lcd->base.last_tstate = 0;
    timer.tstates = 0;

    const bool port12_active = cpu.pio.devices[0x12].active != FALSE;
    const bool port13_active = cpu.pio.devices[0x13].active != FALSE;
    const DeviceReadResult port12_read = try_read_device_port(&cpu, 0x12);
    const DeviceReadResult port13_read = try_read_device_port(&cpu, 0x13);

    timer.tstates = 60;
    write_device_port(&cpu, 0x10, 0x03);
    timer.tstates = 119;
    const unsigned char early_status = read_device_port(&cpu, 0x10);
    timer.tstates = 120;
    const unsigned char boundary_status = read_device_port(&cpu, 0x10);
    const std::uint64_t status_last_tstate = lcd->base.last_tstate;

    write_lcd_after(&cpu, 0x10, 0x01, 60);
    write_lcd_after(&cpu, 0x10, 0x07, 60);
    write_lcd_after(&cpu, 0x10, 0x80, 60);
    write_lcd_after(&cpu, 0x10, 0x2E, 60);
    write_lcd_after(&cpu, 0x11, 0xA0, 60);
    write_lcd_after(&cpu, 0x11, 0xEE, 59);
    const unsigned char early_write_cell = lcd->display[0];
    const unsigned int early_write_column = lcd->base.y;
    write_lcd_after(&cpu, 0x11, 0xA1, 1);
    write_lcd_after(&cpu, 0x11, 0xA2, 60);
    write_lcd_after(&cpu, 0x11, 0xA3, 60);
    const unsigned char wrap_column14 = lcd->display[14];
    const unsigned char wrap_column15 = lcd->display[15];
    const unsigned char wrap_column0 = lcd->display[0];
    const unsigned char wrap_column1 = lcd->display[1];
    const unsigned char wrap_column2 = lcd->display[2];
    const unsigned int wrap_final_column = lcd->base.y;

    write_lcd_after(&cpu, 0x10, 0x81, 60);
    write_lcd_after(&cpu, 0x10, 0x2F, 60);
    write_lcd_after(&cpu, 0x11, 0xB5, 60);
    const unsigned char direct_column15 = lcd->display[31];
    write_lcd_after(&cpu, 0x10, 0x81, 60);
    write_lcd_after(&cpu, 0x10, 0x3F, 60);
    write_lcd_after(&cpu, 0x11, 0xBF, 60);
    const unsigned char alias_column31 = lcd->display[31];
    const unsigned int alias_final_column = lcd->base.y;

    write_lcd_after(&cpu, 0x10, 0x82, 60);
    write_lcd_after(&cpu, 0x10, 0x20, 60);
    write_lcd_after(&cpu, 0x11, 0x12, 60);
    write_lcd_after(&cpu, 0x11, 0x34, 60);
    write_lcd_after(&cpu, 0x10, 0x82, 60);
    write_lcd_after(&cpu, 0x10, 0x20, 60);
    timer.tstates += 60;
    const std::uint64_t latch_read_tstates = timer.tstates;
    const unsigned char latch_first = read_device_port(&cpu, 0x11);
    const unsigned char latch_second = read_device_port(&cpu, 0x11);
    const unsigned char latch_third = read_device_port(&cpu, 0x11);
    const std::uint64_t latch_last_tstate = lcd->base.last_tstate;
    const unsigned int latch_final_column = lcd->base.y;

    write_device_port(&cpu, 0x20, 0x01);
    write_device_port(&cpu, 0x2A, 0x00);
    write_device_port(&cpu, 0x2F, 0x03);
    timer.tstates = 2000;
    write_device_port(&cpu, 0x10, 0x03);
    const std::uint64_t ready_last_tstate = lcd->base.last_tstate;
    timer.tstates = 2240;
    const unsigned char ready_at_240 = read_device_port(&cpu, 0x02);
    timer.tstates = 2241;
    const unsigned char ready_at_241 = read_device_port(&cpu, 0x02);
    const unsigned char accepted_status_read = read_device_port(&cpu, 0x10);
    const std::uint64_t ready_after_read_last_tstate = lcd->base.last_tstate;
    const unsigned char ready_after_read = read_device_port(&cpu, 0x02);

    write_device_port(&cpu, 0x2A, 0x27);
    write_device_port(&cpu, 0x2E, 0x45);
    timer.tstates = 3000;
    const std::uint64_t delay_before = timer.tstates;
    const unsigned char delayed_status = read_device_port(&cpu, 0x10);
    const std::uint64_t delay_after = timer.tstates;
    write_device_port(&cpu, 0x20, 0x03);
    const unsigned char clamped_speed = read_device_port(&cpu, 0x20);

    std::printf(
        "mode=lcd-edge-probe configured_lcd_delay=60 "
        "port12_active=%d port12_read_accepted=%d port12_read=0x%02X "
        "port13_active=%d port13_read_accepted=%d port13_read=0x%02X "
        "early_status=0x%02X boundary_status=0x%02X "
        "status_last_tstate=%" PRIu64 " "
        "early_write_cell=0x%02X early_write_column=%u "
        "wrap_column14=0x%02X wrap_column15=0x%02X "
        "wrap_column0=0x%02X wrap_column1=0x%02X wrap_column2=0x%02X "
        "wrap_final_column=%u direct_column15=0x%02X "
        "alias_column31=0x%02X alias_final_column=%u "
        "latch_reads=%02X,%02X,%02X latch_read_tstates=%" PRIu64 " "
        "latch_last_tstate=%" PRIu64 " latch_final_column=%u "
        "ready_field=3 ready_hold=240 ready_last_tstate=%" PRIu64 " "
        "ready_at_240=0x%02X ready_at_241=0x%02X "
        "accepted_status_read=0x%02X "
        "ready_after_read_last_tstate=%" PRIu64 " ready_after_read=0x%02X "
        "delay_register=0x27 delay_before=%" PRIu64 " "
        "delay_after=%" PRIu64 " delayed_status=0x%02X "
        "flash_opcode_wait=%d flash_read_wait=%d flash_write_wait=%d "
        "ram_opcode_wait=%d ram_read_wait=%d ram_write_wait=%d "
        "requested_speed=3 clamped_speed=%u timer_version=%d\n",
        port12_active ? 1 : 0,
        port12_read.accepted ? 1 : 0,
        port12_read.value,
        port13_active ? 1 : 0,
        port13_read.accepted ? 1 : 0,
        port13_read.value,
        early_status,
        boundary_status,
        status_last_tstate,
        early_write_cell,
        early_write_column,
        wrap_column14,
        wrap_column15,
        wrap_column0,
        wrap_column1,
        wrap_column2,
        wrap_final_column,
        direct_column15,
        alias_column31,
        alias_final_column,
        latch_first,
        latch_second,
        latch_third,
        latch_read_tstates,
        latch_last_tstate,
        latch_final_column,
        ready_last_tstate,
        ready_at_240,
        ready_at_241,
        accepted_status_read,
        ready_after_read_last_tstate,
        ready_after_read,
        delay_before,
        delay_after,
        delayed_status,
        memory.read_OP_flash_tstates ? 1 : 0,
        memory.read_NOP_flash_tstates ? 1 : 0,
        memory.write_flash_tstates ? 1 : 0,
        memory.read_OP_ram_tstates ? 1 : 0,
        memory.read_NOP_ram_tstates ? 1 : 0,
        memory.write_ram_tstates ? 1 : 0,
        clamped_speed,
        timer.timer_version
    );
    return 0;
}

std::uint64_t visible_lcd_fnv1a64(const LCD_t &lcd) {
    std::uint64_t hash = UINT64_C(14695981039346656037);
    for (unsigned int row = 0; row < LCD_HEIGHT; ++row) {
        for (unsigned int column = 0; column < 12; ++column) {
            hash ^= lcd.display[row * LCD_MEM_WIDTH + column];
            hash *= UINT64_C(1099511628211);
        }
    }
    return hash;
}

int run_lcd_diagnostic_probe(int argc, char **argv) {
    if (argc < 3 || argc > 5) {
        std::fprintf(
            stderr,
            "usage: %s --lcd-diagnostic-probe INPUT.rom "
            "[MAX_BOOT_STEPS [MAX_PROBE_STEPS]]\n",
            argv[0]
        );
        return 2;
    }
    const std::uint64_t max_boot_steps =
        argc >= 4 ? parse_count(argv[3], "MAX_BOOT_STEPS") : UINT64_C(5000000);
    const std::uint64_t max_probe_steps =
        argc >= 5 ? parse_count(argv[4], "MAX_PROBE_STEPS") : UINT64_C(250000);
    if (max_boot_steps == 0 || max_probe_steps == 0) {
        fail("LCD diagnostic probe step bounds must be positive");
    }

    // The harness maps retail boot page 3F and directly calls its LCD helpers.
    // Marker PCs are the first instructions after each CALL.
    constexpr unsigned short init_marker = kProbeOrigin + 7;
    constexpr unsigned short fill_marker = kProbeOrigin + 14;
    constexpr unsigned short line_marker = kProbeOrigin + 21;
    constexpr unsigned short contrast_marker = kProbeOrigin + 29;
    const unsigned char harness[] = {
        0x3E, 0x3F, 0xD3, 0x06,
        0xCD, 0xC6, 0x74,
        0x16, 0x55, 0x1E, 0xAA, 0xCD, 0xEF, 0x46,
        0x06, 0xBF, 0x16, 0xFF, 0xCD, 0x2E, 0x47,
        0x3E, 0x27, 0x32, 0x47, 0x84, 0xCD, 0xF8, 0x74,
        0x76,
    };

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

    memory.boot_mapped = FALSE;
    memory.banks = memory.normal_banks;
    memory.port07 = 0x80 | kProbeRamPage;
    change_page(&memory, 2, kProbeRamPage, TRUE);
    const std::size_t program_physical =
        kProbeRamPage * PAGE_SIZE + mc_base(kProbeOrigin);
    std::memcpy(memory.ram + program_physical, harness, sizeof(harness));
    if (std::memcmp(
            memory.banks[2].addr + mc_base(kProbeOrigin),
            harness,
            sizeof(harness)
        ) != 0) {
        fail("injected LCD diagnostic harness does not read back from RAM");
    }

    LCD_t *lcd = reinterpret_cast<LCD_t *>(cpu.pio.lcd);
    std::memset(lcd->display, 0, sizeof(lcd->display));
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

    unsigned int init_visits = 0;
    unsigned int fill_visits = 0;
    unsigned int line_visits = 0;
    unsigned int contrast_visits = 0;
    unsigned int command_writes = 0;
    unsigned int data_writes = 0;
    unsigned int init_commands = 0;
    unsigned int init_data = 0;
    unsigned int fill_commands = 0;
    unsigned int fill_data = 0;
    unsigned int line_commands = 0;
    unsigned int line_data = 0;
    unsigned int contrast_commands = 0;
    unsigned int contrast_data = 0;
    unsigned int previous_commands = 0;
    unsigned int previous_data = 0;
    unsigned int init_active = 0;
    unsigned int init_word_length = 0;
    unsigned int init_cursor_mode = 0;
    std::uint64_t fill_hash = 0;
    std::uint64_t line_hash = 0;
    unsigned char fill_row0_col0 = 0;
    unsigned char fill_row1_col0 = 0;
    unsigned char fill_row0_col11 = 0;
    unsigned char fill_row0_col12 = 0;
    unsigned char line_row63_col0 = 0;
    unsigned char line_row63_col11 = 0;
    unsigned char line_row62_col0 = 0;
    unsigned char contrast_out = 0;

    std::uint64_t probe_steps = 0;
    for (; probe_steps < max_probe_steps && !cpu.halt; ++probe_steps) {
        const bank_state_t &pc_bank = memory.banks[mc_bank(cpu.pc)];
        const bool boot_page = !pc_bank.ram && pc_bank.page == 0x3F;
        if (boot_page && cpu.pc == 0x74C6) {
            ++init_visits;
        }
        if (boot_page && cpu.pc == 0x46EF) {
            ++fill_visits;
        }
        if (boot_page && cpu.pc == 0x472E) {
            ++line_visits;
        }
        if (boot_page && cpu.pc == 0x74F8) {
            ++contrast_visits;
        }
        if (cpu.pc == init_marker) {
            init_commands = command_writes - previous_commands;
            init_data = data_writes - previous_data;
            previous_commands = command_writes;
            previous_data = data_writes;
            init_active = lcd->base.active != FALSE;
            init_word_length = lcd->word_len;
            init_cursor_mode = static_cast<unsigned int>(lcd->base.cursor_mode);
        }
        if (cpu.pc == fill_marker) {
            fill_commands = command_writes - previous_commands;
            fill_data = data_writes - previous_data;
            previous_commands = command_writes;
            previous_data = data_writes;
            fill_hash = visible_lcd_fnv1a64(*lcd);
            fill_row0_col0 = lcd->display[0 * LCD_MEM_WIDTH + 0];
            fill_row1_col0 = lcd->display[1 * LCD_MEM_WIDTH + 0];
            fill_row0_col11 = lcd->display[0 * LCD_MEM_WIDTH + 11];
            fill_row0_col12 = lcd->display[0 * LCD_MEM_WIDTH + 12];
        }
        if (cpu.pc == line_marker) {
            line_commands = command_writes - previous_commands;
            line_data = data_writes - previous_data;
            previous_commands = command_writes;
            previous_data = data_writes;
            line_hash = visible_lcd_fnv1a64(*lcd);
            line_row63_col0 = lcd->display[63 * LCD_MEM_WIDTH + 0];
            line_row63_col11 = lcd->display[63 * LCD_MEM_WIDTH + 11];
            line_row62_col0 = lcd->display[62 * LCD_MEM_WIDTH + 0];
        }
        if (cpu.pc == contrast_marker) {
            contrast_commands = command_writes - previous_commands;
            contrast_data = data_writes - previous_data;
        }
        if (boot_page && mc_base(cpu.pc) + 1 < PAGE_SIZE &&
            pc_bank.addr[mc_base(cpu.pc)] == 0xD3) {
            const unsigned char port = pc_bank.addr[mc_base(cpu.pc) + 1];
            if (port == 0x10) {
                ++command_writes;
                contrast_out = cpu.a;
            } else if (port == 0x11) {
                ++data_writes;
            }
        }
        CPU_step(&cpu);
        if (execution_violation_resets != 0) {
            ++probe_steps;
            break;
        }
    }

    const bool completed = cpu.halt && execution_violation_resets == 0;
    std::printf(
        "mode=lcd-diagnostic-probe probe_size=%zu boot_steps=%" PRIu64 " "
        "boot_tstates=%" PRIu64 " max_probe_steps=%" PRIu64 " "
        "probe_steps=%" PRIu64 " probe_tstates=%" PRIu64 " "
        "init_visits=%u fill_visits=%u line_visits=%u contrast_visits=%u "
        "init_commands=%u init_data=%u fill_commands=%u fill_data=%u "
        "line_commands=%u line_data=%u contrast_commands=%u contrast_data=%u "
        "command_writes=%u data_writes=%u init_active=%u "
        "init_word_length=%u init_cursor_mode=%u "
        "fill_hash=0x%016" PRIx64 " line_hash=0x%016" PRIx64 " "
        "fill_row0_col0=0x%02X fill_row1_col0=0x%02X "
        "fill_row0_col11=0x%02X fill_row0_col12=0x%02X "
        "line_row63_col0=0x%02X line_row63_col11=0x%02X "
        "line_row62_col0=0x%02X contrast_out=0x%02X contrast_level=%u "
        "violation_resets=%u completed=%d final_pc=0x%04X\n",
        sizeof(harness),
        boot_steps,
        boot_tstates,
        max_probe_steps,
        probe_steps,
        timer.tstates - boot_tstates,
        init_visits,
        fill_visits,
        line_visits,
        contrast_visits,
        init_commands,
        init_data,
        fill_commands,
        fill_data,
        line_commands,
        line_data,
        contrast_commands,
        contrast_data,
        command_writes,
        data_writes,
        init_active,
        init_word_length,
        init_cursor_mode,
        fill_hash,
        line_hash,
        fill_row0_col0,
        fill_row1_col0,
        fill_row0_col11,
        fill_row0_col12,
        line_row63_col0,
        line_row63_col11,
        line_row62_col0,
        contrast_out,
        lcd->base.contrast,
        execution_violation_resets,
        static_cast<int>(completed),
        cpu.pc
    );
    return completed ? 0 : 3;
}

unsigned int memory_wait_mask(const memory_context_t &memory) {
    return
        (memory.read_OP_flash_tstates ? 0x01 : 0) |
        (memory.read_NOP_flash_tstates ? 0x02 : 0) |
        (memory.write_flash_tstates ? 0x04 : 0) |
        (memory.read_OP_ram_tstates ? 0x08 : 0) |
        (memory.read_NOP_ram_tstates ? 0x10 : 0) |
        (memory.write_ram_tstates ? 0x20 : 0);
}

int run_speed_edge_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s --speed-edge-probe INPUT.rom\n", argv[0]);
        return 2;
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);

    bool delay_ports_active[7];
    unsigned char reset_delay_reads[7];
    for (unsigned int index = 0; index < 7; ++index) {
        const unsigned char port = static_cast<unsigned char>(0x29 + index);
        delay_ports_active[index] = cpu.pio.devices[port].active != FALSE;
        reset_delay_reads[index] = read_device_port(&cpu, port);
    }
    const unsigned char reset_speed = read_device_port(&cpu, 0x20);
    const unsigned int reset_frequency = timer.freq;
    const int reset_timer_version = timer.timer_version;

    unsigned char default_speed_reads[4];
    unsigned int default_frequencies[4];
    for (unsigned int mode = 0; mode < 4; ++mode) {
        write_device_port(&cpu, 0x20, static_cast<unsigned char>(0xFC + mode));
        default_speed_reads[mode] = read_device_port(&cpu, 0x20);
        default_frequencies[mode] = timer.freq;
    }

    // Wabbitemu's front end can set this field; no calculator port does so.
    timer.timer_version = 1;
    unsigned char extra_speed_reads[4];
    unsigned int extra_frequencies[4];
    for (unsigned int mode = 0; mode < 4; ++mode) {
        write_device_port(&cpu, 0x20, static_cast<unsigned char>(0xFC + mode));
        extra_speed_reads[mode] = read_device_port(&cpu, 0x20);
        extra_frequencies[mode] = timer.freq;
    }

    unsigned char latch_written[7];
    unsigned char latch_reads[7];
    for (unsigned int index = 0; index < 7; ++index) {
        const unsigned char port = static_cast<unsigned char>(0x29 + index);
        latch_written[index] = static_cast<unsigned char>(0xA9 + index);
        write_device_port(&cpu, port, latch_written[index]);
        latch_reads[index] = read_device_port(&cpu, port);
    }

    write_device_port(&cpu, 0x29, 0x00);
    write_device_port(&cpu, 0x2A, 0x01);
    write_device_port(&cpu, 0x2B, 0x02);
    write_device_port(&cpu, 0x2C, 0x03);
    write_device_port(&cpu, 0x2E, 0x77);
    unsigned int wait_masks[4];
    for (unsigned int mode = 0; mode < 4; ++mode) {
        write_device_port(&cpu, 0x20, static_cast<unsigned char>(mode));
        wait_masks[mode] = memory_wait_mask(memory);
    }

    const unsigned int port2d_wait_before = memory_wait_mask(memory);
    const unsigned int port2d_frequency_before = timer.freq;
    const int port2d_timer_version_before = timer.timer_version;
    const XTAL_t port2d_xtal_before = cpu.pio.se_aux->xtal;
    const BOOL port2d_lcd_active_before = cpu.pio.lcd->active;
    const BOOL port2d_halt_before = cpu.halt;
    const BOOL port2d_interrupt_before = cpu.interrupt;
    const std::uint64_t port2d_tstates_before = timer.tstates;
    write_device_port(&cpu, 0x2D, 0x5A);
    const unsigned char port2d_read = read_device_port(&cpu, 0x2D);

    std::printf(
        "mode=speed-edge-probe port20_active=%d "
        "delay_ports_active=%d,%d,%d,%d,%d,%d,%d "
        "reset_speed=%u reset_frequency=%u reset_timer_version=%d "
        "reset_delay_reads=%02X,%02X,%02X,%02X,%02X,%02X,%02X "
        "default_speed_reads=%u,%u,%u,%u "
        "default_frequencies=%u,%u,%u,%u "
        "extra_speed_reads=%u,%u,%u,%u "
        "extra_frequencies=%u,%u,%u,%u "
        "latch_written=%02X,%02X,%02X,%02X,%02X,%02X,%02X "
        "latch_reads=%02X,%02X,%02X,%02X,%02X,%02X,%02X "
        "wait_masks=%02X,%02X,%02X,%02X "
        "port2d_written=0x5A port2d_read=0x%02X "
        "port2d_wait_unchanged=%d port2d_freq_unchanged=%d "
        "port2d_timer_version_unchanged=%d port2d_xtal_unchanged=%d "
        "port2d_lcd_active_unchanged=%d port2d_halt_unchanged=%d "
        "port2d_interrupt_unchanged=%d port2d_tstates_unchanged=%d "
        "tstates=%" PRIu64 "\n",
        cpu.pio.devices[0x20].active != FALSE ? 1 : 0,
        delay_ports_active[0] ? 1 : 0,
        delay_ports_active[1] ? 1 : 0,
        delay_ports_active[2] ? 1 : 0,
        delay_ports_active[3] ? 1 : 0,
        delay_ports_active[4] ? 1 : 0,
        delay_ports_active[5] ? 1 : 0,
        delay_ports_active[6] ? 1 : 0,
        reset_speed,
        reset_frequency,
        reset_timer_version,
        reset_delay_reads[0], reset_delay_reads[1], reset_delay_reads[2],
        reset_delay_reads[3], reset_delay_reads[4], reset_delay_reads[5],
        reset_delay_reads[6],
        default_speed_reads[0], default_speed_reads[1],
        default_speed_reads[2], default_speed_reads[3],
        default_frequencies[0], default_frequencies[1],
        default_frequencies[2], default_frequencies[3],
        extra_speed_reads[0], extra_speed_reads[1],
        extra_speed_reads[2], extra_speed_reads[3],
        extra_frequencies[0], extra_frequencies[1],
        extra_frequencies[2], extra_frequencies[3],
        latch_written[0], latch_written[1], latch_written[2], latch_written[3],
        latch_written[4], latch_written[5], latch_written[6],
        latch_reads[0], latch_reads[1], latch_reads[2], latch_reads[3],
        latch_reads[4], latch_reads[5], latch_reads[6],
        wait_masks[0], wait_masks[1], wait_masks[2], wait_masks[3],
        port2d_read,
        memory_wait_mask(memory) == port2d_wait_before ? 1 : 0,
        timer.freq == port2d_frequency_before ? 1 : 0,
        timer.timer_version == port2d_timer_version_before ? 1 : 0,
        std::memcmp(
            &cpu.pio.se_aux->xtal, &port2d_xtal_before, sizeof(XTAL_t)
        ) == 0 ? 1 : 0,
        cpu.pio.lcd->active == port2d_lcd_active_before ? 1 : 0,
        cpu.halt == port2d_halt_before ? 1 : 0,
        cpu.interrupt == port2d_interrupt_before ? 1 : 0,
        timer.tstates == port2d_tstates_before ? 1 : 0,
        timer.tstates
    );
    return 0;
}

int run_protection_port_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(
            stderr, "usage: %s --protection-port-probe INPUT.rom\n", argv[0]
        );
        return 2;
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);

    const unsigned char ports[5] = {0x22, 0x23, 0x24, 0x25, 0x26};
    bool port_active[5];
    bool port_protected[5];
    unsigned char initial_reads[5];
    bool locked_write_accepted[5];
    unsigned char locked_reads[5];
    const bool initial_flash_locked = memory.flash_locked != FALSE;
    const unsigned short initial_flash_lower = memory.flash_lower;
    const unsigned short initial_flash_upper = memory.flash_upper;
    const unsigned char initial_port24 = memory.port24;
    const unsigned short initial_ram_lower = memory.ram_lower;
    const unsigned short initial_ram_upper = memory.ram_upper;
    for (unsigned int index = 0; index < 5; ++index) {
        const unsigned char port = ports[index];
        port_active[index] = cpu.pio.devices[port].active != FALSE;
        port_protected[index] = cpu.pio.devices[port].protected_port != FALSE;
        initial_reads[index] = read_device_port(&cpu, port);
        locked_write_accepted[index] = try_write_device_port(
            &cpu, port, static_cast<unsigned char>(0xA2 + index)
        );
        locked_reads[index] = read_device_port(&cpu, port);
    }

    memory.flash_locked = FALSE;
    memory.flash_lower = 0x01A5;
    memory.flash_upper = 0x02B6;
    write_device_port(&cpu, 0x22, 0xCC);
    write_device_port(&cpu, 0x23, 0xDD);
    const unsigned char low_write_port22_read = read_device_port(&cpu, 0x22);
    const unsigned char low_write_port23_read = read_device_port(&cpu, 0x23);
    const unsigned short low_write_flash_lower = memory.flash_lower;
    const unsigned short low_write_flash_upper = memory.flash_upper;

    write_device_port(&cpu, 0x24, 0xFF);
    const unsigned char port24_read = read_device_port(&cpu, 0x24);
    const unsigned short port24_flash_lower = memory.flash_lower;
    const unsigned short port24_flash_upper = memory.flash_upper;

    const unsigned char wrap_values[4] = {0x3F, 0x40, 0x41, 0xFF};
    unsigned char ram_lower_reads[4];
    unsigned short ram_lower_internal[4];
    unsigned char ram_upper_reads[4];
    unsigned short ram_upper_internal[4];
    for (unsigned int index = 0; index < 4; ++index) {
        write_device_port(&cpu, 0x25, wrap_values[index]);
        ram_lower_reads[index] = read_device_port(&cpu, 0x25);
        ram_lower_internal[index] = memory.ram_lower;
        write_device_port(&cpu, 0x26, wrap_values[index]);
        ram_upper_reads[index] = read_device_port(&cpu, 0x26);
        ram_upper_internal[index] = memory.ram_upper;
    }

    std::printf(
        "mode=protection-port-probe "
        "port_active=%d,%d,%d,%d,%d port_protected=%d,%d,%d,%d,%d "
        "initial_flash_locked=%d initial_reads=%02X,%02X,%02X,%02X,%02X "
        "initial_flash_lower=0x%04X initial_flash_upper=0x%04X "
        "initial_port24=0x%02X initial_ram_lower=0x%04X "
        "initial_ram_upper=0x%04X "
        "locked_write_accepted=%d,%d,%d,%d,%d "
        "locked_reads=%02X,%02X,%02X,%02X,%02X "
        "configured_flash_locked=%d seeded_flash_lower=0x01A5 "
        "seeded_flash_upper=0x02B6 low_writes=CC,DD "
        "low_write_reads=%02X,%02X low_write_flash_lower=0x%04X "
        "low_write_flash_upper=0x%04X port24_written=0xFF "
        "port24_read=0x%02X port24_flash_lower=0x%04X "
        "port24_flash_upper=0x%04X wrap_values=3F,40,41,FF "
        "ram_lower_reads=%02X,%02X,%02X,%02X "
        "ram_lower_internal=%04X,%04X,%04X,%04X "
        "ram_upper_reads=%02X,%02X,%02X,%02X "
        "ram_upper_internal=%04X,%04X,%04X,%04X "
        "tstates=%" PRIu64 "\n",
        port_active[0] ? 1 : 0, port_active[1] ? 1 : 0,
        port_active[2] ? 1 : 0, port_active[3] ? 1 : 0,
        port_active[4] ? 1 : 0,
        port_protected[0] ? 1 : 0, port_protected[1] ? 1 : 0,
        port_protected[2] ? 1 : 0, port_protected[3] ? 1 : 0,
        port_protected[4] ? 1 : 0,
        initial_flash_locked ? 1 : 0,
        initial_reads[0], initial_reads[1], initial_reads[2],
        initial_reads[3], initial_reads[4],
        initial_flash_lower, initial_flash_upper, initial_port24,
        initial_ram_lower, initial_ram_upper,
        locked_write_accepted[0] ? 1 : 0,
        locked_write_accepted[1] ? 1 : 0,
        locked_write_accepted[2] ? 1 : 0,
        locked_write_accepted[3] ? 1 : 0,
        locked_write_accepted[4] ? 1 : 0,
        locked_reads[0], locked_reads[1], locked_reads[2],
        locked_reads[3], locked_reads[4],
        memory.flash_locked != FALSE ? 1 : 0,
        low_write_port22_read, low_write_port23_read,
        low_write_flash_lower, low_write_flash_upper,
        port24_read, port24_flash_lower, port24_flash_upper,
        ram_lower_reads[0], ram_lower_reads[1],
        ram_lower_reads[2], ram_lower_reads[3],
        ram_lower_internal[0], ram_lower_internal[1],
        ram_lower_internal[2], ram_lower_internal[3],
        ram_upper_reads[0], ram_upper_reads[1],
        ram_upper_reads[2], ram_upper_reads[3],
        ram_upper_internal[0], ram_upper_internal[1],
        ram_upper_internal[2], ram_upper_internal[3],
        timer.tstates
    );
    return 0;
}

int run_reset_retention_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(
            stderr, "usage: %s --reset-retention-probe INPUT.rom\n", argv[0]
        );
        return 2;
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);
    SE_AUX_t *se_aux = cpu.pio.se_aux;
    LCD_t *lcd = reinterpret_cast<LCD_t *>(cpu.pio.lcd);

    cpu.af = 0xA1F1;
    cpu.bc = 0xB2C2;
    cpu.de = 0xD3E3;
    cpu.hl = 0xE4F4;
    cpu.afp = 0x1525;
    cpu.bcp = 0x2636;
    cpu.dep = 0x3747;
    cpu.hlp = 0x4858;
    cpu.ix = 0x5969;
    cpu.iy = 0x6A7A;
    cpu.pc = 0x4567;
    cpu.sp = 0x89AB;
    cpu.i = 0x12;
    cpu.r = 0x34;
    cpu.bus = 0x56;
    cpu.link_write = 0x03;
    cpu.model_bits = 3;
    cpu.imode = 2;
    cpu.interrupt = TRUE;
    cpu.ei_block = TRUE;
    cpu.iff1 = TRUE;
    cpu.iff2 = TRUE;
    cpu.halt = TRUE;
    cpu.read = TRUE;
    cpu.write = TRUE;
    cpu.output = TRUE;
    cpu.input = TRUE;
    cpu.prefix = 0xDD;

    memory.ram[0x1234] = 0xA5;
    memory.step = FLASH_FASTMODE_PROG;
    memory.flash_write_delay = 0x12345678;
    memory.flash_locked = FALSE;
    memory.flash_write_byte = 0x5A;
    memory.flash_error = TRUE;
    memory.flash_toggles = 0x40;
    memory.flash_lower = 0x01CC;
    memory.flash_upper = 0x02DD;
    memory.port24 = 0xEE;
    memory.ram_lower = 0x4000;
    memory.ram_upper = 0x83FF;
    memory.prot_mode = MODE3;
    memory.port06 = 0x12;
    memory.port07 = 0x85;
    memory.port0E = 0x34;
    memory.port0F = 0x56;
    memory.port27_remap_count = 0x12;
    memory.port28_remap_count = 0x34;
    memory.boot_mapped = TRUE;
    memory.banks = memory.bootmap_banks;
    memory.hasChangedPage0 = TRUE;
    for (unsigned int index = 0; index < 4; ++index) {
        memory.protected_page[index] = static_cast<int>(index + 1);
    }
    memory.protected_page_set = 2;

    timer.tstates = 123456;
    timer.freq = MHZ_25;
    timer.elapsed = 12.5;
    timer.lasttime = 34.5;
    timer.timer_version = 1;

    for (unsigned int index = 0; index < 7; ++index) {
        se_aux->delay.reg[index] = static_cast<unsigned char>(0xA0 + index);
    }
    se_aux->md5.a = 0x12345678;
    se_aux->md5.s = 0x1A;
    se_aux->md5.mode = 3;
    se_aux->linka.link_enable = 0xD4;
    se_aux->linka.in = 0xA5;
    se_aux->linka.out = 0x5A;
    se_aux->linka.working = 0x33;
    se_aux->xtal.ticks = 0x1234;
    se_aux->xtal.timers[0].clock = 0x80;
    se_aux->xtal.timers[0].count = 0x22;
    se_aux->xtal.timers[0].active = TRUE;
    se_aux->clock.enable = 3;
    se_aux->clock.set = 0x12345678;
    se_aux->clock.base = 0x23456789;
    se_aux->clock.lasttime = 45.5;
    se_aux->usb.USBLineState = 0xE5;
    se_aux->usb.USBEvents = 0x58;
    se_aux->usb.USBEventMask = 0xFF;
    se_aux->usb.LineInterrupt = TRUE;
    se_aux->gpio = 0x5A;

    cpu.pio.stdint->intactive = 0xA5;
    cpu.pio.stdint->mem = 0x5A;
    cpu.pio.stdint->on_latch = TRUE;
    cpu.pio.keypad->group = 0xFE;
    cpu.pio.keypad->keys[0][0] = KEY_STATEDOWN;
    cpu.pio.keypad->on_pressed = KEY_STATEDOWN;
    cpu.pio.link->host = 0x01;
    cpu.pio.link->client[0] = 0x02;

    lcd->base.active = TRUE;
    lcd->base.x = 4;
    lcd->base.y = 5;
    lcd->base.z = 6;
    lcd->base.contrast = 17;
    lcd->base.last_tstate = 654321;
    lcd->word_len = 6;
    lcd->lcd_delay = 61;
    lcd->last_read = 0xA5;
    lcd->display[0] = 0x5A;

    const DELAY_t delay_before = se_aux->delay;
    const MD5_t md5_before = se_aux->md5;
    const LINKASSIST_t linka_before = se_aux->linka;
    const XTAL_t xtal_before = se_aux->xtal;
    const CLOCK_t clock_before = se_aux->clock;
    const USB_t usb_before = se_aux->usb;
    const STDINT_t stdint_before = *cpu.pio.stdint;
    const keypad_t keypad_before = *cpu.pio.keypad;
    const LCD_t lcd_before = *lcd;

    CPU_reset(&cpu);

    bool protected_pages_clear = memory.protected_page_set == 0;
    for (unsigned int index = 0; index < 4; ++index) {
        protected_pages_clear = protected_pages_clear &&
            memory.protected_page[index] == 0;
    }
    const bool cpu_general_retained =
        cpu.af == 0xA1F1 && cpu.bc == 0xB2C2 && cpu.de == 0xD3E3 &&
        cpu.hl == 0xE4F4 && cpu.afp == 0x1525 && cpu.bcp == 0x2636 &&
        cpu.dep == 0x3747 && cpu.hlp == 0x4858 && cpu.ix == 0x5969 &&
        cpu.iy == 0x6A7A && cpu.i == 0x12 && cpu.r == 0x34 &&
        cpu.bus == 0x56 && cpu.link_write == 0x03 && cpu.model_bits == 3;
    const bool flash_command_retained =
        memory.step == FLASH_FASTMODE_PROG &&
        memory.flash_write_delay == 0x12345678 && !memory.flash_locked &&
        memory.flash_write_byte == 0x5A && memory.flash_error &&
        memory.flash_toggles == 0x40;
    const bool flash_bounds_retained =
        memory.flash_lower == 0x01CC && memory.flash_upper == 0x02DD &&
        memory.port24 == 0xEE;
    const bool protection_selectors_retained =
        memory.prot_mode == MODE3 && memory.port06 == 0x12 &&
        memory.port07 == 0x85 && memory.port0E == 0x34 &&
        memory.port0F == 0x56;
    const bool raw_link_retained =
        cpu.pio.link->host == 0x02 && cpu.pio.link->client[0] == 0x02;
    const bool usb_gpio_retained =
        std::memcmp(&se_aux->usb, &usb_before, sizeof(USB_t)) == 0 &&
        se_aux->gpio == 0x5A;
    const bool retained[14] = {
        cpu_general_retained,
        memory.ram[0x1234] == 0xA5,
        flash_command_retained,
        flash_bounds_retained,
        protection_selectors_retained,
        timer.tstates == 123456 && timer.freq == MHZ_25 &&
            timer.elapsed == 12.5 && timer.lasttime == 34.5 &&
            timer.timer_version == 1,
        std::memcmp(&se_aux->delay, &delay_before, sizeof(DELAY_t)) == 0,
        std::memcmp(&se_aux->md5, &md5_before, sizeof(MD5_t)) == 0,
        std::memcmp(cpu.pio.stdint, &stdint_before, sizeof(STDINT_t)) == 0,
        std::memcmp(cpu.pio.keypad, &keypad_before, sizeof(keypad_t)) == 0,
        raw_link_retained &&
            std::memcmp(&se_aux->linka, &linka_before, sizeof(LINKASSIST_t)) == 0,
        std::memcmp(&se_aux->xtal, &xtal_before, sizeof(XTAL_t)) == 0 &&
            std::memcmp(&se_aux->clock, &clock_before, sizeof(CLOCK_t)) == 0,
        usb_gpio_retained,
        std::memcmp(lcd, &lcd_before, sizeof(LCD_t)) == 0,
    };

    const unsigned short reset_pc = cpu.pc;
    const unsigned short reset_sp = cpu.sp;
    const int reset_imode = cpu.imode;
    const bool reset_interrupt = cpu.interrupt != FALSE;
    const bool reset_ei_block = cpu.ei_block != FALSE;
    const bool reset_iff1 = cpu.iff1 != FALSE;
    const bool reset_iff2 = cpu.iff2 != FALSE;
    const bool reset_halt = cpu.halt != FALSE;
    const bool reset_io_flags =
        cpu.read || cpu.write || cpu.output || cpu.input;
    const int reset_prefix = cpu.prefix;
    const unsigned short reset_ram_lower = memory.ram_lower;
    const unsigned short reset_ram_upper = memory.ram_upper;
    const int reset_port27 = memory.port27_remap_count;
    const int reset_port28 = memory.port28_remap_count;
    const bool reset_boot_mapped = memory.boot_mapped != FALSE;
    const bool reset_page0_changed = memory.hasChangedPage0 != FALSE;
    const bool reset_banks_normal = memory.banks == memory.normal_banks;
    const unsigned char reset_pages[4] = {
        static_cast<unsigned char>(memory.banks[0].page),
        static_cast<unsigned char>(memory.banks[1].page),
        static_cast<unsigned char>(memory.banks[2].page),
        static_cast<unsigned char>(memory.banks[3].page),
    };
    const bool reset_page_ram[4] = {
        memory.banks[0].ram != FALSE,
        memory.banks[1].ram != FALSE,
        memory.banks[2].ram != FALSE,
        memory.banks[3].ram != FALSE,
    };
    const char *reset_flash_step = flash_step_name(memory.step);
    const bool reset_flash_locked = memory.flash_locked != FALSE;
    const bool reset_flash_error = memory.flash_error != FALSE;
    const unsigned char reset_flash_toggle = memory.flash_toggles;
    const unsigned char reset_flash_write_byte = memory.flash_write_byte;
    const std::uint64_t reset_flash_delay = memory.flash_write_delay;
    const unsigned short reset_flash_lower = memory.flash_lower;
    const unsigned short reset_flash_upper = memory.flash_upper;
    const unsigned char reset_port24 = memory.port24;
    const int reset_prot_mode = memory.prot_mode;
    const unsigned char reset_selectors[4] = {
        memory.port06, memory.port07, memory.port0E, memory.port0F,
    };
    const unsigned char reset_ram_marker = memory.ram[0x1234];
    const std::uint64_t reset_timer_tstates = timer.tstates;
    const unsigned int reset_timer_freq = timer.freq;
    const int reset_timer_version = timer.timer_version;

    CPU_reset(&cpu);
    cpu.pio.lcd->reset(&cpu);
    const bool frontend_non_lcd_retained =
        memory.step == FLASH_FASTMODE_PROG &&
        std::memcmp(&se_aux->md5, &md5_before, sizeof(MD5_t)) == 0 &&
        timer.freq == MHZ_25 && timer.timer_version == 1;
    const bool frontend_display_clear = lcd->display[0] == 0;

    memory.flash_lower = 0;
    memory.flash_upper = 1;
    memory.step = FLASH_PROGRAM;
    memory.flash_error = FALSE;
    memory.read_OP_flash_tstates = 0;
    change_page(&memory, 1, 1, FALSE);
    memory.banks = memory.normal_banks;
    memory.boot_mapped = FALSE;
    memory.hasChangedPage0 = TRUE;
    cpu.pc = 0x4000;
    cpu.sp = 0x7777;
    cpu.af = 0xA5F5;
    cpu.bc = 0xB6C6;
    cpu.exe_violation_callback = nullptr;
    timer.tstates = 0;
    CPU_step(&cpu);
    const unsigned short program_violation_pc = cpu.pc;
    const unsigned short program_violation_af = cpu.af;
    const unsigned short program_violation_bc = cpu.bc;
    const unsigned short program_violation_sp = cpu.sp;
    const std::uint64_t program_violation_tstates = timer.tstates;
    const char *program_violation_flash_step = flash_step_name(memory.step);
    const bool program_violation_flash_error = memory.flash_error != FALSE;

    memory.flash_lower = 0;
    memory.flash_upper = 1;
    memory.step = FLASH_ERROR;
    memory.flash_error = TRUE;
    change_page(&memory, 1, 1, FALSE);
    memory.banks = memory.normal_banks;
    memory.boot_mapped = FALSE;
    memory.hasChangedPage0 = TRUE;
    cpu.pc = 0x4000;
    cpu.sp = 0x8888;
    cpu.af = 0xB5E5;
    cpu.bc = 0xC6D6;
    timer.tstates = 0;
    CPU_step(&cpu);

    std::printf(
        "mode=reset-retention-probe reset_pc=0x%04X reset_sp=0x%04X "
        "reset_imode=%d reset_interrupt=%d reset_ei_block=%d "
        "reset_iff1=%d reset_iff2=%d reset_halt=%d reset_io_flags=%d "
        "reset_prefix=%d cpu_general_retained=%d "
        "reset_ram_lower=0x%04X reset_ram_upper=0x%04X "
        "reset_port27=%d reset_port28=%d reset_boot_mapped=%d "
        "reset_page0_changed=%d reset_banks_normal=%d "
        "protected_pages_clear=%d reset_pages=%02X,%02X,%02X,%02X "
        "reset_page_ram=%d,%d,%d,%d "
        "retained=%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d "
        "reset_flash_step=%s reset_flash_locked=%d "
        "reset_flash_error=%d reset_flash_toggle=0x%02X "
        "reset_flash_write_byte=0x%02X reset_flash_delay=%" PRIu64 " "
        "reset_flash_lower=0x%04X reset_flash_upper=0x%04X "
        "reset_port24=0x%02X reset_prot_mode=%d "
        "reset_selectors=%02X,%02X,%02X,%02X reset_ram_marker=0x%02X "
        "reset_timer_tstates=%" PRIu64 " reset_timer_freq=%u "
        "reset_timer_version=%d frontend_lcd_active=%d "
        "frontend_lcd_x=%u frontend_lcd_y=%u frontend_lcd_z=%u "
        "frontend_lcd_contrast=%u frontend_lcd_word_len=%u "
        "frontend_lcd_last_read=0x%02X frontend_lcd_display_clear=%d "
        "frontend_lcd_last_tstate=%lld frontend_lcd_delay=%u "
        "frontend_non_lcd_retained=%d "
        "program_violation_pc=0x%04X program_violation_af=0x%04X "
        "program_violation_bc=0x%04X program_violation_sp=0x%04X "
        "program_violation_tstates=%" PRIu64 " "
        "program_violation_flash_step=%s program_violation_flash_error=%d "
        "error_violation_pc=0x%04X error_violation_af=0x%04X "
        "error_violation_bc=0x%04X error_violation_sp=0x%04X "
        "error_violation_tstates=%" PRIu64 " "
        "error_violation_flash_step=%s error_violation_flash_error=%d\n",
        reset_pc, reset_sp, reset_imode,
        reset_interrupt ? 1 : 0, reset_ei_block ? 1 : 0,
        reset_iff1 ? 1 : 0, reset_iff2 ? 1 : 0,
        reset_halt ? 1 : 0, reset_io_flags ? 1 : 0, reset_prefix,
        cpu_general_retained ? 1 : 0,
        reset_ram_lower, reset_ram_upper, reset_port27, reset_port28,
        reset_boot_mapped ? 1 : 0, reset_page0_changed ? 1 : 0,
        reset_banks_normal ? 1 : 0, protected_pages_clear ? 1 : 0,
        reset_pages[0], reset_pages[1], reset_pages[2], reset_pages[3],
        reset_page_ram[0] ? 1 : 0, reset_page_ram[1] ? 1 : 0,
        reset_page_ram[2] ? 1 : 0, reset_page_ram[3] ? 1 : 0,
        retained[0] ? 1 : 0, retained[1] ? 1 : 0,
        retained[2] ? 1 : 0, retained[3] ? 1 : 0,
        retained[4] ? 1 : 0, retained[5] ? 1 : 0,
        retained[6] ? 1 : 0, retained[7] ? 1 : 0,
        retained[8] ? 1 : 0, retained[9] ? 1 : 0,
        retained[10] ? 1 : 0, retained[11] ? 1 : 0,
        retained[12] ? 1 : 0, retained[13] ? 1 : 0,
        reset_flash_step, reset_flash_locked ? 1 : 0,
        reset_flash_error ? 1 : 0, reset_flash_toggle,
        reset_flash_write_byte, reset_flash_delay,
        reset_flash_lower, reset_flash_upper, reset_port24, reset_prot_mode,
        reset_selectors[0], reset_selectors[1],
        reset_selectors[2], reset_selectors[3], reset_ram_marker,
        reset_timer_tstates, reset_timer_freq, reset_timer_version,
        lcd->base.active ? 1 : 0, lcd->base.x, lcd->base.y, lcd->base.z,
        lcd->base.contrast, lcd->word_len, lcd->last_read,
        frontend_display_clear ? 1 : 0,
        static_cast<long long>(lcd->base.last_tstate), lcd->lcd_delay,
        frontend_non_lcd_retained ? 1 : 0,
        program_violation_pc, program_violation_af, program_violation_bc,
        program_violation_sp, program_violation_tstates,
        program_violation_flash_step,
        program_violation_flash_error ? 1 : 0,
        cpu.pc, cpu.af, cpu.bc, cpu.sp, timer.tstates,
        flash_step_name(memory.step), memory.flash_error ? 1 : 0
    );
    return 0;
}

std::uint64_t seconds_to_nanoseconds(double seconds) {
    return static_cast<std::uint64_t>(std::llround(seconds * 1000000000.0));
}

int run_interrupt_edge_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s --interrupt-edge-probe INPUT.rom\n", argv[0]);
        return 2;
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);
    STDINT_t *stdint = cpu.pio.stdint;

    const unsigned char initial_mask = read_device_port(&cpu, 0x03);
    write_device_port(&cpu, 0x03, 0xFF);
    const unsigned char stored_mask = read_device_port(&cpu, 0x03);
    stdint->on_latch = TRUE;
    const bool on_latch_before_ack = stdint->on_latch != FALSE;
    write_device_port(&cpu, 0x03, 0xFE);
    const bool on_latch_after_ack = stdint->on_latch != FALSE;
    const unsigned char mask_after_on_ack = read_device_port(&cpu, 0x03);

    write_device_port(&cpu, 0x04, 0x00);
    const std::uint64_t rate0_timer1_ns = seconds_to_nanoseconds(stdint->timermax1);
    write_device_port(&cpu, 0x04, 0x02);
    const std::uint64_t rate1_timer1_ns = seconds_to_nanoseconds(stdint->timermax1);
    write_device_port(&cpu, 0x04, 0x04);
    const std::uint64_t rate2_timer1_ns = seconds_to_nanoseconds(stdint->timermax1);
    write_device_port(&cpu, 0x04, 0x06);
    const std::uint64_t rate3_timer1_ns = seconds_to_nanoseconds(stdint->timermax1);
    const std::uint64_t rate3_timer2_ns = seconds_to_nanoseconds(stdint->timermax2);
    const std::uint64_t rate3_timer2_offset_ns = seconds_to_nanoseconds(
        stdint->lastchk2 - stdint->lastchk1
    );

    stdint->lastchk1 = 0;
    write_device_port(&cpu, 0x03, 0x0A);
    timer.elapsed = stdint->timermax1;
    const unsigned char exact_boundary_status = read_device_port(&cpu, 0x04);
    cpu.interrupt = FALSE;
    evaluate_device_port(&cpu, 0x03, "interrupt probe");
    const bool exact_boundary_interrupt = cpu.interrupt != FALSE;
    timer.elapsed = std::nextafter(
        stdint->timermax1, std::numeric_limits<double>::infinity()
    );
    const unsigned char after_boundary_status = read_device_port(&cpu, 0x04);
    cpu.interrupt = FALSE;
    evaluate_device_port(&cpu, 0x03, "interrupt probe");
    const bool after_boundary_interrupt = cpu.interrupt != FALSE;

    write_device_port(&cpu, 0x03, 0x08);
    write_device_port(&cpu, 0x03, 0x0A);
    const unsigned char after_port3_ack_status = read_device_port(&cpu, 0x04);
    timer.elapsed = std::nextafter(
        stdint->lastchk1 + stdint->timermax1,
        std::numeric_limits<double>::infinity()
    );
    const unsigned char before_port2_ack_status = read_device_port(&cpu, 0x04);
    write_device_port(&cpu, 0x02, 0x00);
    const unsigned char after_port2_ack_status = read_device_port(&cpu, 0x04);

    write_device_port(&cpu, 0x03, 0x08);
    cpu.pio.se_aux->xtal.timers[0].underflow = TRUE;
    cpu.pio.se_aux->xtal.timers[1].underflow = TRUE;
    cpu.pio.se_aux->xtal.timers[2].underflow = TRUE;
    const unsigned char completion_status = read_device_port(&cpu, 0x04);

    cpu.pio.lcd->active = TRUE;
    cpu.halt = TRUE;
    write_device_port(&cpu, 0x03, 0x00);
    const bool low_power_lcd_active = cpu.pio.lcd->active != FALSE;
    write_device_port(&cpu, 0x03, 0x08);
    const bool restored_lcd_active = cpu.pio.lcd->active != FALSE;

    std::printf(
        "mode=interrupt-edge-probe initial_mask=0x%02X stored_mask=0x%02X "
        "on_latch_before_ack=%d on_latch_after_ack=%d "
        "mask_after_on_ack=0x%02X "
        "rate0_timer1_ns=%" PRIu64 " rate1_timer1_ns=%" PRIu64 " "
        "rate2_timer1_ns=%" PRIu64 " rate3_timer1_ns=%" PRIu64 " "
        "rate3_timer2_ns=%" PRIu64 " rate3_timer2_offset_ns=%" PRIu64 " "
        "exact_boundary_status=0x%02X exact_boundary_interrupt=%d "
        "after_boundary_status=0x%02X after_boundary_interrupt=%d "
        "after_port3_ack_status=0x%02X before_port2_ack_status=0x%02X "
        "after_port2_ack_status=0x%02X "
        "completion_status=0x%02X low_power_lcd_active=%d "
        "restored_lcd_active=%d tstates=%" PRIu64 "\n",
        initial_mask,
        stored_mask,
        on_latch_before_ack ? 1 : 0,
        on_latch_after_ack ? 1 : 0,
        mask_after_on_ack,
        rate0_timer1_ns,
        rate1_timer1_ns,
        rate2_timer1_ns,
        rate3_timer1_ns,
        rate3_timer2_ns,
        rate3_timer2_offset_ns,
        exact_boundary_status,
        exact_boundary_interrupt ? 1 : 0,
        after_boundary_status,
        after_boundary_interrupt ? 1 : 0,
        after_port3_ack_status,
        before_port2_ack_status,
        after_port2_ack_status,
        completion_status,
        low_power_lcd_active ? 1 : 0,
        restored_lcd_active ? 1 : 0,
        timer.tstates
    );
    return 0;
}

int run_link_edge_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s --link-edge-probe INPUT.rom\n", argv[0]);
        return 2;
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);
    link_t *link = cpu.pio.link;
    LINKASSIST_t *assist = &cpu.pio.se_aux->linka;
    unsigned char peer = 0;
    link->client = &peer;

    const bool port08_active = cpu.pio.devices[0x08].active != FALSE;
    const bool port09_active = cpu.pio.devices[0x09].active != FALSE;
    const bool port0a_active = cpu.pio.devices[0x0A].active != FALSE;
    const bool port0b_active = cpu.pio.devices[0x0B].active != FALSE;
    const bool port0c_active = cpu.pio.devices[0x0C].active != FALSE;
    const bool port0d_active = cpu.pio.devices[0x0D].active != FALSE;
    const DeviceReadResult port0b_read = try_read_device_port(&cpu, 0x0B);
    const DeviceReadResult port0c_read = try_read_device_port(&cpu, 0x0C);
    const unsigned char initial_enable = read_device_port(&cpu, 0x08);
    const unsigned char initial_status = read_device_port(&cpu, 0x09);
    const unsigned char initial_in = read_device_port(&cpu, 0x0A);
    const unsigned char initial_out = read_device_port(&cpu, 0x0D);

    std::vector<unsigned char> raw_reads;
    for (unsigned int local = 0; local < 4; ++local) {
        for (unsigned int remote = 0; remote < 4; ++remote) {
            peer = static_cast<unsigned char>(remote);
            write_device_port(&cpu, 0x00, static_cast<unsigned char>(local));
            raw_reads.push_back(read_device_port(&cpu, 0x00));
        }
    }
    peer = 0;
    write_device_port(&cpu, 0x00, 0xA6);
    const unsigned char raw_high_write = read_device_port(&cpu, 0x00);
    write_device_port(&cpu, 0x00, 0x00);
    write_device_port(&cpu, 0x03, 0x10);
    cpu.interrupt = FALSE;
    peer = 1;
    const unsigned char raw_peer_read = read_device_port(&cpu, 0x00);
    const bool raw_peer_interrupt = cpu.interrupt != FALSE;
    peer = 0;

    write_device_port(&cpu, 0x08, 0x80);
    write_device_port(&cpu, 0x08, 0x02);
    cpu.interrupt = FALSE;
    evaluate_device_port(&cpu, 0x09, "link probe");
    const bool idle_ready_interrupt = cpu.interrupt != FALSE;
    const unsigned char idle_ready_status = read_device_port(&cpu, 0x09);
    read_device_port(&cpu, 0x0D);
    const unsigned char idle_after_out_status = read_device_port(&cpu, 0x09);

    write_device_port(&cpu, 0x08, 0x80);
    read_device_port(&cpu, 0x0D);
    write_device_port(&cpu, 0x08, 0x02);
    write_device_port(&cpu, 0x0D, 0xA5);
    cpu.interrupt = FALSE;
    std::vector<unsigned char> assist_send_drives;
    for (unsigned int bit = 0; bit < 8; ++bit) {
        peer = 0;
        evaluate_device_port(&cpu, 0x09, "link probe");
        assist_send_drives.push_back(link->host & 3);
        peer = static_cast<unsigned char>((link->host & 1) ? 2 : 1);
        evaluate_device_port(&cpu, 0x09, "link probe");
    }
    peer = 0;
    evaluate_device_port(&cpu, 0x09, "link probe");
    const bool assist_send_interrupt = cpu.interrupt != FALSE;
    const unsigned char assist_send_status = read_device_port(&cpu, 0x09);
    const unsigned char assist_send_out = read_device_port(&cpu, 0x0D);
    const unsigned char assist_send_after_out_status = read_device_port(&cpu, 0x09);

    write_device_port(&cpu, 0x08, 0x80);
    read_device_port(&cpu, 0x0D);
    write_device_port(&cpu, 0x08, 0x01);
    cpu.interrupt = FALSE;
    constexpr unsigned char receive_byte = 0xA5;
    for (unsigned int bit = 0; bit < 8; ++bit) {
        peer = static_cast<unsigned char>((receive_byte & (1 << bit)) ? 2 : 1);
        evaluate_device_port(&cpu, 0x09, "link probe");
        peer = 0;
        evaluate_device_port(&cpu, 0x09, "link probe");
    }
    const bool assist_receive_interrupt = cpu.interrupt != FALSE;
    const unsigned char assist_receive_status = read_device_port(&cpu, 0x09);
    const unsigned char assist_receive_in = read_device_port(&cpu, 0x0A);
    const unsigned char assist_receive_after_in_status = read_device_port(&cpu, 0x09);

    write_device_port(&cpu, 0x08, 0x80);
    read_device_port(&cpu, 0x0D);
    write_device_port(&cpu, 0x08, 0x04);
    assist->error = TRUE;
    peer = 1;
    cpu.interrupt = FALSE;
    evaluate_device_port(&cpu, 0x09, "link probe");
    const bool assist_error_interrupt = cpu.interrupt != FALSE;
    const unsigned char assist_error_status = read_device_port(&cpu, 0x09);
    const unsigned char assist_error_after_read_status = read_device_port(&cpu, 0x09);

    std::printf(
        "mode=link-edge-probe "
        "port08_active=%d port09_active=%d port0a_active=%d "
        "port0b_active=%d port0b_read_accepted=%d port0b_read=0x%02X "
        "port0c_active=%d port0c_read_accepted=%d port0c_read=0x%02X "
        "port0d_active=%d initial_enable=0x%02X initial_status=0x%02X "
        "initial_in=0x%02X initial_out=0x%02X raw_reads=",
        port08_active ? 1 : 0,
        port09_active ? 1 : 0,
        port0a_active ? 1 : 0,
        port0b_active ? 1 : 0,
        port0b_read.accepted ? 1 : 0,
        port0b_read.value,
        port0c_active ? 1 : 0,
        port0c_read.accepted ? 1 : 0,
        port0c_read.value,
        port0d_active ? 1 : 0,
        initial_enable,
        initial_status,
        initial_in,
        initial_out
    );
    for (std::size_t index = 0; index < raw_reads.size(); ++index) {
        std::printf("%s%02X", index == 0 ? "" : ",", raw_reads[index]);
    }
    std::printf(
        " raw_high_write=0x%02X raw_peer_read=0x%02X "
        "raw_peer_interrupt=%d idle_ready_status=0x%02X "
        "idle_ready_interrupt=%d idle_after_out_status=0x%02X "
        "assist_send_drives=",
        raw_high_write,
        raw_peer_read,
        raw_peer_interrupt ? 1 : 0,
        idle_ready_status,
        idle_ready_interrupt ? 1 : 0,
        idle_after_out_status
    );
    for (std::size_t index = 0; index < assist_send_drives.size(); ++index) {
        std::printf(
            "%s%02X", index == 0 ? "" : ",", assist_send_drives[index]
        );
    }
    std::printf(
        " assist_send_status=0x%02X assist_send_interrupt=%d "
        "assist_send_out=0x%02X assist_send_after_out_status=0x%02X "
        "assist_receive_status=0x%02X assist_receive_interrupt=%d "
        "assist_receive_in=0x%02X "
        "assist_receive_after_in_status=0x%02X "
        "assist_error_status=0x%02X assist_error_interrupt=%d "
        "assist_error_after_read_status=0x%02X tstates=%" PRIu64 "\n",
        assist_send_status,
        assist_send_interrupt ? 1 : 0,
        assist_send_out,
        assist_send_after_out_status,
        assist_receive_status,
        assist_receive_interrupt ? 1 : 0,
        assist_receive_in,
        assist_receive_after_in_status,
        assist_error_status,
        assist_error_interrupt ? 1 : 0,
        assist_error_after_read_status,
        timer.tstates
    );
    return 0;
}

void usb_rom_harness_port(CPU_t *cpu, device_t *device) {
    UsbRomHarness *harness = static_cast<UsbRomHarness *>(device->aux);
    const unsigned int port = static_cast<unsigned int>(DEV_INDEX(device));
    if (cpu->input) {
        unsigned char value = harness->registers[port];
        if (port == 0x4C) {
            value = harness->handshake_success ? 0x5A : 0x02;
        } else if (port == 0x8C) {
            value = harness->frame_success ? 0x01 : 0x00;
        } else if (harness->scripted_transfer) {
            const bool packet_available =
                harness->receive_packet_index < harness->receive_packets.size();
            if (port == 0x8F) {
                value = 0x04;
            } else if (port == 0x82) {
                value = static_cast<unsigned char>(
                    0x04 | (packet_available ? 0x02 : 0x00)
                );
            } else if (port == 0x84) {
                value = packet_available ? 0x06 : 0x00;
            } else if (port == 0x86 || port == 0x91 || port == 0x94) {
                value = 0x00;
            } else if (port == 0x96) {
                if (!packet_available) {
                    harness->script_error = true;
                    value = 0;
                } else {
                    const std::vector<unsigned char> &packet =
                        harness->receive_packets[harness->receive_packet_index];
                    value = static_cast<unsigned char>(
                        packet.size() - harness->receive_byte_index
                    );
                }
            } else if (port == 0xA1) {
                if (!packet_available) {
                    harness->script_error = true;
                    value = 0;
                } else {
                    const std::vector<unsigned char> &packet =
                        harness->receive_packets[harness->receive_packet_index];
                    if (harness->receive_byte_index >= packet.size()) {
                        harness->script_error = true;
                        value = 0;
                    } else {
                        value = packet[harness->receive_byte_index++];
                        if (harness->receive_byte_index == packet.size()) {
                            ++harness->receive_packet_index;
                            harness->receive_byte_index = 0;
                        }
                    }
                }
            }
        }
        ++harness->input_counts[port];
        cpu->bus = value;
        cpu->input = FALSE;
    } else if (cpu->output) {
        ++harness->output_counts[port];
        harness->registers[port] = cpu->bus;
        if (harness->writes.size() < 128) {
            harness->writes.push_back(
                UsbRomIoWrite{
                    static_cast<unsigned char>(port),
                    static_cast<unsigned char>(cpu->bus),
                }
            );
        }
        if (harness->scripted_transfer && port == 0xA2) {
            harness->transmit_packet.push_back(
                static_cast<unsigned char>(cpu->bus)
            );
        } else if (
            harness->scripted_transfer && port == 0x91 &&
            harness->registers[0x8E] == 0x02 && (cpu->bus & 0x01) != 0
        ) {
            if (harness->transmit_packet.empty()) {
                harness->script_error = true;
            } else {
                harness->transmit_packets.push_back(harness->transmit_packet);
                harness->transmit_packet.clear();
            }
        }
        cpu->output = FALSE;
    }
}

void install_usb_rom_harness(CPU_t *cpu, UsbRomHarness *harness) {
    for (unsigned int port = 0x4A; port <= 0x5B; ++port) {
        cpu->pio.devices[port].active = TRUE;
        cpu->pio.devices[port].protected_port = FALSE;
        cpu->pio.devices[port].aux = harness;
        cpu->pio.devices[port].code = (devp) usb_rom_harness_port;
    }
    for (unsigned int port = 0x80; port <= 0xA2; ++port) {
        cpu->pio.devices[port].active = TRUE;
        cpu->pio.devices[port].protected_port = FALSE;
        cpu->pio.devices[port].aux = harness;
        cpu->pio.devices[port].code = (devp) usb_rom_harness_port;
    }
}

void usb_rom_controller_status_port(CPU_t *cpu, device_t *device) {
    UsbRomHarness *harness = static_cast<UsbRomHarness *>(device->aux);
    const bool input = cpu->input != FALSE;
    device->aux = harness->controller_status_aux;
    device->code = harness->controller_status_code;
    harness->controller_status_code(cpu, device);
    device->aux = harness;
    device->code = (devp) usb_rom_controller_status_port;
    if (input) {
        cpu->bus |= 0x80;
        ++harness->input_counts[0x04];
        harness->registers[0x04] = cpu->bus;
    }
}

void install_usb_rom_controller_status_harness(
    CPU_t *cpu,
    UsbRomHarness *harness
) {
    harness->controller_status_code = cpu->pio.devices[0x04].code;
    harness->controller_status_aux = cpu->pio.devices[0x04].aux;
    cpu->pio.devices[0x04].aux = harness;
    cpu->pio.devices[0x04].code = (devp) usb_rom_controller_status_port;
    harness->controller_status_controlled = true;
}

UsbRomCaseResult run_usb_rom_case(
    const std::vector<unsigned char> &input,
    const char *name,
    bool handshake_success,
    bool frame_success,
    bool attempt_receive,
    std::uint64_t max_boot_steps,
    std::uint64_t max_probe_steps
) {
    const unsigned char init_harness[] = {0xEF, 0x08, 0x81, 0x76};
    const unsigned char attempt_harness[] = {
        0x3E, 0x40, 0xB7, 0xEF, 0xE4, 0x80, 0x76,
    };
    const unsigned char *program =
        attempt_receive ? attempt_harness : init_harness;
    const std::size_t program_size =
        attempt_receive ? sizeof(attempt_harness) : sizeof(init_harness);
    const unsigned short return_address = static_cast<unsigned short>(
        kProbeOrigin + (attempt_receive ? 6 : 3)
    );

    UsbRomCaseResult result{};
    result.name = name;
    result.handshake_success = handshake_success;
    result.frame_success = frame_success;
    result.io.handshake_success = handshake_success;
    result.io.frame_success = frame_success;
    result.io.registers[0x4D] = 0xA5;
    result.io.registers[0x55] = 0x1F;
    result.io.registers[0x56] = 0x50;

    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);
    while (result.boot_steps < max_boot_steps && !boot_protection_ready(memory)) {
        CPU_step(&cpu);
        ++result.boot_steps;
    }
    if (!boot_protection_ready(memory)) {
        fail("retail boot did not establish USB ROM-probe protection bounds");
    }
    result.boot_tstates = timer.tstates;

    memory.boot_mapped = FALSE;
    memory.banks = memory.normal_banks;
    memory.port07 = 0x80 | kProbeRamPage;
    change_page(&memory, 2, kProbeRamPage, TRUE);
    const std::size_t program_physical =
        kProbeRamPage * PAGE_SIZE + mc_base(kProbeOrigin);
    std::memcpy(memory.ram + program_physical, program, program_size);
    if (std::memcmp(
            memory.banks[2].addr + mc_base(kProbeOrigin),
            program,
            program_size
        ) != 0) {
        fail("injected USB ROM harness does not read back from RAM");
    }
    const std::vector<unsigned char> flash_before(
        memory.flash, memory.flash + kTi84PlusFlashSize
    );
    install_usb_rom_harness(&cpu, &result.io);

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

    for (; result.probe_steps < max_probe_steps; ++result.probe_steps) {
        const bank_state_t &pc_bank = memory.banks[mc_bank(cpu.pc)];
        const bool probe_ram = pc_bank.ram && pc_bank.page == kProbeRamPage;
        const bool boot_usb_page = !pc_bank.ram && pc_bank.page == 0x2F;
        if (probe_ram && cpu.pc == return_address) {
            ++result.return_visits;
            break;
        }
        if (boot_usb_page && cpu.pc == 0x4170) {
            ++result.receive_boundary_visits;
            if (attempt_receive) {
                break;
            }
        }
        if (boot_usb_page && cpu.pc == 0x52A4) {
            ++result.init_visits;
        } else if (boot_usb_page && cpu.pc == 0x59C3) {
            ++result.reset_helper_visits;
        } else if (boot_usb_page && cpu.pc == 0x5313) {
            ++result.timeout_tick_visits;
        } else if (boot_usb_page && (cpu.pc == 0x58C8 || cpu.pc == 0x5B87)) {
            ++result.cleanup_visits;
        }
        CPU_step(&cpu);
        if (execution_violation_resets != 0) {
            ++result.probe_steps;
            break;
        }
    }
    result.probe_tstates = timer.tstates - result.boot_tstates;
    result.violation_resets = execution_violation_resets;
    result.flash_changed_bytes = static_cast<unsigned int>(count_differences(
        flash_before, memory.flash, 0, kTi84PlusFlashSize
    ));
    result.final_a = cpu.a;
    result.final_f = cpu.f;
    result.final_pc = cpu.pc;
    const bool returned = result.return_visits == 1;
    const bool carry = (cpu.f & 0x01) != 0;
    result.completed = execution_violation_resets == 0 &&
        result.flash_changed_bytes == 0 && result.init_visits == 1 &&
        (attempt_receive
            ? result.receive_boundary_visits == 1
            : returned && carry != (handshake_success && frame_success));
    return result;
}

void print_usb_rom_case(const UsbRomCaseResult &result) {
    std::printf(
        "mode=usb-rom-probe case=%s handshake=%d frame=%d "
        "boot_steps=%" PRIu64 " boot_tstates=%" PRIu64 " "
        "probe_steps=%" PRIu64 " probe_tstates=%" PRIu64 " "
        "init_visits=%u reset_helper_visits=%u timeout_tick_visits=%u "
        "cleanup_visits=%u receive_boundary_visits=%u return_visits=%u "
        "violation_resets=%u flash_changed_bytes=%u "
        "input_4c=%" PRIu64 " input_4d=%" PRIu64 " input_8c=%" PRIu64 " "
        "output_4a=%" PRIu64 " output_4b=%" PRIu64 " "
        "output_4c=%" PRIu64 " output_54=%" PRIu64 " "
        "output_57=%" PRIu64 " output_87=%" PRIu64 " "
        "output_89=%" PRIu64 " output_8b=%" PRIu64 " "
        "output_92=%" PRIu64 " final_a=0x%02X final_f=0x%02X "
        "final_pc=0x%04X completed=%d writes=",
        result.name,
        result.handshake_success ? 1 : 0,
        result.frame_success ? 1 : 0,
        result.boot_steps,
        result.boot_tstates,
        result.probe_steps,
        result.probe_tstates,
        result.init_visits,
        result.reset_helper_visits,
        result.timeout_tick_visits,
        result.cleanup_visits,
        result.receive_boundary_visits,
        result.return_visits,
        result.violation_resets,
        result.flash_changed_bytes,
        result.io.input_counts[0x4C],
        result.io.input_counts[0x4D],
        result.io.input_counts[0x8C],
        result.io.output_counts[0x4A],
        result.io.output_counts[0x4B],
        result.io.output_counts[0x4C],
        result.io.output_counts[0x54],
        result.io.output_counts[0x57],
        result.io.output_counts[0x87],
        result.io.output_counts[0x89],
        result.io.output_counts[0x8B],
        result.io.output_counts[0x92],
        result.final_a,
        result.final_f,
        result.final_pc,
        result.completed ? 1 : 0
    );
    for (std::size_t index = 0; index < result.io.writes.size(); ++index) {
        const UsbRomIoWrite &write = result.io.writes[index];
        std::printf(
            "%s%02X%02X", index == 0 ? "" : ",", write.port, write.value
        );
    }
    std::printf("\n");
}

int run_usb_rom_probe(int argc, char **argv) {
    if (argc < 3 || argc > 5) {
        std::fprintf(
            stderr,
            "usage: %s --usb-rom-probe INPUT.rom "
            "[MAX_BOOT_STEPS [MAX_PROBE_STEPS]]\n",
            argv[0]
        );
        return 2;
    }
    const std::uint64_t max_boot_steps =
        argc >= 4 ? parse_count(argv[3], "MAX_BOOT_STEPS") : UINT64_C(5000000);
    const std::uint64_t max_probe_steps =
        argc >= 5 ? parse_count(argv[4], "MAX_PROBE_STEPS") : UINT64_C(8000000);
    if (max_boot_steps == 0 || max_probe_steps == 0) {
        fail("USB ROM-probe step bounds must be positive");
    }
    const std::vector<unsigned char> input = read_image(argv[2]);
    const UsbRomCaseResult cases[] = {
        run_usb_rom_case(
            input, "init-success", true, true, false,
            max_boot_steps, max_probe_steps
        ),
        run_usb_rom_case(
            input, "handshake-timeout", false, true, false,
            max_boot_steps, max_probe_steps
        ),
        run_usb_rom_case(
            input, "frame-timeout", true, false, false,
            max_boot_steps, max_probe_steps
        ),
        run_usb_rom_case(
            input, "attempt-event-40", true, true, true,
            max_boot_steps, max_probe_steps
        ),
    };
    bool completed = true;
    for (const UsbRomCaseResult &result : cases) {
        print_usb_rom_case(result);
        completed = completed && result.completed;
    }
    return completed ? 0 : 3;
}

std::size_t usb_rom_packet_bytes(
    const std::vector<std::vector<unsigned char>> &packets
) {
    std::size_t total = 0;
    for (const std::vector<unsigned char> &packet : packets) {
        total += packet.size();
    }
    return total;
}

void print_usb_rom_packets(
    const std::vector<std::vector<unsigned char>> &packets
) {
    if (packets.empty()) {
        std::printf("-");
        return;
    }
    for (std::size_t packet_index = 0; packet_index < packets.size(); ++packet_index) {
        if (packet_index != 0) {
            std::printf(";");
        }
        for (unsigned char value : packets[packet_index]) {
            std::printf("%02X", value);
        }
    }
}

UsbRomReceiveResult run_usb_rom_receive_case(
    const std::vector<unsigned char> &input,
    std::uint64_t max_boot_steps,
    std::uint64_t max_probe_steps
) {
    const unsigned char program[] = {
        0xFD, 0x21, 0xF0, 0x89,
        0xEF, 0x08, 0x81,
        0x38, 0x1C,
        0xFD, 0xCB, 0x42, 0xC6,
        0x21, 0x04, 0x01,
        0x22, 0x94, 0x90,
        0x21, 0x00, 0x00,
        0x22, 0x99, 0x90,
        0x3E, 0x14,
        0x32, 0xA8, 0x90,
        0xAF,
        0x32, 0xA9, 0x90,
        0xEF, 0xF6, 0x80,
        0x76,
    };

    UsbRomReceiveResult result{};
    result.io.handshake_success = true;
    result.io.frame_success = true;
    result.io.scripted_transfer = true;
    result.io.registers[0x4D] = 0xA5;
    result.io.registers[0x55] = 0x1F;
    result.io.registers[0x56] = 0x50;
    result.io.receive_packets = {
        {0x00, 0x00, 0x00, 0x02, 0x05},
        {0xE0, 0x00},
        {
            0x00, 0x00, 0x00, 0x0C, 0x04,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x05,
            0x00, 0x00, 0x3E, 0x00, 0x00, 0x00,
        },
    };

    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);
    while (result.boot_steps < max_boot_steps && !boot_protection_ready(memory)) {
        CPU_step(&cpu);
        ++result.boot_steps;
    }
    if (!boot_protection_ready(memory)) {
        fail("retail boot did not establish USB receive-probe protection bounds");
    }
    result.boot_tstates = timer.tstates;

    memory.boot_mapped = FALSE;
    memory.banks = memory.normal_banks;
    memory.port07 = 0x80 | kProbeRamPage;
    change_page(&memory, 2, kProbeRamPage, TRUE);
    const std::size_t program_physical =
        kProbeRamPage * PAGE_SIZE + mc_base(kProbeOrigin);
    std::memcpy(memory.ram + program_physical, program, sizeof(program));
    if (std::memcmp(
            memory.banks[2].addr + mc_base(kProbeOrigin),
            program,
            sizeof(program)
        ) != 0) {
        fail("injected USB receive harness does not read back from RAM");
    }
    const std::vector<unsigned char> flash_before(
        memory.flash, memory.flash + kTi84PlusFlashSize
    );
    install_usb_rom_harness(&cpu, &result.io);

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

    for (; result.probe_steps < max_probe_steps; ++result.probe_steps) {
        const bank_state_t &pc_bank = memory.banks[mc_bank(cpu.pc)];
        const bool boot_usb_page = !pc_bank.ram && pc_bank.page == 0x2F;
        const bool boot_page = !pc_bank.ram && pc_bank.page == 0x3F;
        const bool probe_ram = pc_bank.ram && pc_bank.page == kProbeRamPage;
        if (
            probe_ram && cpu.pc == kProbeOrigin + 7 &&
            !result.io.controller_status_controlled
        ) {
            install_usb_rom_controller_status_harness(&cpu, &result.io);
        }
        if (boot_usb_page && cpu.pc == 0x5000) {
            ++result.stop_visits;
            break;
        }
        if (boot_page && cpu.pc == 0x62D0) {
            ++result.progress_visits;
        }
        if (
            boot_usb_page && cpu.pc == 0x497B &&
            !result.progress_state_seeded
        ) {
            mem_write(&memory, 0x82A3, 0x3E);
            result.progress_state_seeded = true;
        }
        if (boot_usb_page && cpu.pc == 0x52A4) {
            ++result.init_visits;
        } else if (boot_usb_page && cpu.pc == 0x48CA) {
            ++result.receive_entry_visits;
            result.receive_iy = cpu.iy;
        } else if (boot_usb_page && cpu.pc == 0x4289) {
            ++result.control_start_visits;
        } else if (boot_usb_page && cpu.pc == 0x450E) {
            ++result.ack_parse_visits;
        } else if (boot_usb_page && cpu.pc == 0x4931) {
            result.power_gate_value = cpu.a;
        } else if (boot_usb_page && cpu.pc == 0x499F) {
            ++result.page_check_visits;
            result.page_check_value = cpu.a;
        } else if (boot_usb_page && cpu.pc == 0x49A2) {
            if ((cpu.f & 0x01) != 0) {
                ++result.invalid_page_visits;
            }
        } else if (boot_usb_page && cpu.pc == 0x4610) {
            ++result.stream_receive_visits;
        } else if (boot_usb_page && cpu.pc == 0x495B) {
            ++result.record_dispatch_visits;
        } else if (boot_usb_page && cpu.pc == 0x5958) {
            ++result.cleanup_visits;
        }
        CPU_step(&cpu);
        if (execution_violation_resets != 0) {
            ++result.probe_steps;
            break;
        }
    }
    result.probe_tstates = timer.tstates - result.boot_tstates;
    result.violation_resets = execution_violation_resets;
    result.flash_changed_bytes = static_cast<unsigned int>(count_differences(
        flash_before, memory.flash, 0, kTi84PlusFlashSize
    ));
    result.final_pc = cpu.pc;
    result.completed = result.stop_visits == 1 && result.init_visits == 1 &&
        result.receive_entry_visits == 1 && result.control_start_visits == 1 &&
        result.ack_parse_visits == 1 && result.progress_visits == 1 &&
        result.progress_state_seeded && result.receive_iy == 0x89F0 &&
        result.stream_receive_visits == 1 && result.record_dispatch_visits == 1 &&
        result.page_check_visits == 1 && result.page_check_value == 0x3E &&
        result.invalid_page_visits == 1 && result.cleanup_visits == 1 &&
        result.io.receive_packet_index == result.io.receive_packets.size() &&
        result.io.receive_byte_index == 0 && result.io.transmit_packet.empty() &&
        !result.io.script_error && execution_violation_resets == 0 &&
        result.flash_changed_bytes == 0;
    return result;
}

void print_usb_rom_receive_result(const UsbRomReceiveResult &result) {
    std::printf(
        "mode=usb-rom-receive-probe boot_steps=%" PRIu64 " "
        "boot_tstates=%" PRIu64 " probe_steps=%" PRIu64 " "
        "probe_tstates=%" PRIu64 " init_visits=%u receive_entry_visits=%u "
        "control_start_visits=%u ack_parse_visits=%u stream_receive_visits=%u "
        "record_dispatch_visits=%u progress_visits=%u "
        "progress_state_seeded=%d receive_iy=0x%04X power_gate_value=0x%02X "
        "page_check_visits=%u page_check_value=0x%02X "
        "invalid_page_visits=%u cleanup_visits=%u "
        "stop_visits=%u violation_resets=%u flash_changed_bytes=%u "
        "rx_packet_count=%zu rx_bytes=%zu rx_consumed=%zu "
        "tx_packet_count=%zu tx_bytes=%zu script_error=%d final_pc=0x%04X "
        "completed=%d rx_packets=",
        result.boot_steps,
        result.boot_tstates,
        result.probe_steps,
        result.probe_tstates,
        result.init_visits,
        result.receive_entry_visits,
        result.control_start_visits,
        result.ack_parse_visits,
        result.stream_receive_visits,
        result.record_dispatch_visits,
        result.progress_visits,
        result.progress_state_seeded ? 1 : 0,
        result.receive_iy,
        result.power_gate_value,
        result.page_check_visits,
        result.page_check_value,
        result.invalid_page_visits,
        result.cleanup_visits,
        result.stop_visits,
        result.violation_resets,
        result.flash_changed_bytes,
        result.io.receive_packets.size(),
        usb_rom_packet_bytes(result.io.receive_packets),
        result.io.receive_packet_index,
        result.io.transmit_packets.size(),
        usb_rom_packet_bytes(result.io.transmit_packets),
        result.io.script_error ? 1 : 0,
        result.final_pc,
        result.completed ? 1 : 0
    );
    print_usb_rom_packets(result.io.receive_packets);
    std::printf(" tx_packets=");
    print_usb_rom_packets(result.io.transmit_packets);
    std::printf("\n");
}

int run_usb_rom_receive_probe(int argc, char **argv) {
    if (argc < 3 || argc > 5) {
        std::fprintf(
            stderr,
            "usage: %s --usb-rom-receive-probe INPUT.rom "
            "[MAX_BOOT_STEPS [MAX_PROBE_STEPS]]\n",
            argv[0]
        );
        return 2;
    }
    const std::uint64_t max_boot_steps =
        argc >= 4 ? parse_count(argv[3], "MAX_BOOT_STEPS") : UINT64_C(5000000);
    const std::uint64_t max_probe_steps =
        argc >= 5 ? parse_count(argv[4], "MAX_PROBE_STEPS") : UINT64_C(8000000);
    if (max_boot_steps == 0 || max_probe_steps == 0) {
        fail("USB receive-probe step bounds must be positive");
    }
    const std::vector<unsigned char> input = read_image(argv[2]);
    const UsbRomReceiveResult result = run_usb_rom_receive_case(
        input, max_boot_steps, max_probe_steps
    );
    print_usb_rom_receive_result(result);
    return result.completed ? 0 : 3;
}

int run_usb_edge_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s --usb-edge-probe INPUT.rom\n", argv[0]);
        return 2;
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);
    USB_t *usb = &cpu.pio.se_aux->usb;

    const bool port4a_active = cpu.pio.devices[0x4A].active != FALSE;
    const bool port4c_active = cpu.pio.devices[0x4C].active != FALSE;
    const bool port4d_active = cpu.pio.devices[0x4D].active != FALSE;
    const bool port54_active = cpu.pio.devices[0x54].active != FALSE;
    const bool port55_active = cpu.pio.devices[0x55].active != FALSE;
    const bool port56_active = cpu.pio.devices[0x56].active != FALSE;
    const bool port57_active = cpu.pio.devices[0x57].active != FALSE;
    const bool port5b_active = cpu.pio.devices[0x5B].active != FALSE;
    const bool port80_active = cpu.pio.devices[0x80].active != FALSE;
    const DeviceReadResult port54_read = try_read_device_port(&cpu, 0x54);

    const unsigned char initial_port4a = read_device_port(&cpu, 0x4A);
    const unsigned char initial_port4c = read_device_port(&cpu, 0x4C);
    const unsigned char initial_port4d = read_device_port(&cpu, 0x4D);
    const unsigned char initial_port55 = read_device_port(&cpu, 0x55);
    const unsigned char initial_port56 = read_device_port(&cpu, 0x56);
    const unsigned char initial_port57 = read_device_port(&cpu, 0x57);
    const unsigned char initial_port5b = read_device_port(&cpu, 0x5B);
    const unsigned char initial_port80 = read_device_port(&cpu, 0x80);
    const unsigned int initial_line_state = usb->USBLineState;
    const unsigned int initial_events = usb->USBEvents;
    const unsigned int initial_event_mask = usb->USBEventMask;
    const bool initial_line_interrupt = usb->LineInterrupt != FALSE;
    const bool initial_protocol_interrupt = usb->ProtocolInterrupt != FALSE;
    const unsigned char initial_stored_port4a = usb->Port4A;
    const unsigned char initial_stored_port4c = usb->Port4C;
    const unsigned char initial_stored_port54 = usb->Port54;

    write_device_port(&cpu, 0x57, 0xFF);
    const unsigned char mask_ff_read = read_device_port(&cpu, 0x57);
    write_device_port(&cpu, 0x57, 0x00);
    const unsigned char mask_zero_read = read_device_port(&cpu, 0x57);
    cpu.interrupt = FALSE;
    write_device_port(&cpu, 0x4A, 0x08);
    const bool event_interrupt = cpu.interrupt != FALSE;
    const bool event_line_interrupt = usb->LineInterrupt != FALSE;
    const unsigned int event_line_state = usb->USBLineState;
    const unsigned int event_events = usb->USBEvents;
    const unsigned char event_port4a = read_device_port(&cpu, 0x4A);
    const unsigned char event_port4d = read_device_port(&cpu, 0x4D);
    const unsigned char event_port55 = read_device_port(&cpu, 0x55);
    const unsigned char event_port56 = read_device_port(&cpu, 0x56);
    cpu.interrupt = FALSE;
    write_device_port(&cpu, 0x4A, 0x08);
    const bool repeated_event_interrupt = cpu.interrupt != FALSE;
    const unsigned int repeated_events = usb->USBEvents;

    usb->LineInterrupt = FALSE;
    usb->ProtocolInterrupt = FALSE;
    const unsigned char summary_none = read_device_port(&cpu, 0x55);
    usb->LineInterrupt = TRUE;
    usb->ProtocolInterrupt = FALSE;
    const unsigned char summary_line = read_device_port(&cpu, 0x55);
    usb->LineInterrupt = FALSE;
    usb->ProtocolInterrupt = TRUE;
    const unsigned char summary_protocol = read_device_port(&cpu, 0x55);
    usb->LineInterrupt = TRUE;
    usb->ProtocolInterrupt = TRUE;
    const unsigned char summary_both = read_device_port(&cpu, 0x55);

    write_device_port(&cpu, 0x5B, 0xFF);
    const unsigned char port5b_ff_read = read_device_port(&cpu, 0x5B);
    const bool protocol_interrupt_enabled = usb->ProtocolInterruptEnabled != FALSE;
    write_device_port(&cpu, 0x80, 0xFF);
    const unsigned char port80_ff_read = read_device_port(&cpu, 0x80);
    const unsigned int stored_dev_address = usb->DevAddress;
    write_device_port(&cpu, 0x4C, 0xFF);
    const unsigned char port4c_ff_read = read_device_port(&cpu, 0x4C);
    const unsigned char stored_port4c = usb->Port4C;

    // Direct field seeding below tests handler contracts. These states are not
    // claimed to be reachable through the registered Fake USB ports.
    usb->Port54 = 0x00;
    usb->Port4C = 0x00;
    usb->USBLineState = 0xA6;
    const unsigned char port4d_false_pair = read_device_port(&cpu, 0x4D);
    usb->Port54 = 0x44;
    usb->Port4C = 0x08;
    usb->USBLineState = 0xE5;
    const unsigned char port4d_true_pair = read_device_port(&cpu, 0x4D);
    usb->Port4A = 0x08;
    const unsigned char port4a_true_condition = read_device_port(&cpu, 0x4A);
    usb->Port54 = 0x00;
    const unsigned char port4a_false_condition = read_device_port(&cpu, 0x4A);

    std::printf(
        "mode=usb-edge-probe "
        "port4a_active=%d port4c_active=%d port4d_active=%d "
        "port54_active=%d port54_read_accepted=%d port54_read=0x%02X "
        "port55_active=%d port56_active=%d port57_active=%d "
        "port5b_active=%d port80_active=%d "
        "initial_port4a=0x%02X initial_port4c=0x%02X "
        "initial_port4d=0x%02X initial_port55=0x%02X "
        "initial_port56=0x%02X initial_port57=0x%02X "
        "initial_port5b=0x%02X initial_port80=0x%02X "
        "initial_line_state=0x%X initial_events=0x%X "
        "initial_event_mask=0x%X initial_line_interrupt=%d "
        "initial_protocol_interrupt=%d initial_stored_port4a=0x%02X "
        "initial_stored_port4c=0x%02X initial_stored_port54=0x%02X "
        "mask_ff_read=0x%02X mask_zero_read=0x%02X "
        "event_interrupt=%d event_line_interrupt=%d "
        "event_line_state=0x%X event_events=0x%X "
        "event_port4a=0x%02X event_port4d=0x%02X "
        "event_port55=0x%02X event_port56=0x%02X "
        "repeated_event_interrupt=%d repeated_events=0x%X "
        "summary_none=0x%02X summary_line=0x%02X "
        "summary_protocol=0x%02X summary_both=0x%02X "
        "port5b_ff_read=0x%02X protocol_interrupt_enabled=%d "
        "port80_ff_read=0x%02X stored_dev_address=0x%X "
        "port4c_ff_read=0x%02X stored_port4c=0x%02X "
        "port4d_false_pair=0x%02X port4d_true_pair=0x%02X "
        "port4a_true_condition=0x%02X port4a_false_condition=0x%02X "
        "tstates=%" PRIu64 "\n",
        port4a_active ? 1 : 0,
        port4c_active ? 1 : 0,
        port4d_active ? 1 : 0,
        port54_active ? 1 : 0,
        port54_read.accepted ? 1 : 0,
        port54_read.value,
        port55_active ? 1 : 0,
        port56_active ? 1 : 0,
        port57_active ? 1 : 0,
        port5b_active ? 1 : 0,
        port80_active ? 1 : 0,
        initial_port4a,
        initial_port4c,
        initial_port4d,
        initial_port55,
        initial_port56,
        initial_port57,
        initial_port5b,
        initial_port80,
        initial_line_state,
        initial_events,
        initial_event_mask,
        initial_line_interrupt ? 1 : 0,
        initial_protocol_interrupt ? 1 : 0,
        initial_stored_port4a,
        initial_stored_port4c,
        initial_stored_port54,
        mask_ff_read,
        mask_zero_read,
        event_interrupt ? 1 : 0,
        event_line_interrupt ? 1 : 0,
        event_line_state,
        event_events,
        event_port4a,
        event_port4d,
        event_port55,
        event_port56,
        repeated_event_interrupt ? 1 : 0,
        repeated_events,
        summary_none,
        summary_line,
        summary_protocol,
        summary_both,
        port5b_ff_read,
        protocol_interrupt_enabled ? 1 : 0,
        port80_ff_read,
        stored_dev_address,
        port4c_ff_read,
        stored_port4c,
        port4d_false_pair,
        port4d_true_pair,
        port4a_true_condition,
        port4a_false_condition,
        timer.tstates
    );
    return 0;
}

int run_mapper_edge_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s --mapper-edge-probe INPUT.rom\n", argv[0]);
        return 2;
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);

    const bool port04_active = cpu.pio.devices[0x04].active != FALSE;
    const bool port05_active = cpu.pio.devices[0x05].active != FALSE;
    const bool port06_active = cpu.pio.devices[0x06].active != FALSE;
    const bool port07_active = cpu.pio.devices[0x07].active != FALSE;
    const bool port0e_active = cpu.pio.devices[0x0E].active != FALSE;
    const bool port0f_active = cpu.pio.devices[0x0F].active != FALSE;
    const bool port27_active = cpu.pio.devices[0x27].active != FALSE;
    const bool port28_active = cpu.pio.devices[0x28].active != FALSE;

    const unsigned char initial_port04_status = read_device_port(&cpu, 0x04);
    const unsigned char initial_port05 = read_device_port(&cpu, 0x05);
    const unsigned char initial_port06 = read_device_port(&cpu, 0x06);
    const unsigned char initial_port07 = read_device_port(&cpu, 0x07);
    const unsigned char initial_port0e = read_device_port(&cpu, 0x0E);
    const unsigned char initial_port0f = read_device_port(&cpu, 0x0F);
    const unsigned char initial_port27 = read_device_port(&cpu, 0x27);
    const unsigned char initial_port28 = read_device_port(&cpu, 0x28);
    const bool initial_boot_mapped = memory.boot_mapped != FALSE;
    const bool initial_page0_changed = memory.hasChangedPage0 != FALSE;
    const unsigned char initial_fixed_page = memory.banks[0].page;
    const unsigned char initial_a_page = memory.banks[1].page;
    const unsigned char initial_b_page = memory.banks[2].page;
    const unsigned char initial_c_page = memory.banks[3].page;
    const bool initial_a_ram = memory.banks[1].ram != FALSE;
    const bool initial_b_ram = memory.banks[2].ram != FALSE;
    const bool initial_c_ram = memory.banks[3].ram != FALSE;

    CPU_mem_read(&cpu, 0x4000);
    const unsigned char fixed_page_after_data_read = memory.banks[0].page;
    const bool page0_changed_after_data_read = memory.hasChangedPage0 != FALSE;
    memory.flash[0] = 0x00;
    cpu.pc = 0x4000;
    CPU_step(&cpu);
    const unsigned char fixed_page_after_opcode = memory.banks[0].page;
    const bool page0_changed_after_opcode = memory.hasChangedPage0 != FALSE;
    const unsigned short handoff_pc = cpu.pc;

    write_device_port(&cpu, 0x05, 0xFF);
    const unsigned char port05_ff_read = read_device_port(&cpu, 0x05);
    write_device_port(&cpu, 0x0E, 0xFF);
    write_device_port(&cpu, 0x06, 0x7F);
    const unsigned char port0e_ff_read = read_device_port(&cpu, 0x0E);
    const unsigned char port06_flash_read = read_device_port(&cpu, 0x06);
    const unsigned char stored_port06_flash = memory.port06;
    write_device_port(&cpu, 0x0F, 0xFF);
    write_device_port(&cpu, 0x07, 0x7F);
    const unsigned char port0f_ff_read = read_device_port(&cpu, 0x0F);
    const unsigned char port07_flash_read = read_device_port(&cpu, 0x07);
    const unsigned char stored_port07_flash = memory.port07;
    write_device_port(&cpu, 0x06, 0xFF);
    const unsigned char port06_ram_ff_read = read_device_port(&cpu, 0x06);
    const unsigned char stored_port06_ram = memory.port06;
    write_device_port(&cpu, 0x07, 0xFE);
    const unsigned char port07_ram_fe_read = read_device_port(&cpu, 0x07);
    const unsigned char stored_port07_ram = memory.port07;

    write_device_port(&cpu, 0x05, 0x05);
    write_device_port(&cpu, 0x06, 0x02);
    write_device_port(&cpu, 0x07, 0x83);
    write_device_port(&cpu, 0x04, 0x01);
    const unsigned char paired_port04_status = read_device_port(&cpu, 0x04);
    const unsigned char paired_port05 = read_device_port(&cpu, 0x05);
    const unsigned char paired_port06 = read_device_port(&cpu, 0x06);
    const unsigned char paired_port07 = read_device_port(&cpu, 0x07);
    const bool paired_boot_mapped = memory.boot_mapped != FALSE;
    const unsigned char paired_a_page = memory.banks[1].page;
    const unsigned char paired_b_page = memory.banks[2].page;
    const unsigned char paired_c_page = memory.banks[3].page;
    const bool paired_a_ram = memory.banks[1].ram != FALSE;
    const bool paired_b_ram = memory.banks[2].ram != FALSE;
    const bool paired_c_ram = memory.banks[3].ram != FALSE;

    write_device_port(&cpu, 0x04, 0x00);
    write_device_port(&cpu, 0x06, 0x04);
    write_device_port(&cpu, 0x07, 0x02);
    write_device_port(&cpu, 0x05, 0x05);
    write_device_port(&cpu, 0x28, 0x01);
    write_device_port(&cpu, 0x27, 0xFF);
    const unsigned char port27_ff_read = read_device_port(&cpu, 0x27);
    const unsigned char port28_one_read = read_device_port(&cpu, 0x28);

    memory.ram[1 * PAGE_SIZE + 0x0000] = 0xB0;
    memory.ram[1 * PAGE_SIZE + 0x003F] = 0xB1;
    memory.flash[2 * PAGE_SIZE + 0x0000] = 0xA0;
    memory.flash[2 * PAGE_SIZE + 0x003F] = 0xA1;
    memory.flash[2 * PAGE_SIZE + 0x0040] = 0xA2;
    memory.ram[5 * PAGE_SIZE + 0x3B63] = 0xC3;
    memory.ram[5 * PAGE_SIZE + 0x3B64] = 0xC4;
    memory.ram[0 * PAGE_SIZE + 0x3B64] = 0xD4;
    const unsigned char independent_8000 = mem_read(&memory, 0x8000);
    const unsigned char independent_803f = mem_read(&memory, 0x803F);
    const unsigned char independent_8040 = mem_read(&memory, 0x8040);
    const unsigned char independent_fb63 = mem_read(&memory, 0xFB63);
    const unsigned char independent_fb64 = mem_read(&memory, 0xFB64);
    mem_write(&memory, 0x8000, 0xC1);
    mem_write(&memory, 0xFB64, 0xC2);
    const unsigned char independent_write_ram1 = memory.ram[1 * PAGE_SIZE];
    const unsigned char independent_write_underlying_b = memory.flash[2 * PAGE_SIZE];
    const unsigned char independent_write_ram0 = memory.ram[0 * PAGE_SIZE + 0x3B64];
    const unsigned char independent_write_underlying_c = memory.ram[5 * PAGE_SIZE + 0x3B64];

    memory.ram[1 * PAGE_SIZE] = 0x00;
    memory.flash[2 * PAGE_SIZE] = 0x76;
    cpu.pc = 0x8000;
    cpu.halt = FALSE;
    CPU_step(&cpu);
    const bool independent_fetch_halted = cpu.halt != FALSE;

    memory.flash[4 * PAGE_SIZE + 0x0000] = 0xE0;
    memory.flash[4 * PAGE_SIZE + 0x003F] = 0xE1;
    memory.flash[4 * PAGE_SIZE + 0x0040] = 0xE2;
    memory.flash[2 * PAGE_SIZE + 0x3B63] = 0xF3;
    memory.flash[2 * PAGE_SIZE + 0x3B64] = 0xF4;
    write_device_port(&cpu, 0x04, 0x01);
    const unsigned char paired_8000 = mem_read(&memory, 0x8000);
    const unsigned char paired_803f = mem_read(&memory, 0x803F);
    const unsigned char paired_8040 = mem_read(&memory, 0x8040);
    const unsigned char paired_fb63 = mem_read(&memory, 0xFB63);
    const unsigned char paired_fb64 = mem_read(&memory, 0xFB64);

    memory.flash[4 * PAGE_SIZE] = 0x76;
    memory.ram[1 * PAGE_SIZE] = 0x00;
    cpu.pc = 0x8000;
    cpu.halt = FALSE;
    CPU_step(&cpu);
    const bool paired_fetch_halted = cpu.halt != FALSE;
    mem_write(&memory, 0x8000, 0xD1);
    mem_write(&memory, 0xFB64, 0xD2);
    const unsigned char paired_write_ram1 = memory.ram[1 * PAGE_SIZE];
    const unsigned char paired_write_underlying_b = memory.flash[4 * PAGE_SIZE];
    const unsigned char paired_write_ram0 = memory.ram[0 * PAGE_SIZE + 0x3B64];
    const unsigned char paired_write_underlying_c = memory.flash[2 * PAGE_SIZE + 0x3B64];

    std::printf(
        "mode=mapper-edge-probe "
        "port04_active=%d port05_active=%d port06_active=%d port07_active=%d "
        "port0e_active=%d port0f_active=%d port27_active=%d port28_active=%d "
        "initial_port04_status=0x%02X initial_port05=0x%02X "
        "initial_port06=0x%02X initial_port07=0x%02X "
        "initial_port0e=0x%02X initial_port0f=0x%02X "
        "initial_port27=0x%02X initial_port28=0x%02X "
        "initial_boot_mapped=%d initial_page0_changed=%d "
        "initial_fixed_page=0x%02X initial_a_page=0x%02X "
        "initial_b_page=0x%02X initial_c_page=0x%02X "
        "initial_a_ram=%d initial_b_ram=%d initial_c_ram=%d "
        "fixed_page_after_data_read=0x%02X page0_changed_after_data_read=%d "
        "fixed_page_after_opcode=0x%02X page0_changed_after_opcode=%d "
        "handoff_pc=0x%04X "
        "port05_ff_read=0x%02X port0e_ff_read=0x%02X "
        "port06_flash_read=0x%02X stored_port06_flash=0x%02X "
        "port0f_ff_read=0x%02X port07_flash_read=0x%02X "
        "stored_port07_flash=0x%02X port06_ram_ff_read=0x%02X "
        "stored_port06_ram=0x%02X port07_ram_fe_read=0x%02X "
        "stored_port07_ram=0x%02X "
        "paired_port04_status=0x%02X paired_port05=0x%02X "
        "paired_port06=0x%02X paired_port07=0x%02X "
        "paired_boot_mapped=%d paired_a_page=0x%02X "
        "paired_b_page=0x%02X paired_c_page=0x%02X "
        "paired_a_ram=%d paired_b_ram=%d paired_c_ram=%d "
        "port27_ff_read=0x%02X port28_one_read=0x%02X "
        "independent_8000=0x%02X independent_803f=0x%02X "
        "independent_8040=0x%02X independent_fb63=0x%02X "
        "independent_fb64=0x%02X independent_write_ram1=0x%02X "
        "independent_write_underlying_b=0x%02X "
        "independent_write_ram0=0x%02X "
        "independent_write_underlying_c=0x%02X "
        "independent_fetch_halted=%d "
        "paired_8000=0x%02X paired_803f=0x%02X "
        "paired_8040=0x%02X paired_fb63=0x%02X paired_fb64=0x%02X "
        "paired_fetch_halted=%d paired_write_ram1=0x%02X "
        "paired_write_underlying_b=0x%02X paired_write_ram0=0x%02X "
        "paired_write_underlying_c=0x%02X tstates=%" PRIu64 "\n",
        port04_active ? 1 : 0,
        port05_active ? 1 : 0,
        port06_active ? 1 : 0,
        port07_active ? 1 : 0,
        port0e_active ? 1 : 0,
        port0f_active ? 1 : 0,
        port27_active ? 1 : 0,
        port28_active ? 1 : 0,
        initial_port04_status,
        initial_port05,
        initial_port06,
        initial_port07,
        initial_port0e,
        initial_port0f,
        initial_port27,
        initial_port28,
        initial_boot_mapped ? 1 : 0,
        initial_page0_changed ? 1 : 0,
        initial_fixed_page,
        initial_a_page,
        initial_b_page,
        initial_c_page,
        initial_a_ram ? 1 : 0,
        initial_b_ram ? 1 : 0,
        initial_c_ram ? 1 : 0,
        fixed_page_after_data_read,
        page0_changed_after_data_read ? 1 : 0,
        fixed_page_after_opcode,
        page0_changed_after_opcode ? 1 : 0,
        handoff_pc,
        port05_ff_read,
        port0e_ff_read,
        port06_flash_read,
        stored_port06_flash,
        port0f_ff_read,
        port07_flash_read,
        stored_port07_flash,
        port06_ram_ff_read,
        stored_port06_ram,
        port07_ram_fe_read,
        stored_port07_ram,
        paired_port04_status,
        paired_port05,
        paired_port06,
        paired_port07,
        paired_boot_mapped ? 1 : 0,
        paired_a_page,
        paired_b_page,
        paired_c_page,
        paired_a_ram ? 1 : 0,
        paired_b_ram ? 1 : 0,
        paired_c_ram ? 1 : 0,
        port27_ff_read,
        port28_one_read,
        independent_8000,
        independent_803f,
        independent_8040,
        independent_fb63,
        independent_fb64,
        independent_write_ram1,
        independent_write_underlying_b,
        independent_write_ram0,
        independent_write_underlying_c,
        independent_fetch_halted ? 1 : 0,
        paired_8000,
        paired_803f,
        paired_8040,
        paired_fb63,
        paired_fb64,
        paired_fetch_halted ? 1 : 0,
        paired_write_ram1,
        paired_write_underlying_b,
        paired_write_ram0,
        paired_write_underlying_c,
        timer.tstates
    );
    return 0;
}

void load_md5_word(CPU_t *cpu, unsigned char port, std::uint32_t value) {
    for (unsigned int shift = 0; shift < 32; shift += 8) {
        write_device_port(
            cpu,
            port,
            static_cast<unsigned char>((value >> shift) & 0xFF)
        );
    }
}

std::uint32_t read_md5_result(CPU_t *cpu) {
    std::uint32_t result = 0;
    for (unsigned int index = 0; index < 4; ++index) {
        result |= static_cast<std::uint32_t>(
            read_device_port(cpu, static_cast<unsigned char>(0x1C + index))
        ) << (8 * index);
    }
    return result;
}

int run_md5_edge_probe(int argc, char **argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s --md5-edge-probe INPUT.rom\n", argv[0]);
        return 2;
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);

    unsigned char reset_operand_reads[4];
    for (unsigned int index = 0; index < 4; ++index) {
        reset_operand_reads[index] = read_device_port(
            &cpu, static_cast<unsigned char>(0x18 + index)
        );
    }
    const std::uint32_t reset_result = read_md5_result(&cpu);

    write_device_port(&cpu, 0x1F, 0x02);
    write_device_port(&cpu, 0x1E, 0);
    write_device_port(&cpu, 0x18, 0x11);
    const std::uint32_t one_write_result = read_md5_result(&cpu);
    write_device_port(&cpu, 0x18, 0x22);
    write_device_port(&cpu, 0x18, 0x33);
    const std::uint32_t three_write_result = read_md5_result(&cpu);
    write_device_port(&cpu, 0x18, 0x44);
    const std::uint32_t four_write_result = read_md5_result(&cpu);
    write_device_port(&cpu, 0x18, 0x55);
    const std::uint32_t five_write_result = read_md5_result(&cpu);

    const std::uint32_t control_operands[] = {1, 2, 3, 4, 5, 6};
    for (unsigned int index = 0; index < 6; ++index) {
        load_md5_word(
            &cpu,
            static_cast<unsigned char>(0x18 + index),
            control_operands[index]
        );
    }
    write_device_port(&cpu, 0x1E, 0xFF);
    write_device_port(&cpu, 0x1F, 0xFF);
    const std::uint32_t masked_control_result = read_md5_result(&cpu);
    unsigned char loaded_operand_reads[4];
    for (unsigned int index = 0; index < 4; ++index) {
        loaded_operand_reads[index] = read_device_port(
            &cpu, static_cast<unsigned char>(0x18 + index)
        );
    }

    const std::uint32_t mutation_operands[] = {
        UINT32_C(0x67452301),
        UINT32_C(0xEFCDAB89),
        UINT32_C(0x98BADCFE),
        UINT32_C(0x10325476),
        UINT32_C(0x80636261),
        UINT32_C(0xD76AA478),
    };
    for (unsigned int index = 0; index < 6; ++index) {
        load_md5_word(
            &cpu,
            static_cast<unsigned char>(0x18 + index),
            mutation_operands[index]
        );
    }
    write_device_port(&cpu, 0x1E, 7);
    write_device_port(&cpu, 0x1F, 0);
    const std::uint32_t before_mutation_result = read_md5_result(&cpu);
    const unsigned char mixed_low = read_device_port(&cpu, 0x1C);
    load_md5_word(&cpu, 0x18, UINT32_C(0xFFFFFFFF));
    const std::uint32_t after_mutation_result = read_md5_result(&cpu);
    std::uint32_t mixed_result = mixed_low;
    for (unsigned int index = 1; index < 4; ++index) {
        mixed_result |= static_cast<std::uint32_t>(
            read_device_port(&cpu, static_cast<unsigned char>(0x1C + index))
        ) << (8 * index);
    }

    std::printf(
        "mode=md5-edge-probe reset_operand_reads=%02X,%02X,%02X,%02X "
        "reset_result=0x%08" PRIX32 " one_write_result=0x%08" PRIX32 " "
        "three_write_result=0x%08" PRIX32 " "
        "four_write_result=0x%08" PRIX32 " "
        "five_write_result=0x%08" PRIX32 " "
        "raw_shift=0xFF raw_mode=0xFF "
        "masked_control_result=0x%08" PRIX32 " "
        "loaded_operand_reads=%02X,%02X,%02X,%02X "
        "before_mutation_result=0x%08" PRIX32 " "
        "after_mutation_result=0x%08" PRIX32 " "
        "mixed_result=0x%08" PRIX32 " tstates=%" PRIu64 "\n",
        reset_operand_reads[0],
        reset_operand_reads[1],
        reset_operand_reads[2],
        reset_operand_reads[3],
        reset_result,
        one_write_result,
        three_write_result,
        four_write_result,
        five_write_result,
        masked_control_result,
        loaded_operand_reads[0],
        loaded_operand_reads[1],
        loaded_operand_reads[2],
        loaded_operand_reads[3],
        before_mutation_result,
        after_mutation_result,
        mixed_result,
        timer.tstates
    );
    return 0;
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
    constexpr std::size_t archive_start = 0x20000;
    constexpr std::size_t archive_end = 0xA8000;
    constexpr std::size_t target_sector_start = 0x20000;
    constexpr std::size_t target_sector_end = 0x30000;
    const std::size_t flash_changed_bytes = count_differences(
        input, memory.flash, 0, input.size()
    );
    const std::size_t target_sector_changed_bytes = count_differences(
        input, memory.flash, target_sector_start, target_sector_end
    );
    const std::size_t protected_changed_bytes =
        count_differences(input, memory.flash, 0, archive_start) +
        count_differences(input, memory.flash, archive_end, input.size());
    const std::size_t outside_target_changed_bytes = flash_changed_bytes -
        static_cast<std::size_t>(input[target_physical] != stored);
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
        "bank1_page=%s%02X flash_changed_bytes=%zu "
        "target_sector_changed_bytes=%zu protected_changed_bytes=%zu "
        "outside_target_changed_bytes=%zu final_pc=0x%04X classification=%s\n",
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
        flash_changed_bytes,
        target_sector_changed_bytes,
        protected_changed_bytes,
        outside_target_changed_bytes,
        cpu.pc,
        classification
    );
    return std::strcmp(classification, "indeterminate") == 0 ? 3 : 0;
}

int run_flash_preflight_probe(int argc, char **argv) {
    if (argc < 3 || argc > 6) {
        std::fprintf(
            stderr,
            "usage: %s --flash-preflight-probe INPUT.rom "
            "[MAX_BOOT_STEPS [MAX_PROBE_STEPS [MAX_RESTART_STEPS]]]\n",
            argv[0]
        );
        return 2;
    }
    const std::uint64_t max_boot_steps =
        argc >= 4 ? parse_count(argv[3], "MAX_BOOT_STEPS") : UINT64_C(5000000);
    const std::uint64_t max_probe_steps =
        argc >= 5 ? parse_count(argv[4], "MAX_PROBE_STEPS") : UINT64_C(10000);
    const std::uint64_t max_restart_steps =
        argc >= 6 ? parse_count(argv[5], "MAX_RESTART_STEPS") : UINT64_C(5000000);
    if (max_boot_steps == 0 || max_probe_steps == 0 || max_restart_steps == 0) {
        fail("Flash preflight probe step bounds must be positive");
    }

    constexpr unsigned short preflight_address = 0x02BF;
    constexpr unsigned short failure_address = 0x02CE;
    constexpr unsigned short reset_address = 0x0000;
    constexpr unsigned short configured_sp = 0xBFFE;
    constexpr unsigned short return_address = kProbeOrigin + 3;
    const unsigned char signature[] = {
        0xC5, 0xE5, 0xED, 0x73, 0xE8, 0x83, 0x3A, 0xE9, 0x83,
        0xE6, 0xC0, 0xFE, 0xC0, 0x28, 0x03, 0xC3, 0x00, 0x00,
    };
    const unsigned char harness[] = {0xCD, 0xBF, 0x02, 0x76};
    const std::vector<unsigned char> input = read_image(argv[2]);
    const bool source_signature_match = std::memcmp(
        input.data() + preflight_address,
        signature,
        sizeof(signature)
    ) == 0;
    if (!source_signature_match) {
        fail("input image lacks the exact page-00 Flash preflight signature");
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
    const bool boot_flash_locked = memory.flash_locked != FALSE;

    memory.boot_mapped = FALSE;
    memory.banks = memory.normal_banks;
    memory.port07 = 0x80 | kProbeRamPage;
    change_page(&memory, 2, kProbeRamPage, TRUE);
    const std::size_t harness_physical =
        kProbeRamPage * PAGE_SIZE + mc_base(kProbeOrigin);
    std::memcpy(memory.ram + harness_physical, harness, sizeof(harness));
    if (std::memcmp(
            memory.banks[2].addr + mc_base(kProbeOrigin),
            harness,
            sizeof(harness)
        ) != 0) {
        fail("injected Flash preflight harness does not read back from RAM");
    }

    const bool mapped_signature_match =
        !memory.banks[0].ram && memory.banks[0].page == 0 &&
        std::memcmp(
            memory.banks[0].addr + preflight_address,
            signature,
            sizeof(signature)
        ) == 0;
    if (!mapped_signature_match) {
        fail("retail boot did not map the exact Flash preflight in page 0");
    }
    if (!memory.flash_locked || memory.step != FLASH_READ) {
        fail("Flash preflight probe requires a locked array-read state");
    }

    cpu.pc = kProbeOrigin;
    cpu.sp = configured_sp;
    cpu.halt = FALSE;
    cpu.iff1 = FALSE;
    cpu.iff2 = FALSE;
    cpu.interrupt = FALSE;
    cpu.ei_block = FALSE;
    cpu.prefix = 0;
    execution_violation_resets = 0;
    cpu.exe_violation_callback = record_execution_violation;

    unsigned int harness_visits = 0;
    unsigned int preflight_visits = 0;
    unsigned int failure_visits = 0;
    unsigned int reset_visits = 0;
    unsigned int return_visits = 0;
    std::uint64_t probe_steps = 0;
    for (; probe_steps < max_probe_steps; ++probe_steps) {
        if (cpu.pc == reset_address) {
            ++reset_visits;
            break;
        }
        if (cpu.pc == return_address) {
            ++return_visits;
            break;
        }
        harness_visits += cpu.pc == kProbeOrigin;
        preflight_visits += cpu.pc == preflight_address;
        failure_visits += cpu.pc == failure_address;
        CPU_step(&cpu);
        if (execution_violation_resets != 0) {
            ++probe_steps;
            break;
        }
    }
    const std::size_t flash_changed_before_restart = count_differences(
        input,
        memory.flash,
        0,
        input.size()
    );
    const bool gate_locked_before_restart = memory.flash_locked != FALSE;
    const char *step_before_restart = flash_step_name(memory.step);

    const bool failure_path_complete =
        harness_visits == 1 && preflight_visits == 1 && failure_visits == 1 &&
        reset_visits == 1 && return_visits == 0 &&
        execution_violation_resets == 0 && flash_changed_before_restart == 0 &&
        gate_locked_before_restart && memory.step == FLASH_READ;

    if (CPU_reset(&cpu) != 0) {
        fail("Wabbitemu CPU restart failed");
    }
    cpu.pio.lcd->reset(&cpu);
    const unsigned short restart_reset_pc = cpu.pc;
    bool restart_ready = false;
    std::uint64_t restart_steps = 0;
    const std::uint64_t restart_tstates_start = timer.tstates;
    for (; restart_steps < max_restart_steps; ++restart_steps) {
        CPU_step(&cpu);
        const bank_state_t &pc_bank = memory.banks[mc_bank(cpu.pc)];
        if (cpu.pc == boot_pc && pc_bank.ram == boot_bank.ram &&
            pc_bank.page == boot_bank.page && boot_protection_ready(memory)) {
            ++restart_steps;
            restart_ready = true;
            break;
        }
    }
    const std::size_t flash_changed_after_restart = count_differences(
        input,
        memory.flash,
        0,
        input.size()
    );
    const bank_state_t restart_bank = memory.banks[mc_bank(cpu.pc)];
    const bool passed = source_signature_match && mapped_signature_match &&
        boot_flash_locked && failure_path_complete && restart_reset_pc == 0 &&
        restart_ready && flash_changed_after_restart == 0;

    std::printf(
        "mode=flash-preflight-probe status=%d "
        "preflight_address=0x%04X failure_address=0x%04X "
        "reset_address=0x%04X configured_sp=0x%04X "
        "signature_size=%zu source_signature_match=%d mapped_signature_match=%d "
        "boot_steps=%" PRIu64 " boot_tstates=%" PRIu64 " "
        "boot_pc=0x%04X boot_page=%s%02X boot_flash_locked=%d "
        "max_probe_steps=%" PRIu64 " probe_steps=%" PRIu64 " "
        "harness_visits=%u preflight_visits=%u failure_visits=%u "
        "reset_visits=%u return_visits=%u violation_resets=%u "
        "gate_locked_before_restart=%d step_before_restart=%s "
        "flash_changed_before_restart=%zu restart_reset_pc=0x%04X "
        "max_restart_steps=%" PRIu64 " restart_steps=%" PRIu64 " "
        "restart_tstates=%" PRIu64 " restart_pc=0x%04X "
        "restart_page=%s%02X restart_ready=%d "
        "flash_changed_after_restart=%zu\n",
        passed ? 0 : 1,
        preflight_address,
        failure_address,
        reset_address,
        configured_sp,
        sizeof(signature),
        source_signature_match ? 1 : 0,
        mapped_signature_match ? 1 : 0,
        boot_steps,
        boot_tstates,
        boot_pc,
        boot_bank.ram ? "RAM:" : "",
        boot_bank.page,
        boot_flash_locked ? 1 : 0,
        max_probe_steps,
        probe_steps,
        harness_visits,
        preflight_visits,
        failure_visits,
        reset_visits,
        return_visits,
        execution_violation_resets,
        gate_locked_before_restart ? 1 : 0,
        step_before_restart,
        flash_changed_before_restart,
        restart_reset_pc,
        max_restart_steps,
        restart_steps,
        timer.tstates - restart_tstates_start,
        cpu.pc,
        restart_bank.ram ? "RAM:" : "",
        restart_bank.page,
        restart_ready ? 1 : 0,
        flash_changed_after_restart
    );
    return passed ? 0 : 3;
}

int run_flash_bcall_usage_probe(int argc, char **argv) {
    if (argc < 4 || argc > 6) {
        std::fprintf(
            stderr,
            "usage: %s --flash-bcall-usage-probe INPUT.rom PROBE.bin "
            "[MAX_BOOT_STEPS [MAX_PROBE_STEPS]]\n",
            argv[0]
        );
        return 2;
    }
    const std::uint64_t max_boot_steps =
        argc >= 5 ? parse_count(argv[4], "MAX_BOOT_STEPS") : UINT64_C(5000000);
    const std::uint64_t max_probe_steps =
        argc >= 6 ? parse_count(argv[5], "MAX_PROBE_STEPS") : UINT64_C(250000);
    if (max_boot_steps == 0 || max_probe_steps == 0) {
        fail("Flash bcall usage step bounds must be positive");
    }

    constexpr unsigned short result_start = 0x9F00;
    constexpr unsigned short writeflash_af_address = 0x9F00;
    constexpr unsigned short writeflashunsafe_af_address = 0x9F02;
    constexpr unsigned short writeabytesafe_af_address = 0x9F04;
    constexpr unsigned short writeabyte_af_address = 0x9F06;
    constexpr unsigned short erasepage_af_address = 0x9F08;
    constexpr unsigned short eraseflash_af_address = 0x9F0A;
    constexpr unsigned short erasecertificate_af_address = 0x9F0C;
    constexpr unsigned short bound_iff_af_address = 0x9F0E;
    constexpr unsigned short writeflash_copy_address = 0x9F20;
    constexpr unsigned short writeflashunsafe_copy_address = 0x9F22;
    constexpr unsigned short writeabytesafe_copy_address = 0x9F24;
    constexpr unsigned short writeabyte_copy_address = 0x9F25;
    constexpr unsigned short erasepage_copy_address = 0x9F26;
    constexpr unsigned short eraseflash_copy_address = 0x9F27;
    constexpr unsigned short erasecertificate_copy_address = 0x9F28;
    constexpr unsigned char writeflash_page = 0x08;
    constexpr unsigned short writeflash_offset = 0x0100;
    constexpr unsigned char writeflashunsafe_page = 0x3E;
    constexpr unsigned short writeflashunsafe_offset = 0x0100;
    constexpr unsigned char writeabytesafe_page = 0x08;
    constexpr unsigned short writeabytesafe_offset = 0x0102;
    constexpr unsigned char writeabyte_page = 0x3E;
    constexpr unsigned short writeabyte_offset = 0x0102;
    constexpr unsigned char erasepage_page = 0x0C;
    constexpr unsigned short erasepage_offset = 0x0000;
    constexpr unsigned char eraseflash_page = 0x10;
    constexpr unsigned short eraseflash_offset = 0x0567;
    constexpr unsigned char erasecertificate_page = 0x3E;
    constexpr unsigned short erasecertificate_offset = 0x2001;

    const std::vector<unsigned char> input = read_image(argv[2]);
    const std::vector<unsigned char> probe = read_probe(argv[3]);
    if (probe.size() > result_start - kProbeOrigin) {
        fail("Flash bcall usage probe overlaps its fixed result block");
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

    memory.boot_mapped = FALSE;
    memory.banks = memory.normal_banks;
    memory.port07 = 0x80 | kProbeRamPage;
    change_page(&memory, 2, kProbeRamPage, TRUE);
    const std::size_t program_physical =
        kProbeRamPage * PAGE_SIZE + mc_base(kProbeOrigin);
    const std::size_t results_physical =
        kProbeRamPage * PAGE_SIZE + mc_base(result_start);
    std::memcpy(memory.ram + program_physical, probe.data(), probe.size());
    std::memset(memory.ram + results_physical, 0xCC, 0x40);
    if (std::memcmp(
            memory.banks[2].addr + mc_base(kProbeOrigin),
            probe.data(),
            probe.size()
        ) != 0) {
        fail("injected Flash bcall usage probe does not read back from RAM");
    }

    const auto flash_physical = [](unsigned char page, unsigned short offset) {
        return static_cast<std::size_t>(page) * PAGE_SIZE + offset;
    };
    const std::size_t writeflash_physical =
        flash_physical(writeflash_page, writeflash_offset);
    const std::size_t writeflashunsafe_physical =
        flash_physical(writeflashunsafe_page, writeflashunsafe_offset);
    const std::size_t writeabytesafe_physical =
        flash_physical(writeabytesafe_page, writeabytesafe_offset);
    const std::size_t writeabyte_physical =
        flash_physical(writeabyte_page, writeabyte_offset);
    const std::size_t erasepage_physical =
        flash_physical(erasepage_page, erasepage_offset);
    const std::size_t eraseflash_physical =
        flash_physical(eraseflash_page, eraseflash_offset);
    const std::size_t erasecertificate_physical =
        flash_physical(erasecertificate_page, erasecertificate_offset);
    memory.flash[writeflash_physical] = 0xFF;
    memory.flash[writeflash_physical + 1] = 0xFF;
    memory.flash[writeflashunsafe_physical] = 0xFF;
    memory.flash[writeflashunsafe_physical + 1] = 0xFF;
    memory.flash[writeabytesafe_physical] = 0xFE;
    memory.flash[writeabyte_physical] = 0xFE;
    memory.flash[erasepage_physical] = 0x00;
    memory.flash[eraseflash_physical] = 0x00;
    memory.flash[erasecertificate_physical] = 0x00;
    memory.flash_locked = FALSE;
    memory.step = FLASH_READ;
    memory.flash_error = FALSE;
    memory.flash_toggles = 0;

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

    unsigned int writeflash_visits = 0;
    unsigned int writeflashunsafe_visits = 0;
    unsigned int writeabytesafe_visits = 0;
    unsigned int writeabyte_visits = 0;
    unsigned int erasepage_visits = 0;
    unsigned int eraseflash_visits = 0;
    unsigned int erasecertificate_visits = 0;
    unsigned int setbound_visits = 0;
    unsigned int flashtoram_visits = 0;
    unsigned int worker_entry_visits = 0;
    std::uint64_t probe_steps = 0;
    for (; probe_steps < max_probe_steps && !cpu.halt; ++probe_steps) {
        const bank_state_t &pc_bank = memory.banks[mc_bank(cpu.pc)];
        const bool boot_page = !pc_bank.ram && pc_bank.page == 0x3F;
        const bool archive_page = !pc_bank.ram && pc_bank.page == 0x3D;
        const bool worker_page = pc_bank.ram &&
            pc_bank.page == kProbeRamPage && cpu.pc == 0x8100;
        if (boot_page && cpu.pc == 0x4C8F) {
            ++writeflash_visits;
        }
        if (boot_page && cpu.pc == 0x4CA6) {
            ++writeflashunsafe_visits;
        }
        if (boot_page && cpu.pc == 0x4C9A) {
            ++writeabytesafe_visits;
        }
        if (boot_page && cpu.pc == 0x4C9F) {
            ++writeabyte_visits;
        }
        if (boot_page && cpu.pc == 0x4C1E) {
            ++erasepage_visits;
        }
        if (boot_page && cpu.pc == 0x4C2A) {
            ++eraseflash_visits;
        }
        if (boot_page && cpu.pc == 0x4E3F) {
            ++erasecertificate_visits;
        }
        if (boot_page && cpu.pc == 0x4784) {
            ++setbound_visits;
        }
        if (archive_page && cpu.pc == 0x6745) {
            ++flashtoram_visits;
        }
        if (worker_page) {
            ++worker_entry_visits;
        }
        CPU_step(&cpu);
        if (execution_violation_resets != 0) {
            ++probe_steps;
            break;
        }
    }

    const auto ram_byte = [&memory](unsigned short address) {
        return memory.ram[
            kProbeRamPage * PAGE_SIZE + mc_base(address)
        ];
    };
    const auto ram_word = [&ram_byte](unsigned short address) {
        return static_cast<unsigned short>(
            ram_byte(address) |
            static_cast<unsigned short>(ram_byte(address + 1)) << 8
        );
    };
    const unsigned short writeflash_af = ram_word(writeflash_af_address);
    const unsigned short writeflashunsafe_af =
        ram_word(writeflashunsafe_af_address);
    const unsigned short writeabytesafe_af = ram_word(writeabytesafe_af_address);
    const unsigned short writeabyte_af = ram_word(writeabyte_af_address);
    const unsigned short erasepage_af = ram_word(erasepage_af_address);
    const unsigned short eraseflash_af = ram_word(eraseflash_af_address);
    const unsigned short erasecertificate_af =
        ram_word(erasecertificate_af_address);
    const unsigned short bound_iff_af = ram_word(bound_iff_af_address);
    const unsigned char writeflash_stored_0 = memory.flash[writeflash_physical];
    const unsigned char writeflash_stored_1 =
        memory.flash[writeflash_physical + 1];
    const unsigned char writeflashunsafe_stored_0 =
        memory.flash[writeflashunsafe_physical];
    const unsigned char writeflashunsafe_stored_1 =
        memory.flash[writeflashunsafe_physical + 1];
    const unsigned char writeabytesafe_stored =
        memory.flash[writeabytesafe_physical];
    const unsigned char writeabyte_stored = memory.flash[writeabyte_physical];
    const unsigned char erasepage_stored = memory.flash[erasepage_physical];
    const unsigned char eraseflash_stored = memory.flash[eraseflash_physical];
    const unsigned char erasecertificate_stored =
        memory.flash[erasecertificate_physical];
    const unsigned char writeflash_copy_0 = ram_byte(writeflash_copy_address);
    const unsigned char writeflash_copy_1 =
        ram_byte(writeflash_copy_address + 1);
    const unsigned char writeflashunsafe_copy_0 =
        ram_byte(writeflashunsafe_copy_address);
    const unsigned char writeflashunsafe_copy_1 =
        ram_byte(writeflashunsafe_copy_address + 1);
    const unsigned char writeabytesafe_copy =
        ram_byte(writeabytesafe_copy_address);
    const unsigned char writeabyte_copy = ram_byte(writeabyte_copy_address);
    const unsigned char erasepage_copy = ram_byte(erasepage_copy_address);
    const unsigned char eraseflash_copy = ram_byte(eraseflash_copy_address);
    const unsigned char erasecertificate_copy =
        ram_byte(erasecertificate_copy_address);
    const unsigned char context_byte = CPU_mem_read(&cpu, 0x89F0 + 0x25);
    const unsigned char op1 = CPU_mem_read(&cpu, 0x8478);
    const bool completed = cpu.halt && execution_violation_resets == 0;

    std::printf(
        "mode=flash-bcall-usage-probe probe_size=%zu boot_steps=%" PRIu64 " "
        "boot_tstates=%" PRIu64 " max_probe_steps=%" PRIu64 " "
        "probe_steps=%" PRIu64 " probe_tstates=%" PRIu64 " "
        "writeflash_visits=%u writeflashunsafe_visits=%u "
        "writeabytesafe_visits=%u writeabyte_visits=%u "
        "erasepage_visits=%u eraseflash_visits=%u "
        "erasecertificate_visits=%u setbound_visits=%u "
        "flashtoram_visits=%u worker_entry_visits=%u violation_resets=%u "
        "completed=%d writeflash_af=0x%04X writeflashunsafe_af=0x%04X "
        "writeabytesafe_af=0x%04X writeabyte_af=0x%04X "
        "erasepage_af=0x%04X eraseflash_af=0x%04X "
        "erasecertificate_af=0x%04X bound_iff_af=0x%04X "
        "writeflash_stored=%02X,%02X writeflash_copy=%02X,%02X "
        "writeflashunsafe_stored=%02X,%02X "
        "writeflashunsafe_copy=%02X,%02X "
        "writeabytesafe_stored=0x%02X writeabytesafe_copy=0x%02X "
        "writeabyte_stored=0x%02X writeabyte_copy=0x%02X "
        "erasepage_stored=0x%02X erasepage_copy=0x%02X "
        "eraseflash_stored=0x%02X eraseflash_copy=0x%02X "
        "erasecertificate_stored=0x%02X erasecertificate_copy=0x%02X "
        "op1=0x%02X context_bit1=%d "
        "flash_upper=0x%02X flash_locked=%d final_pc=0x%04X\n",
        probe.size(),
        boot_steps,
        boot_tstates,
        max_probe_steps,
        probe_steps,
        timer.tstates - boot_tstates,
        writeflash_visits,
        writeflashunsafe_visits,
        writeabytesafe_visits,
        writeabyte_visits,
        erasepage_visits,
        eraseflash_visits,
        erasecertificate_visits,
        setbound_visits,
        flashtoram_visits,
        worker_entry_visits,
        execution_violation_resets,
        static_cast<int>(completed),
        writeflash_af,
        writeflashunsafe_af,
        writeabytesafe_af,
        writeabyte_af,
        erasepage_af,
        eraseflash_af,
        erasecertificate_af,
        bound_iff_af,
        writeflash_stored_0,
        writeflash_stored_1,
        writeflash_copy_0,
        writeflash_copy_1,
        writeflashunsafe_stored_0,
        writeflashunsafe_stored_1,
        writeflashunsafe_copy_0,
        writeflashunsafe_copy_1,
        writeabytesafe_stored,
        writeabytesafe_copy,
        writeabyte_stored,
        writeabyte_copy,
        erasepage_stored,
        erasepage_copy,
        eraseflash_stored,
        eraseflash_copy,
        erasecertificate_stored,
        erasecertificate_copy,
        op1,
        static_cast<int>((context_byte & 0x02) != 0),
        memory.flash_upper,
        static_cast<int>(memory.flash_locked),
        cpu.pc
    );
    return completed ? 0 : 3;
}

int run_injected_hardware_probe(
    int argc,
    char **argv,
    const char *mode,
    unsigned char probe_id,
    std::size_t payload_size
) {
    if (argc < 4 || argc > 6) {
        std::fprintf(
            stderr,
            "usage: %s %s INPUT.rom PROBE.bin "
            "[MAX_BOOT_STEPS [MAX_PROBE_STEPS]]\n",
            argv[0],
            argv[1]
        );
        return 2;
    }
    const std::uint64_t max_boot_steps =
        argc >= 5 ? parse_count(argv[4], "MAX_BOOT_STEPS") : UINT64_C(5000000);
    const std::uint64_t max_probe_steps =
        argc >= 6 ? parse_count(argv[5], "MAX_PROBE_STEPS") : UINT64_C(1500000);
    if (max_boot_steps == 0 || max_probe_steps == 0) {
        fail("injected hardware-probe step bounds must be positive");
    }

    const std::vector<unsigned char> input = read_image(argv[2]);
    const std::vector<unsigned char> probe = read_probe(argv[3]);
    const unsigned char create_call[] = {0xCD, 0x98, 0x9D};
    const unsigned char frame_marker[] = {
        'H', 'W', 'P', '1', 0x01, probe_id,
        static_cast<unsigned char>(payload_size & 0xFF),
        static_cast<unsigned char>((payload_size >> 8) & 0xFF)
    };
    const std::size_t call_offset = find_unique(
        probe,
        create_call,
        sizeof(create_call),
        "CALL create_probe_appvar"
    );
    const std::size_t frame_offset = find_unique(
        probe,
        frame_marker,
        sizeof(frame_marker),
        "injected hardware-probe result frame"
    );
    const std::size_t frame_size = 10 + payload_size;
    if (frame_offset + frame_size > probe.size()) {
        fail("injected hardware-probe result frame extends past the probe image");
    }
    const unsigned short call_address = static_cast<unsigned short>(
        kProbeOrigin + call_offset
    );

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

    memory.boot_mapped = FALSE;
    memory.banks = memory.normal_banks;
    memory.port07 = 0x80 | kProbeRamPage;
    change_page(&memory, 2, kProbeRamPage, TRUE);
    const std::size_t program_physical =
        kProbeRamPage * PAGE_SIZE + mc_base(kProbeOrigin);
    std::memcpy(memory.ram + program_physical, probe.data(), probe.size());
    if (std::memcmp(
            memory.banks[2].addr + mc_base(kProbeOrigin),
            probe.data(),
            probe.size()
        ) != 0) {
        fail("injected hardware probe does not read back from RAM");
    }

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

    std::uint64_t probe_steps = 0;
    for (; probe_steps < max_probe_steps; ++probe_steps) {
        if (cpu.pc == call_address) {
            break;
        }
        CPU_step(&cpu);
        if (execution_violation_resets != 0) {
            ++probe_steps;
            break;
        }
    }

    const unsigned char *frame =
        memory.ram + program_physical + frame_offset;
    const unsigned char outcome = frame[10 + 13];
    const bool completed =
        cpu.pc == call_address && outcome == 0 && execution_violation_resets == 0;
    std::printf(
        "mode=%s probe_size=%zu boot_steps=%" PRIu64 " "
        "boot_tstates=%" PRIu64 " max_probe_steps=%" PRIu64 " "
        "probe_steps=%" PRIu64 " probe_tstates=%" PRIu64 " "
        "call_address=0x%04X violation_resets=%u outcome=%u completed=%d "
        "frame_hex=",
        mode,
        probe.size(),
        boot_steps,
        boot_tstates,
        max_probe_steps,
        probe_steps,
        timer.tstates - boot_tstates,
        call_address,
        execution_violation_resets,
        outcome,
        static_cast<int>(completed)
    );
    for (std::size_t index = 0; index < frame_size; ++index) {
        std::printf("%02X", frame[index]);
    }
    std::printf(" final_pc=0x%04X\n", cpu.pc);
    return completed ? 0 : 3;
}

int run_prefix_m1_probe(int argc, char **argv) {
    return run_injected_hardware_probe(
        argc, argv, "prefix-m1-probe", 11, 63
    );
}

int run_timer_physical_probe(int argc, char **argv) {
    return run_injected_hardware_probe(
        argc, argv, "timer-physical-probe", 12, 91
    );
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
    if (argc >= 2 && std::strcmp(argv[1], "--reset-retention-probe") == 0) {
        return run_reset_retention_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--protection-port-probe") == 0) {
        return run_protection_port_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--speed-edge-probe") == 0) {
        return run_speed_edge_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--mapper-edge-probe") == 0) {
        return run_mapper_edge_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--usb-edge-probe") == 0) {
        return run_usb_edge_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--usb-rom-probe") == 0) {
        return run_usb_rom_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--usb-rom-receive-probe") == 0) {
        return run_usb_rom_receive_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--link-edge-probe") == 0) {
        return run_link_edge_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--interrupt-edge-probe") == 0) {
        return run_interrupt_edge_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--lcd-edge-probe") == 0) {
        return run_lcd_edge_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--lcd-diagnostic-probe") == 0) {
        return run_lcd_diagnostic_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--asic-edge-probe") == 0) {
        return run_asic_edge_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--timer-edge-probe") == 0) {
        return run_timer_edge_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--keypad-edge-probe") == 0) {
        return run_keypad_edge_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--md5-edge-probe") == 0) {
        return run_md5_edge_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--flash-command-probe") == 0) {
        return run_flash_command_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--flash-worker-probe") == 0) {
        return run_flash_worker_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--flash-preflight-probe") == 0) {
        return run_flash_preflight_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--flash-bcall-usage-probe") == 0) {
        return run_flash_bcall_usage_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--prefix-m1-probe") == 0) {
        return run_prefix_m1_probe(argc, argv);
    }
    if (argc >= 2 && std::strcmp(argv[1], "--timer-physical-probe") == 0) {
        return run_timer_physical_probe(argc, argv);
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
