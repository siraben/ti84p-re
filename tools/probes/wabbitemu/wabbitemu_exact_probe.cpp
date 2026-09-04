// Generic exact-byte runner layered over the pinned Wabbitemu adapter.

#define main wabbitemu_headless_embedded_main
#include "wabbitemu_headless.cpp"
#undef main

namespace {

constexpr unsigned short kFakeAppVar = 0xB800;

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

bool execution_frame_transition_valid(
    const unsigned char *staging, const unsigned char *resident
) {
    if (std::memcmp(staging, resident, 18) != 0) {
        return false;
    }
    const unsigned char before = staging[18];
    const unsigned char after = resident[18];
    if (before == 0) {
        return after == 1 || after == 3 || after == 4;
    }
    return (before == 2 && after == 2) || (before == 4 && after == 4);
}

int run_exact_probe(int argc, char **argv) {
    if (argc < 6 || argc > 8) {
        std::fprintf(
            stderr,
            "usage: %s --exact-probe INPUT.rom PROBE.bin ID PAYLOAD_SIZE "
            "[MAX_BOOT_STEPS [MAX_PROBE_STEPS]]\n",
            argv[0]
        );
        return 2;
    }
    const unsigned char probe_id = parse_page(argv[4]);
    const std::size_t payload_size = parse_count(argv[5], "PAYLOAD_SIZE");
    const std::uint64_t max_boot_steps =
        argc >= 7 ? parse_count(argv[6], "MAX_BOOT_STEPS") : UINT64_C(5000000);
    const std::uint64_t max_probe_steps =
        argc >= 8 ? parse_count(argv[7], "MAX_PROBE_STEPS") : UINT64_C(5000000);
    const std::vector<unsigned char> input = read_image(argv[2]);
    const std::vector<unsigned char> probe = read_probe(argv[3]);
    const unsigned char frame_marker[] = {
        'H', 'W', 'P', '1', 0x01, probe_id,
        static_cast<unsigned char>(payload_size & 0xFF),
        static_cast<unsigned char>((payload_size >> 8) & 0xFF),
    };
    const unsigned char display_bcall[] = {0xEF, 0x40, 0x45};
    const std::size_t frame_offset = find_unique(
        probe, frame_marker, sizeof(frame_marker), "exact-probe frame"
    );
    const std::size_t display_offset = find_unique(
        probe, display_bcall, sizeof(display_bcall), "display _ClrLCDFull bcall"
    );
    const std::size_t frame_size = 10 + payload_size;
    if (frame_offset + frame_size > probe.size()) {
        fail("exact-probe frame extends past machine image");
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
        fail("retail boot did not reach the protected OS baseline");
    }

    // Normalize the documented direct-Asm mapping and an idle interrupt/timer
    // baseline before injection. Peripheral state, including the LCD, remains
    // the state produced by the retail boot.
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
    if (std::memcmp(
            memory.ram + program_physical, probe.data(), probe.size()
        ) != 0) {
        fail("exact-probe injection did not read back");
    }

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
    execution_violation_resets = 0;
    cpu.exe_violation_callback = record_execution_violation;

    const unsigned short display_stop = static_cast<unsigned short>(
        kProbeOrigin + display_offset
    );
    const std::size_t fake_physical =
        kProbeRamPage * PAGE_SIZE + mc_base(kFakeAppVar);
    std::size_t create_intercepts = 0;
    std::uint64_t probe_steps = 0;
    for (; probe_steps < max_probe_steps; ++probe_steps) {
        if (cpu.pc == display_stop) {
            break;
        }
        if (is_create_call(probe, cpu.pc)) {
            const unsigned char *frame = memory.ram + program_physical + frame_offset;
            std::memcpy(memory.ram + fake_physical, frame, frame_size);
            cpu.de = static_cast<unsigned short>(kFakeAppVar + frame_size);
            cpu.pc = static_cast<unsigned short>(cpu.pc + 3);
            ++create_intercepts;
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
    const bool frame_valid = probe_id == 4
        ? execution_frame_transition_valid(
            frame, memory.ram + fake_physical
        )
        : appvar_matches;
    const bool completed = cpu.pc == display_stop
        && execution_violation_resets == 0
        && create_intercepts != 0
        && frame_valid;
    std::printf(
        "mode=exact-probe probe_id=%u payload_size=%zu probe_size=%zu "
        "boot_steps=%" PRIu64 " probe_steps=%" PRIu64 " "
        "create_intercepts=%zu display_stop=0x%04X final_pc=0x%04X "
        "violation_resets=%u appvar_matches=%d completed=%d "
        "display_code=%u frame_hex=",
        probe_id, payload_size, probe.size(), boot_steps, probe_steps,
        create_intercepts, display_stop, cpu.pc, execution_violation_resets,
        static_cast<int>(appvar_matches), static_cast<int>(completed), cpu.de
    );
    for (std::size_t index = 0; index < frame_size; ++index) {
        std::printf("%02X", frame[index]);
    }
    std::printf(" appvar_frame_hex=");
    for (std::size_t index = 0; index < frame_size; ++index) {
        std::printf("%02X", memory.ram[fake_physical + index]);
    }
    std::printf("\n");
    return completed ? 0 : 3;
}

} // namespace

int main(int argc, char **argv) {
    if (argc >= 2 && std::strcmp(argv[1], "--exact-probe") == 0) {
        return run_exact_probe(argc, argv);
    }
    std::fprintf(stderr, "expected --exact-probe\n");
    return 2;
}
