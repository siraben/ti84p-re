-- Raw-link and advertised-assist probe for the MAME TI-84 Plus driver.

local cpu = assert(manager.machine.devices[":maincpu"], "missing :maincpu")
local io = assert(cpu.spaces["io"], "maincpu has no I/O space")
local link = assert(manager.machine.devices[":linkport"], "missing :linkport")

local function saved_item(suffix)
    for name, index in pairs(link.items) do
        if string.sub(name, -#suffix) == suffix then
            return emu.item(index)
        end
    end
    error("missing link-port save item " .. suffix)
end

local tip_in = saved_item("/m_tip_in")
local tip_out = saved_item("/m_tip_out")
local ring_in = saved_item("/m_ring_in")
local ring_out = saved_item("/m_ring_out")

local function read_assist_block()
    local bytes = {}
    for port = 0x08, 0x0d do
        bytes[#bytes + 1] = string.format("%02X", io:read_u8(port))
    end
    return table.concat(bytes)
end

print(string.format(
    "MAME_LINK identity machine=%s version=%s",
    manager.machine.system.name,
    emu.app_version()
))

-- Normal TI-84 Plus raw writes affect the PCR readback but release the port.
for _, value in ipairs({ 0x00, 0x01, 0x02, 0x03, 0x14, 0x28, 0x3c }) do
    io:write_u8(0x00, value)
    print(string.format(
        "MAME_LINK raw write=%02X read=%02X tip_out=%d ring_out=%d",
        value,
        io:read_u8(0x00),
        tip_out:read(0),
        ring_out:read(0)
    ))
end

-- Inject peer levels in the link-port device's saved input fields.
io:write_u8(0x00, 0x00)
for peer = 0, 3 do
    tip_in:write(0, (peer & 1) == 0 and 1 or 0)
    ring_in:write(0, (peer & 2) == 0 and 1 or 0)
    print(string.format(
        "MAME_LINK peer pull_low=%02X read=%02X",
        peer,
        io:read_u8(0x00)
    ))
end
tip_in:write(0, 1)
ring_in:write(0, 1)

local assist_initial = read_assist_block()
for port = 0x08, 0x0d do
    io:write_u8(port, 0xa0 | port)
end
print(string.format(
    "MAME_LINK assist status=%02X initial=%s patterned=%s",
    io:read_u8(0x02),
    assist_initial,
    read_assist_block()
))

cpu.state["PC"].value = 0
manager.machine:exit()
