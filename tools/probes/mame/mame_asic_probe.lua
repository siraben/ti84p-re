-- ASIC status, speed, protection-port, GPIO, USB, and reset probe for MAME.

if _G.TI84_MAME_ASIC_PROBE_STARTED then
    return
end
_G.TI84_MAME_ASIC_PROBE_STARTED = true

local cpu = assert(manager.machine.devices[":maincpu"], "missing :maincpu")
local program = assert(cpu.spaces["program"], "maincpu has no program space")
local io = assert(cpu.spaces["io"], "maincpu has no I/O space")

local function read_ports(first, last)
    local values = {}
    for port = first, last do
        values[#values + 1] = string.format("%02X", io:read_u8(port))
    end
    return table.concat(values)
end

local function write_pattern(first, last)
    for port = first, last do
        io:write_u8(port, 0x80 | port)
    end
end

local function write_bytes(address, values)
    for offset, value in ipairs(values) do
        program:write_u8(address + offset - 1, value)
    end
end

local function read_word(address)
    return program:read_u8(address) | (program:read_u8(address + 1) << 8)
end

local function machine_time()
    local value = manager.machine.time
    return value.seconds, value.attoseconds
end

local function elapsed_attoseconds(start_seconds, start_attoseconds)
    local seconds, attoseconds = machine_time()
    return (seconds - start_seconds) * 1e18 + attoseconds - start_attoseconds
end

print(string.format(
    "MAME_ASIC identity machine=%s version=%s",
    manager.machine.system.name,
    emu.app_version()
))

print(string.format(
    "MAME_ASIC reset status02=%02X port14=%02X identity15=%02X " ..
    "speed20=%02X control21=%02X usb55=%02X usb56=%02X pc=%04X",
    io:read_u8(0x02),
    io:read_u8(0x14),
    io:read_u8(0x15),
    io:read_u8(0x20),
    io:read_u8(0x21),
    io:read_u8(0x55),
    io:read_u8(0x56),
    cpu.state["PC"].value
))

local gate_values = { 0x00, 0x01, 0x02, 0x3f, 0x40, 0xff }
local gate_status = {}
local gate_readback = {}
for index, value in ipairs(gate_values) do
    io:write_u8(0x14, value)
    gate_status[index] = string.format("%02X", io:read_u8(0x02))
    gate_readback[index] = string.format("%02X", io:read_u8(0x14))
end
print(string.format(
    "MAME_ASIC gate values=0001023F40FF status=%s readback=%s",
    table.concat(gate_status),
    table.concat(gate_readback)
))

local speed_values = { 0x00, 0x01, 0x02, 0x03, 0xff }
local speed_readback = {}
for index, value in ipairs(speed_values) do
    io:write_u8(0x20, value)
    speed_readback[index] = string.format("%02X", io:read_u8(0x20))
end
print(string.format(
    "MAME_ASIC speed values=00010203FF readback=%s",
    table.concat(speed_readback)
))

io:write_u8(0x14, 0x00)
io:write_u8(0x21, 0x33)
local locked_33 = io:read_u8(0x21)
io:write_u8(0x14, 0x01)
io:write_u8(0x21, 0x30)
local unlocked_30 = io:read_u8(0x21)
io:write_u8(0x21, 0x03)
local unlocked_03 = io:read_u8(0x21)
io:write_u8(0x21, 0x33)
local unlocked_33 = io:read_u8(0x21)
io:write_u8(0x21, 0xff)
local unlocked_ff = io:read_u8(0x21)
print(string.format(
    "MAME_ASIC control locked33=%02X unlocked30=%02X unlocked03=%02X " ..
    "unlocked33=%02X unlockedff=%02X",
    locked_33,
    unlocked_30,
    unlocked_03,
    unlocked_33,
    unlocked_ff
))

local protection_initial = read_ports(0x22, 0x2f)
write_pattern(0x22, 0x2f)
local protection_patterned = read_ports(0x22, 0x2f)
local gpio_initial = read_ports(0x39, 0x3a)
write_pattern(0x39, 0x3a)
local gpio_patterned = read_ports(0x39, 0x3a)
local usb_initial = read_ports(0x4a, 0x5b)
write_pattern(0x4a, 0x5b)
local usb_patterned = read_ports(0x4a, 0x5b)
print(string.format(
    "MAME_ASIC mapping protection_initial=%s protection_patterned=%s " ..
    "gpio_initial=%s gpio_patterned=%s usb_initial=%s usb_patterned=%s",
    protection_initial,
    protection_patterned,
    gpio_initial,
    gpio_patterned,
    usb_initial,
    usb_patterned
))

-- Run the same 50-T-state counter loop for five 20 ms video frames at each
-- modeled CPU clock. Port 0x21 and the absent boundary ports remain patterned
-- so successful RAM execution also covers MAME's missing fetch protection.
io:write_u8(0x04, 0x00)
io:write_u8(0x05, 0x00)
write_bytes(0xc000, {
    0xf3,                   -- DI
    0x2a, 0x00, 0xc1,       -- LD HL,(C100)
    0x23,                   -- INC HL
    0x22, 0x00, 0xc1,       -- LD (C100),HL
    0x18, 0xf7,             -- JR C001
})
program:write_u8(0xc100, 0x00)
program:write_u8(0xc101, 0x00)
io:write_u8(0x14, 0x00)
io:write_u8(0x21, 0x33)
for port, value in pairs({
    [0x22] = 0xcc,
    [0x23] = 0xdd,
    [0x24] = 0xaa,
    [0x25] = 0x10,
    [0x26] = 0x20,
}) do
    io:write_u8(port, value)
end
io:write_u8(0x03, 0x00)
io:write_u8(0x20, 0x00)
cpu.state["SP"].value = 0xcfff
cpu.state["PC"].value = 0xc000

local phase = "low"
local frames = 0
local low_count = 0
local low_elapsed = 0
local start_seconds, start_attoseconds = machine_time()
local reset_subscription
local frame_subscription
frame_subscription = emu.add_machine_frame_notifier(function()
    frames = frames + 1
    if frames < 5 then
        return
    end

    if phase == "low" then
        low_count = read_word(0xc100)
        low_elapsed = elapsed_attoseconds(start_seconds, start_attoseconds)
        program:write_u8(0xc100, 0x00)
        program:write_u8(0xc101, 0x00)
        io:write_u8(0x20, 0x01)
        cpu.state["PC"].value = 0xc001
        phase = "high"
        frames = 0
        start_seconds, start_attoseconds = machine_time()
        return
    end

    local high_count = read_word(0xc100)
    local high_elapsed = elapsed_attoseconds(start_seconds, start_attoseconds)
    print(string.format(
        "MAME_ASIC clocks frames=5 low_count=%04X low_attoseconds=%.0f " ..
        "high_count=%04X high_attoseconds=%.0f control21=%02X " ..
        "protection=%s",
        low_count,
        low_elapsed,
        high_count,
        high_elapsed,
        io:read_u8(0x21),
        read_ports(0x22, 0x26)
    ))

    io:write_u8(0x14, 0x01)
    io:write_u8(0x20, 0x03)
    io:write_u8(0x21, 0xab)
    reset_subscription = emu.add_machine_reset_notifier(function()
        print(string.format(
            "MAME_ASIC soft_reset status02=%02X port14=%02X identity15=%02X " ..
            "speed20=%02X control21=%02X usb55=%02X usb56=%02X pc=%04X",
            io:read_u8(0x02),
            io:read_u8(0x14),
            io:read_u8(0x15),
            io:read_u8(0x20),
            io:read_u8(0x21),
            io:read_u8(0x55),
            io:read_u8(0x56),
            cpu.state["PC"].value
        ))
        manager.machine:exit()
    end)
    manager.machine:soft_reset()
end)
