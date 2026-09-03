-- Memory-mapper and fixed-page handoff probe for MAME's TI-84 Plus driver.

local cpu = assert(manager.machine.devices[":maincpu"], "missing :maincpu")
local program = assert(cpu.spaces["program"], "maincpu has no program space")
local io = assert(cpu.spaces["io"], "maincpu has no I/O space")
local probe_case = assert(
    os.getenv("TI84_MAME_MAPPER_CASE"),
    "TI84_MAME_MAPPER_CASE is required"
)

local function bytes(address, count)
    local values = {}
    for offset = 0, count - 1 do
        values[#values + 1] = string.format("%02X", program:read_u8(address + offset))
    end
    return table.concat(values)
end

local function port_bytes(ports)
    local values = {}
    for _, port in ipairs(ports) do
        values[#values + 1] = string.format("%02X", io:read_u8(port))
    end
    return table.concat(values)
end

local function write_bytes(address, values)
    for offset, value in ipairs(values) do
        program:write_u8(address + offset - 1, value)
    end
end

local function identity()
    print(string.format(
        "MAME_MAPPER identity case=%s machine=%s version=%s",
        probe_case,
        manager.machine.system.name,
        emu.app_version()
    ))
end

local function select_c_ram(page)
    io:write_u8(0x04, 0x00)
    io:write_u8(0x05, page)
end

local function install_read_program(address)
    write_bytes(0xc000, {
        0xf3,                         -- DI
        0x3a, address & 0xff, address >> 8, -- LD A,(address)
        0x32, 0x00, 0xc1,             -- LD (C100),A
        0x76,                         -- HALT
    })
    program:write_u8(0xc100, 0x00)
end

local function run_boot_case(address, mode, bank_a, bank_b)
    select_c_ram(0)
    install_read_program(address)
    io:write_u8(0x06, bank_a)
    io:write_u8(0x07, bank_b)
    if mode ~= 0 then
        -- In paired mode port 0x07 selects C, so keep the code on RAM page 0.
        io:write_u8(0x07, 0x80)
        io:write_u8(0x04, mode)
    end
    local fixed_before = bytes(0x0000, 2)
    cpu.state["SP"].value = 0xcfff
    cpu.state["PC"].value = 0xc000
    io:write_u8(0x03, 0x00)

    local frame_subscription
    frame_subscription = emu.add_machine_frame_notifier(function()
        print(string.format(
            "MAME_MAPPER boot case=%s mode=%02X bank_a=%02X bank_b=%02X " ..
            "address=%04X fixed_before=%s observed=%02X fixed_after=%s pc=%04X",
            probe_case,
            mode,
            io:read_u8(0x06),
            io:read_u8(0x07),
            address,
            fixed_before,
            program:read_u8(0xc100),
            bytes(0x0000, 2),
            cpu.state["PC"].value
        ))
        manager.machine:exit()
    end)
end

local function seed_ram()
    for page = 0, 6 do
        select_c_ram(page)
        program:write_u8(0xc000, 0xa0 + page)
        program:write_u8(0xfb64, 0xd0 + page)
    end
end

local function install_marker_program(page, marker)
    select_c_ram(page)
    write_bytes(0xc100, {
        0xf3,                         -- DI
        0x3e, marker,                 -- LD A,marker
        0x32, 0x00, 0xc2,             -- LD (C200),A
        0xc3, 0x00, 0xc3,             -- JP C300
    })
end

local function run_mapping_case()
    seed_ram()

    io:write_u8(0x04, 0x00)
    io:write_u8(0x06, 0x41)
    local flash_41 = bytes(0x4000, 2)
    local read_41 = io:read_u8(0x06)
    io:write_u8(0x06, 0x7f)
    local flash_7f = bytes(0x4000, 2)
    local read_7f = io:read_u8(0x06)
    io:write_u8(0x06, 0x80)
    local ram_80 = program:read_u8(0x4000)
    local read_80 = io:read_u8(0x06)
    io:write_u8(0x06, 0x86)
    local ram_86 = program:read_u8(0x4000)
    local read_86 = io:read_u8(0x06)
    io:write_u8(0x07, 0x85)
    local b_85 = program:read_u8(0x8000)
    io:write_u8(0x05, 0xfe)
    local c_fe = program:read_u8(0xc000)
    print(string.format(
        "MAME_MAPPER selectors flash41=%s read41=%02X flash7f=%s read7f=%02X " ..
        "ram80=%02X read80=%02X ram86=%02X read86=%02X " ..
        "b85=%02X read85=%02X cfe=%02X readfe=%02X",
        flash_41, read_41, flash_7f, read_7f,
        ram_80, read_80, ram_86, read_86,
        b_85, io:read_u8(0x07), c_fe, io:read_u8(0x05)
    ))

    io:write_u8(0x06, 0x02)
    io:write_u8(0x07, 0x83)
    io:write_u8(0x04, 0x01)
    print(string.format(
        "MAME_MAPPER paired a=%s b=%s c=%02X port5=%02X port6=%02X port7=%02X",
        bytes(0x4000, 2),
        bytes(0x8000, 2),
        program:read_u8(0xc000),
        io:read_u8(0x05),
        io:read_u8(0x06),
        io:read_u8(0x07)
    ))

    local absent_ports = { 0x0e, 0x0f, 0x27, 0x28 }
    local absent_initial = port_bytes(absent_ports)
    for _, port in ipairs(absent_ports) do
        io:write_u8(port, 0x80 | port)
    end
    print(string.format(
        "MAME_MAPPER absent initial=%s patterned=%s",
        absent_initial,
        port_bytes(absent_ports)
    ))

    io:write_u8(0x04, 0x00)
    io:write_u8(0x07, 0x82)
    io:write_u8(0x05, 0x03)
    io:write_u8(0x28, 0x01)
    io:write_u8(0x27, 0xff)
    local b_before = program:read_u8(0x8000)
    local c_before = program:read_u8(0xfb64)
    program:write_u8(0x8000, 0xe2)
    program:write_u8(0xfb64, 0xe3)
    io:write_u8(0x07, 0x81)
    local forced_b_after = program:read_u8(0x8000)
    io:write_u8(0x05, 0x00)
    local forced_c_after = program:read_u8(0xfb64)
    io:write_u8(0x07, 0x82)
    local underlying_b_after = program:read_u8(0x8000)
    io:write_u8(0x05, 0x03)
    local underlying_c_after = program:read_u8(0xfb64)
    print(string.format(
        "MAME_MAPPER overlay b_before=%02X c_before=%02X " ..
        "forced_b_after=%02X underlying_b_after=%02X " ..
        "forced_c_after=%02X underlying_c_after=%02X",
        b_before, c_before,
        forced_b_after, underlying_b_after,
        forced_c_after, underlying_c_after
    ))

    install_marker_program(1, 0x11)
    install_marker_program(2, 0x22)
    select_c_ram(0)
    program:write_u8(0xc200, 0x00)
    write_bytes(0xc300, { 0xf3, 0x18, 0xfe }) -- DI; JR $
    io:write_u8(0x07, 0x82)
    io:write_u8(0x28, 0x05)
    cpu.state["SP"].value = 0xcfff
    cpu.state["PC"].value = 0x8100
    io:write_u8(0x03, 0x00)

    local frame_subscription
    frame_subscription = emu.add_machine_frame_notifier(function()
        print(string.format(
            "MAME_MAPPER fetch marker=%02X pc=%04X",
            program:read_u8(0xc200),
            cpu.state["PC"].value
        ))
        manager.machine:exit()
    end)
end

identity()

if probe_case == "direct" then
    local fixed_before = bytes(0x0000, 2)
    local a = bytes(0x4000, 2)
    print(string.format(
        "MAME_MAPPER reset pc=%04X ports=%s fixed_before=%s a=%s b=%s c=%s fixed_after=%s",
        cpu.state["PC"].value,
        port_bytes({ 0x04, 0x05, 0x06, 0x07 }),
        fixed_before,
        a,
        bytes(0x8000, 2),
        bytes(0xc000, 2),
        bytes(0x0000, 2)
    ))
    manager.machine:exit()
elseif probe_case == "independent_b" then
    run_boot_case(0x8000, 0x00, 0x01, 0x02)
elseif probe_case == "window_a" then
    run_boot_case(0x4000, 0x00, 0x01, 0x02)
elseif probe_case == "paired_b" then
    run_boot_case(0x8001, 0x01, 0x02, 0x80)
elseif probe_case == "mapping" then
    run_mapping_case()
else
    error("unknown TI84_MAME_MAPPER_CASE " .. probe_case)
end
