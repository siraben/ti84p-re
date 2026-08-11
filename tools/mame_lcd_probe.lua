-- LCD-controller and missing ASIC-wait probe for the MAME TI-84 Plus driver.

local cpu = assert(manager.machine.devices[":maincpu"], "missing :maincpu")
local lcd = assert(manager.machine.devices[":t6a04"], "missing :t6a04")
local program = assert(cpu.spaces["program"], "maincpu has no program space")
local io = assert(cpu.spaces["io"], "maincpu has no I/O space")

local function saved_item(suffix)
    for name, index in pairs(lcd.items) do
        if string.sub(name, -#suffix) == suffix then
            return emu.item(index)
        end
    end
    error("missing LCD save item " .. suffix)
end

local busy = saved_item("/m_busy_flag")
local ram = saved_item("/m_lcd_ram")
local display = saved_item("/m_display_on")
local contrast = saved_item("/m_contrast")
local xpos = saved_item("/m_xpos")
local ypos = saved_item("/m_ypos")
local zpos = saved_item("/m_zpos")
local direction = saved_item("/m_direction")
local active = saved_item("/m_active_counter")
local word = saved_item("/m_word_len")
local opa1 = saved_item("/m_opa1")
local opa2 = saved_item("/m_opa2")
local output = saved_item("/m_output_reg")

local function seed_reset_state()
    busy:write(0, 0)
    display:write(0, 0)
    contrast:write(0, 0)
    xpos:write(0, 0)
    ypos:write(0, 0)
    zpos:write(0, 0)
    direction:write(0, 1)
    active:write(0, 1)
    word:write(0, 1)
    opa1:write(0, 0)
    opa2:write(0, 0)
    output:write(0, 0)
    for index = 0, 959 do
        ram:write(index, 0)
    end
end

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

local function ram_bytes(first, last)
    local values = {}
    for index = first, last do
        values[#values + 1] = string.format("%02X", ram:read(index))
    end
    return table.concat(values)
end

local function reset_ram_nonzero()
    local count = 0
    for index = 0, 959 do
        if ram:read(index) ~= 0 then
            count = count + 1
        end
    end
    return count
end

-- Map RAM page 0 and park the CPU so TI-OS cannot touch controller ports.
io:write_u8(0x04, 0x00)
program:write_u8(0xc000, 0xf3)
program:write_u8(0xc001, 0x18)
program:write_u8(0xc002, 0xfe)
assert(program:read_u8(0xc000) == 0xf3, "C000 is not writable RAM")
cpu.state["PC"].value = 0xc000
io:write_u8(0x03, 0x00)

print(string.format(
    "MAME_LCD identity machine=%s version=%s",
    manager.machine.system.name,
    emu.app_version()
))

print(string.format(
    "MAME_LCD reset status10=%02X status12=%02X port2=%02X " ..
    "ram_nonzero=%d x=%02X y=%02X z=%02X output=%02X word=%02X " ..
    "display=%02X active=%02X direction=%d",
    io:read_u8(0x10), io:read_u8(0x12), io:read_u8(0x02),
    reset_ram_nonzero(), xpos:read(0), ypos:read(0), zpos:read(0),
    output:read(0), word:read(0), display:read(0), active:read(0),
    direction:read(0)
))

io:write_u8(0x10, 0x03)
local rapid = {}
for index = 1, 4 do
    rapid[index] = string.format("%02X", io:read_u8(index % 2 == 0 and 0x12 or 0x10))
end
local movement = {}
for command = 0x04, 0x07 do
    io:write_u8(0x10, command)
    movement[#movement + 1] = string.format("%02X", io:read_u8(0x10))
end
io:write_u8(0x10, 0x00)
local six_status = io:read_u8(0x10)
io:write_u8(0x10, 0x01)
local eight_status = io:read_u8(0x10)
io:write_u8(0x12, 0x02)
local mirror_off_status = io:read_u8(0x10)
io:write_u8(0x10, 0x03)
local mirror_on_status = io:read_u8(0x12)
io:write_u8(0x10, 0xef)
io:write_u8(0x10, 0x17)
io:write_u8(0x10, 0x0b)
io:write_u8(0x10, 0x7f)
io:write_u8(0x10, 0x1f)
assert(busy:read(0) == 0, "unexpected LCD busy state")
print(string.format(
    "MAME_LCD control rapid_status=%s movement_status=%s " ..
    "six_status=%02X eight_status=%02X mirror_off_status=%02X " ..
    "mirror_on_status=%02X contrast=%02X opa1=%02X opa2=%02X z=%02X",
    table.concat(rapid), table.concat(movement),
    six_status, eight_status, mirror_off_status, mirror_on_status,
    contrast:read(0), opa1:read(0), opa2:read(0), zpos:read(0)
))

seed_reset_state()
io:write_u8(0x10, 0x01)
io:write_u8(0x10, 0x07)
io:write_u8(0x10, 0x80)
io:write_u8(0x10, 0x2e)
for index, value in ipairs({ 0xa0, 0xa1, 0xa2, 0xa3 }) do
    io:write_u8(index % 2 == 0 and 0x13 or 0x11, value)
end
print(string.format(
    "MAME_LCD increment cells=%s final_x=%02X final_y=%02X",
    ram_bytes(14, 17), xpos:read(0), ypos:read(0)
))

io:write_u8(0x10, 0x80)
io:write_u8(0x10, 0x2f)
io:write_u8(0x11, 0xb5)
local column15_final_y = ypos:read(0)
io:write_u8(0x10, 0x80)
io:write_u8(0x10, 0x3f)
io:write_u8(0x13, 0xbf)
print(string.format(
    "MAME_LCD direct column15_cell=%02X column15_final_y=%02X " ..
    "column31_cell=%02X column31_final_y=%02X",
    ram:read(15), column15_final_y, ram:read(31), ypos:read(0)
))

seed_reset_state()
io:write_u8(0x10, 0x01)
io:write_u8(0x10, 0x07)
io:write_u8(0x10, 0x82)
io:write_u8(0x10, 0x20)
io:write_u8(0x11, 0x12)
io:write_u8(0x13, 0x34)
io:write_u8(0x11, 0x56)
io:write_u8(0x10, 0x82)
io:write_u8(0x10, 0x20)
local latch_reads = string.format(
    "%02X%02X%02X",
    io:read_u8(0x11), io:read_u8(0x13), io:read_u8(0x11)
)
print(string.format(
    "MAME_LCD latch reads=%s final_x=%02X final_y=%02X",
    latch_reads, xpos:read(0), ypos:read(0)
))

seed_reset_state()
io:write_u8(0x10, 0x00)
io:write_u8(0x10, 0x07)
io:write_u8(0x10, 0x83)
io:write_u8(0x10, 0x20)
io:write_u8(0x11, 0x3f)
io:write_u8(0x13, 0x15)
print(string.format(
    "MAME_LCD six_bit cells=%s final_y=%02X",
    ram_bytes(45, 46), ypos:read(0)
))

local delay_initial = read_block(0x29, 0x2f)
write_pattern(0x29, 0x2f)
print(string.format(
    "MAME_LCD mapping delay_initial=%s delay_patterned=%s ready=%02X",
    delay_initial, read_block(0x29, 0x2f), io:read_u8(0x02)
))

manager.machine:exit()
