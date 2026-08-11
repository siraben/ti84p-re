-- CPU-I/O-space MD5-assist coverage probe for the MAME TI-84 Plus driver.

local cpu = assert(manager.machine.devices[":maincpu"], "missing :maincpu")
local io = assert(cpu.spaces["io"], "maincpu has no I/O space")

local FIRST_PORT = 0x18
local LAST_PORT = 0x1f

local function read_block()
    local bytes = {}
    for port = FIRST_PORT, LAST_PORT do
        bytes[#bytes + 1] = string.format("%02X", io:read_u8(port))
    end
    return table.concat(bytes)
end

local function write_word(port, value)
    for _ = 1, 4 do
        io:write_u8(port, value & 0xff)
        value = value >> 8
    end
end

local function read_result()
    local value = 0
    for port = 0x1f, 0x1c, -1 do
        value = (value << 8) | io:read_u8(port)
    end
    return value
end

print(string.format(
    "MAME_MD5 identity machine=%s version=%s",
    manager.machine.system.name,
    emu.app_version()
))

print("MAME_MD5 initial ports=" .. read_block())

for port = FIRST_PORT, LAST_PORT do
    io:write_u8(port, 0x80 | port)
end
print("MAME_MD5 patterned ports=" .. read_block())

-- First MD5 operation for the padded message "abc", matching 3F:6A0F.
io:write_u8(0x1f, 0x00)
write_word(0x18, 0x67452301)
write_word(0x19, 0xefcdab89)
write_word(0x1a, 0x98badcfe)
write_word(0x1b, 0x10325476)
write_word(0x1c, 0x80636261)
write_word(0x1d, 0xd76aa478)
io:write_u8(0x1e, 0x07)
print(string.format(
    "MAME_MD5 step expected=D6D117B4 observed=%08X ports=%s",
    read_result(),
    read_block()
))

cpu.state["PC"].value = 0
manager.machine:exit()
