-- Programmable-timer and absent-RTC probe for the MAME TI-84 Plus driver.

local cpu = assert(manager.machine.devices[":maincpu"], "missing :maincpu")
local program = assert(cpu.spaces["program"], "maincpu has no program space")
local io = assert(cpu.spaces["io"], "maincpu has no I/O space")

local function read_block(first, last)
    local values = {}
    for port = first, last do
        values[#values + 1] = string.format("%02X", io:read_u8(port))
    end
    return table.concat(values)
end

local function write_pattern(first, last)
    for port = first, last do
        io:write_u8(port, 0xa0 | (port & 0x1f))
    end
end

local function disable_all_timers()
    for setup = 0x30, 0x36, 3 do
        io:write_u8(setup, 0x00)
        io:write_u8(setup + 1, 0x00)
    end
end

local function machine_time()
    local value = manager.machine.time
    return value.seconds, value.attoseconds
end

local function elapsed_attoseconds(start_seconds, start_attoseconds)
    local seconds, attoseconds = machine_time()
    return (seconds - start_seconds) * 1e18 + attoseconds - start_attoseconds
end

-- Map page 0 RAM at C000, then keep the CPU in DI/JR $ so TI-OS cannot
-- rewrite timer registers between probe phases.
io:write_u8(0x04, 0x00)
program:write_u8(0xc000, 0xf3)
program:write_u8(0xc001, 0x18)
program:write_u8(0xc002, 0xfe)
assert(program:read_u8(0xc000) == 0xf3, "C000 is not writable RAM")
cpu.state["PC"].value = 0xc000
io:write_u8(0x03, 0x00)
disable_all_timers()

print(string.format(
    "MAME_TIMER identity machine=%s version=%s",
    manager.machine.system.name,
    emu.app_version()
))

local aux_initial = read_block(0x2d, 0x2f)
local rtc_initial = read_block(0x40, 0x48)
write_pattern(0x2d, 0x2f)
write_pattern(0x40, 0x48)
print(string.format(
    "MAME_TIMER mapping aux_initial=%s aux_patterned=%s " ..
    "rtc_initial=%s rtc_patterned=%s",
    aux_initial,
    read_block(0x2d, 0x2f),
    rtc_initial,
    read_block(0x40, 0x48)
))

io:write_u8(0x30, 0xff)
io:write_u8(0x31, 0xff)
io:write_u8(0x32, 0x00)
print(string.format(
    "MAME_TIMER masks setup=%02X mode=%02X count=%02X",
    io:read_u8(0x30),
    io:read_u8(0x31),
    io:read_u8(0x32)
))
disable_all_timers()

local phase = "family_start"
local phase_frame = 0
local family_start_seconds = 0
local family_start_attoseconds = 0
local bit1_set = nil

local frame_subscription
frame_subscription = emu.add_machine_frame_notifier(function()
    phase_frame = phase_frame + 1

    if phase == "family_start" then
        local sources = { 0x01, 0x41, 0x81 }
        for timer = 0, 2 do
            local setup = 0x30 + timer * 3
            io:write_u8(setup, sources[timer + 1])
            io:write_u8(setup + 1, 0x02)
            io:write_u8(setup + 2, 0xff)
        end
        family_start_seconds, family_start_attoseconds = machine_time()
        phase = "family_report"
        phase_frame = 0
        return
    end

    if phase == "family_report" then
        print(string.format(
            "MAME_TIMER family elapsed_attoseconds=%.0f " ..
            "sources=%02X%02X%02X counts=%02X%02X%02X",
            elapsed_attoseconds(family_start_seconds, family_start_attoseconds),
            io:read_u8(0x30), io:read_u8(0x33), io:read_u8(0x36),
            io:read_u8(0x32), io:read_u8(0x35), io:read_u8(0x38)
        ))
        disable_all_timers()
        io:write_u8(0x36, 0x07)
        io:write_u8(0x37, 0x00)
        io:write_u8(0x38, 0x00)
        phase = "zero"
        phase_frame = 0
        return
    end

    if phase == "zero" and phase_frame == 15 then
        print(string.format(
            "MAME_TIMER zero elapsed_frames=%d count=%02X setup=%02X " ..
            "mode=%02X port4=%02X",
            phase_frame,
            io:read_u8(0x38), io:read_u8(0x36),
            io:read_u8(0x37), io:read_u8(0x04)
        ))
        io:write_u8(0x36, 0x00)
        io:write_u8(0x37, 0x02)
        io:write_u8(0x36, 0x07)
        io:write_u8(0x38, 0x01)
        phase = "bit1_set"
        phase_frame = 0
        return
    end

    if phase == "bit1_set" then
        bit1_set = {
            io:read_u8(0x38), io:read_u8(0x36),
            io:read_u8(0x37), io:read_u8(0x04),
        }
        io:write_u8(0x37, 0x00)
        io:write_u8(0x36, 0x07)
        io:write_u8(0x38, 0x01)
        phase = "bit1_clear"
        phase_frame = 0
        return
    end

    if phase == "bit1_clear" then
        print(string.format(
            "MAME_TIMER polarity bit1_set_count=%02X bit1_set_setup=%02X " ..
            "bit1_set_mode=%02X bit1_set_port4=%02X " ..
            "bit1_clear_count=%02X bit1_clear_setup=%02X " ..
            "bit1_clear_mode=%02X bit1_clear_port4=%02X",
            bit1_set[1], bit1_set[2], bit1_set[3], bit1_set[4],
            io:read_u8(0x38), io:read_u8(0x36),
            io:read_u8(0x37), io:read_u8(0x04)
        ))
        io:write_u8(0x37, 0x01)
        io:write_u8(0x36, 0x07)
        io:write_u8(0x38, 0x01)
        phase = "loop"
        phase_frame = 0
        return
    end

    if phase == "loop" then
        print(string.format(
            "MAME_TIMER loop count=%02X setup=%02X mode=%02X port4=%02X",
            io:read_u8(0x38), io:read_u8(0x36),
            io:read_u8(0x37), io:read_u8(0x04)
        ))
        disable_all_timers()
        for timer = 0, 1 do
            local setup = 0x30 + timer * 3
            io:write_u8(setup, 0x07)
            io:write_u8(setup + 1, 0x00)
            io:write_u8(setup + 2, 0x01)
        end
        phase = "global"
        phase_frame = 0
        return
    end

    if phase == "global" then
        local before = io:read_u8(0x04)
        io:write_u8(0x31, 0x00)
        print(string.format(
            "MAME_TIMER global before=%02X after=%02X",
            before,
            io:read_u8(0x04)
        ))
        disable_all_timers()
        io:write_u8(0x30, 0x07)
        io:write_u8(0x31, 0x02)
        io:write_u8(0x32, 0x05)
        io:write_u8(0x30, 0x00)
        phase = "source_off"
        phase_frame = 0
        return
    end

    if phase == "source_off" and phase_frame == 2 then
        print(string.format(
            "MAME_TIMER source_off elapsed_frames=%d count=%02X " ..
            "setup=%02X mode=%02X",
            phase_frame,
            io:read_u8(0x32), io:read_u8(0x30), io:read_u8(0x31)
        ))
        manager.machine:exit()
    end
end)
