// Execute the complete compact-code display path in the pinned Wabbitemu core.

#include <string>

#define main wabbitemu_headless_embedded_main
#include "wabbitemu_headless.cpp"
#undef main

namespace {

constexpr unsigned short kFakeAppVar = 0xB800;
constexpr unsigned short kReturnSentinel = 0x9D94;

std::size_t visible_lcd_nonzero_bytes(const LCD_t &lcd) {
    std::size_t count = 0;
    for (unsigned int row = 0; row < LCD_HEIGHT; ++row) {
        for (unsigned int column = 0; column < 12; ++column) {
            if (lcd.display[row * LCD_MEM_WIDTH + column] != 0) {
                ++count;
            }
        }
    }
    return count;
}

bool is_create_call(const std::vector<unsigned char> &probe, unsigned short pc) {
    if (pc < kProbeOrigin) {
        return false;
    }
    const std::size_t offset = pc - kProbeOrigin;
    return offset + 2 < probe.size()
        && probe[offset] == 0xCD
        && probe[offset + 1] == 0x98
        && probe[offset + 2] == 0x9D;
}

bool display_bcall(
    const std::vector<unsigned char> &probe,
    unsigned short pc,
    CPU_t *cpu,
    std::string *compact,
    unsigned short *display_code,
    std::size_t *key_pages,
    std::vector<std::uint64_t> *page_hashes,
    std::vector<std::size_t> *page_nonzero_bytes
) {
    if (pc < kProbeOrigin) {
        return false;
    }
    const std::size_t offset = pc - kProbeOrigin;
    if (offset + 2 >= probe.size() || probe[offset] != 0xEF) {
        return false;
    }
    const unsigned short id = static_cast<unsigned short>(
        probe[offset + 1] | (probe[offset + 2] << 8)
    );
    switch (id) {
        case 0x4507:
            *display_code = cpu->hl;
            return false;
        case 0x455E:
            compact->push_back(static_cast<char>(cpu->a));
            return false;
        case 0x4972:
            ++*key_pages;
            page_hashes->push_back(visible_lcd_fnv1a64(
                *reinterpret_cast<const LCD_t *>(cpu->pio.lcd)
            ));
            page_nonzero_bytes->push_back(visible_lcd_nonzero_bytes(
                *reinterpret_cast<const LCD_t *>(cpu->pio.lcd)
            ));
            cpu->a = 0x05;
            cpu->pc = static_cast<unsigned short>(cpu->pc + 3);
            return true;
        case 0x450A:
        case 0x4540:
        case 0x4543:
        case 0x4558:
            return false;
        default:
            return false;
    }
}

int run_compact_probe(int argc, char **argv) {
    if (argc != 7) {
        std::fprintf(
            stderr,
            "usage: %s --compact-probe INPUT.rom PROBE.bin ID PAYLOAD_SIZE MAX_STEPS\n",
            argv[0]
        );
        return 2;
    }
    const unsigned char probe_id = parse_page(argv[4]);
    const std::size_t payload_size = parse_count(argv[5], "PAYLOAD_SIZE");
    const std::uint64_t max_steps = parse_count(argv[6], "MAX_STEPS");
    const std::vector<unsigned char> input = read_image(argv[2]);
    const std::vector<unsigned char> probe = read_probe(argv[3]);
    const unsigned char frame_marker[] = {
        'H', 'W', 'P', '1', 0x01, probe_id,
        static_cast<unsigned char>(payload_size & 0xFF),
        static_cast<unsigned char>((payload_size >> 8) & 0xFF),
    };
    const unsigned char done_marker[] = {0x3E, 0xC7, 0xFE, 0xC7, 0xC9};
    const std::size_t frame_offset = find_unique(
        probe, frame_marker, sizeof(frame_marker), "compact-probe frame"
    );
    const std::size_t done_offset = find_unique(
        probe, done_marker, sizeof(done_marker), "compact display marker"
    );
    const std::size_t frame_size = 10 + payload_size;
    if (frame_offset + frame_size > probe.size()) {
        fail("compact-probe frame extends past machine image");
    }

    memory_context_t memory;
    timer_context_t timer;
    CPU_t cpu;
    initialize(input, &memory, &timer, &cpu);
    std::uint64_t boot_steps = 0;
    while (boot_steps < UINT64_C(5000000) && !boot_protection_ready(memory)) {
        CPU_step(&cpu);
        ++boot_steps;
    }
    if (!boot_protection_ready(memory)) {
        fail("retail boot did not reach the protected OS baseline");
    }

    write_device_port(&cpu, 0x03, 0x00);
    write_device_port(&cpu, 0x03, 0x0B);
    write_device_port(&cpu, 0x04, 0x06);
    write_device_port(&cpu, 0x05, 0x00);
    write_device_port(&cpu, 0x06, 0x3F);
    write_device_port(&cpu, 0x07, 0x81);
    write_device_port(&cpu, 0x0E, 0x00);
    write_device_port(&cpu, 0x0F, 0x00);
    write_device_port(&cpu, 0x27, 0x00);
    write_device_port(&cpu, 0x28, 0x00);
    write_device_port(&cpu, 0x20, 0x01);
    write_device_port(&cpu, 0x30, 0x00);
    write_device_port(&cpu, 0x31, 0x00);
    timer.tstates += 100;
    write_device_port(&cpu, 0x10, 0x01);
    CPU_mem_write(&cpu, 0x844F, 0x20);
    CPU_mem_write(&cpu, 0x8451, 0x80);

    const std::size_t program_physical =
        kProbeRamPage * PAGE_SIZE + mc_base(kProbeOrigin);
    std::memcpy(memory.ram + program_physical, probe.data(), probe.size());
    cpu.pc = kProbeOrigin;
    cpu.sp = kProbeStack;
    cpu.iy = 0x89F0;
    cpu.imode = 1;
    cpu.halt = FALSE;
    cpu.iff1 = TRUE;
    cpu.iff2 = TRUE;
    cpu.interrupt = FALSE;
    cpu.ei_block = FALSE;
    cpu.prefix = 0;
    CPU_mem_write(&cpu, kProbeStack, kReturnSentinel & 0xFF);
    CPU_mem_write(&cpu, kProbeStack + 1, kReturnSentinel >> 8);
    execution_violation_resets = 0;
    cpu.exe_violation_callback = record_execution_violation;

    const unsigned short done_stop = static_cast<unsigned short>(
        kProbeOrigin + done_offset
    );
    const std::size_t fake_physical =
        kProbeRamPage * PAGE_SIZE + mc_base(kFakeAppVar);
    std::size_t create_intercepts = 0;
    std::size_t key_pages = 0;
    std::size_t marker_visits = 0;
    unsigned short display_code = 0;
    std::string compact;
    std::vector<std::uint64_t> page_hashes;
    std::vector<std::size_t> page_nonzero_bytes;
    std::uint64_t probe_steps = 0;
    for (; probe_steps < max_steps; ++probe_steps) {
        if (cpu.pc == kReturnSentinel) {
            break;
        }
        if (cpu.pc == done_stop) {
            ++marker_visits;
        }
        if (is_create_call(probe, cpu.pc)) {
            const unsigned char *frame = memory.ram + program_physical + frame_offset;
            std::memcpy(memory.ram + fake_physical, frame, frame_size);
            cpu.de = static_cast<unsigned short>(kFakeAppVar + frame_size);
            cpu.pc = static_cast<unsigned short>(cpu.pc + 3);
            ++create_intercepts;
            continue;
        }
        if (display_bcall(
                probe, cpu.pc, &cpu, &compact, &display_code, &key_pages,
                &page_hashes, &page_nonzero_bytes
            )) {
            continue;
        }
        CPU_step(&cpu);
        if (execution_violation_resets != 0) {
            ++probe_steps;
            break;
        }
    }

    const unsigned char *frame = memory.ram + program_physical + frame_offset;
    const bool appvar_matches = std::memcmp(
        memory.ram + fake_physical, frame, frame_size
    ) == 0;
    bool all_pages_nonblank = page_nonzero_bytes.size() == key_pages;
    for (std::size_t count : page_nonzero_bytes) {
        all_pages_nonblank = all_pages_nonblank && count != 0;
    }
    const bool completed = cpu.pc == kReturnSentinel
        && cpu.sp == static_cast<unsigned short>(kProbeStack + 2)
        && execution_violation_resets == 0
        && create_intercepts == 1
        && marker_visits == 1
        && appvar_matches
        && page_hashes.size() == key_pages
        && all_pages_nonblank
        && compact.rfind("HWPZ1-", 0) == 0;
    const LCD_t *lcd = reinterpret_cast<const LCD_t *>(cpu.pio.lcd);
    const std::uint64_t lcd_hash = visible_lcd_fnv1a64(*lcd);
    std::printf(
        "mode=wabbitemu-compact probe_id=%u payload_size=%zu probe_size=%zu "
        "boot_steps=%" PRIu64 " probe_steps=%" PRIu64 " create_intercepts=%zu "
        "key_pages=%zu marker_visits=%zu returned=%d final_pc=0x%04X "
        "final_sp=0x%04X appvar_matches=%d completed=%d display_code=%u rendered=1 "
        "lcd_fnv1a64=%016" PRIx64 " all_pages_nonblank=%d page_lcd_fnv1a64=",
        probe_id, payload_size, probe.size(), boot_steps, probe_steps,
        create_intercepts, key_pages, marker_visits,
        static_cast<int>(cpu.pc == kReturnSentinel), cpu.pc,
        cpu.sp, static_cast<int>(appvar_matches), static_cast<int>(completed), display_code,
        lcd_hash, static_cast<int>(all_pages_nonblank)
    );
    for (std::size_t index = 0; index < page_hashes.size(); ++index) {
        std::printf(
            "%s%016" PRIx64, index == 0 ? "" : ",", page_hashes[index]
        );
    }
    std::printf(" page_nonzero_bytes=");
    for (std::size_t index = 0; index < page_nonzero_bytes.size(); ++index) {
        std::printf(
            "%s%zu", index == 0 ? "" : ",", page_nonzero_bytes[index]
        );
    }
    std::printf(" compact_code=%s frame_hex=", compact.c_str());
    for (std::size_t index = 0; index < frame_size; ++index) {
        std::printf("%02X", frame[index]);
    }
    std::printf("\n");
    return completed ? 0 : 3;
}

} // namespace

int main(int argc, char **argv) {
    if (argc >= 2 && std::strcmp(argv[1], "--compact-probe") == 0) {
        return run_compact_probe(argc, argv);
    }
    std::fprintf(stderr, "expected --compact-probe\n");
    return 2;
}
