-- Direct Flash command/status probe for the MAME TI-84 Plus driver.

local cpu = assert(manager.machine.devices[":maincpu"], "missing :maincpu")
local bank = assert(manager.machine.devices[":membank0"], "missing :membank0")
local flash = assert(bank.spaces["program"], "membank0 has no program space")

local TARGET = 0x020100
local TOP_SECTOR = 0x0f8000
local TOP_ADJACENT = 0x0fa000
local BOOT_SECTOR = 0x0fc000
local OUTSIDE_BUSY = 0x0e0000

local function write_unlock_prefix()
    flash:write_u8(0x000aaa, 0xaa)
    flash:write_u8(0x000555, 0x55)
end

local function write_command(command)
    write_unlock_prefix()
    flash:write_u8(0x000aaa, command)
end

local function write_program(address, value)
    write_command(0xa0)
    flash:write_u8(address, value)
end

local function write_sector_erase(address)
    write_command(0x80)
    write_unlock_prefix()
    flash:write_u8(address, 0x30)
end

local function byte(address)
    return flash:read_u8(address)
end

print(string.format(
    "MAME_FLASH identity machine=%s version=%s",
    manager.machine.system.name,
    emu.app_version()
))

local initial_target = byte(TARGET)
write_command(0x90)
local autoselect = {byte(0), byte(1), byte(2), byte(4)}
flash:write_u8(0, 0xf0)

write_program(TARGET, 0x50)
local legal_stored = byte(TARGET)
write_program(TARGET, 0xd0)
local illegal_stored = byte(TARGET)

flash:write_u8(0x000aaa, 0xaa)
flash:write_u8(0x000aaa, 0xf0)
local partial_reset_byte = byte(TARGET)

flash:write_u8(0x000055, 0x98)
local cfi_byte = byte(TARGET)

write_command(0x20)
flash:write_u8(TARGET, 0xa0)
flash:write_u8(TARGET, 0x00)
local fast_program_stored = byte(TARGET)
flash:write_u8(TARGET, 0x90)
local fast_exit_id = byte(0)
flash:write_u8(TARGET, 0xf0)
local fast_exit_array = byte(TARGET)

local top_before = byte(TOP_SECTOR)
local adjacent_before = byte(TOP_ADJACENT)
local boot_before = byte(BOOT_SECTOR)
local outside_before = byte(OUTSIDE_BUSY)
write_sector_erase(TOP_SECTOR)
local busy_selected_1 = byte(TOP_SECTOR)
local busy_selected_2 = byte(TOP_SECTOR)
local busy_adjacent = byte(TOP_ADJACENT)
local busy_boot = byte(BOOT_SECTOR)
local busy_outside = byte(OUTSIDE_BUSY)

print(string.format(
    "MAME_FLASH immediate initial_target=%02X autoselect=%02X,%02X,%02X,%02X " ..
    "legal_stored=%02X illegal_stored=%02X partial_reset_byte=%02X " ..
    "cfi_byte=%02X fast_program_stored=%02X fast_exit_id=%02X " ..
    "fast_exit_array=%02X top_before=%02X adjacent_before=%02X " ..
    "boot_before=%02X outside_before=%02X busy_selected=%02X,%02X " ..
    "busy_adjacent=%02X busy_boot=%02X busy_outside=%02X",
    initial_target,
    autoselect[1], autoselect[2], autoselect[3], autoselect[4],
    legal_stored,
    illegal_stored,
    partial_reset_byte,
    cfi_byte,
    fast_program_stored,
    fast_exit_id,
    fast_exit_array,
    top_before,
    adjacent_before,
    boot_before,
    outside_before,
    busy_selected_1,
    busy_selected_2,
    busy_adjacent,
    busy_boot,
    busy_outside
))

cpu.state["PC"].value = 0

local frame = 0
local frame_subscription
frame_subscription = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    if frame == 20 then
        print(string.format(
            "MAME_FLASH complete frame=%d selected=%02X adjacent=%02X " ..
            "boot=%02X outside=%02X",
            frame,
            byte(TOP_SECTOR),
            byte(TOP_ADJACENT),
            byte(BOOT_SECTOR),
            byte(OUTSIDE_BUSY)
        ))
        manager.machine:exit()
    end
end)
