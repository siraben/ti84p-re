-- CPU-mapped port-0x14 Flash-gate probe for the MAME TI-84 Plus driver.

local cpu = assert(manager.machine.devices[":maincpu"], "missing :maincpu")
local memory = assert(cpu.spaces["program"], "maincpu has no program space")
local io = assert(cpu.spaces["io"], "maincpu has no I/O space")
local bank = assert(manager.machine.devices[":membank0"], "missing :membank0")
local flash = assert(bank.spaces["program"], "membank0 has no program space")

local LOGICAL_UNLOCK_AAA = 0x4aaa
local LOGICAL_UNLOCK_555 = 0x4555
local LOGICAL_TARGET = 0x4100
local PHYSICAL_TARGET = 0x020100

local function write_prefix()
    memory:write_u8(LOGICAL_UNLOCK_AAA, 0xaa)
    memory:write_u8(LOGICAL_UNLOCK_555, 0x55)
end

local function finish_program(value)
    memory:write_u8(LOGICAL_UNLOCK_AAA, 0xa0)
    memory:write_u8(LOGICAL_TARGET, value)
end

local function write_program(value)
    write_prefix()
    finish_program(value)
end

local function report(name, gate_status)
    print(string.format(
        "MAME_FLASH_GATE case=%s gate_status=%02X cpu=%02X physical=%02X",
        name,
        gate_status,
        memory:read_u8(LOGICAL_TARGET),
        flash:read_u8(PHYSICAL_TARGET)
    ))
end

print(string.format(
    "MAME_FLASH_GATE identity machine=%s version=%s",
    manager.machine.system.name,
    emu.app_version()
))

-- Independent mode maps Flash page 08 at the CPU's 0x4000 window.
io:write_u8(0x04, 0x00)
io:write_u8(0x06, 0x08)
print(string.format(
    "MAME_FLASH_GATE mapping page=%02X initial=%02X",
    io:read_u8(0x06),
    memory:read_u8(LOGICAL_TARGET)
))

-- A complete command is accepted while MAME reports the gate as locked.
io:write_u8(0x14, 0x00)
write_program(0x50)
report("locked", io:read_u8(0x02))

-- The unlock prefix begins locked and completes after port 0x14 is set.
io:write_u8(0x14, 0x00)
write_prefix()
io:write_u8(0x14, 0x01)
finish_program(0xd0)
report("unlock_between", io:read_u8(0x02))

-- The unlock prefix begins unlocked and completes after the gate is relocked.
write_prefix()
io:write_u8(0x14, 0x00)
finish_program(0x20)
report("relock_between", io:read_u8(0x02))

cpu.state["PC"].value = 0
manager.machine:exit()
