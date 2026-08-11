-- Direct sector-geometry and chip-erase probe for the MAME TI-84 Plus driver.

local cpu = assert(manager.machine.devices[":maincpu"], "missing :maincpu")
local bank = assert(manager.machine.devices[":membank0"], "missing :membank0")
local flash = assert(bank.spaces["program"], "membank0 has no program space")

local MAX_FRAMES = 10000

local cases = {
    {name = "regular64", start = 0x0e0000, size = 0x010000, probe = 0x0f0000},
    {name = "top32", start = 0x0f0000, size = 0x008000, probe = 0x0f8000},
    {name = "top8a", start = 0x0f8000, size = 0x002000, probe = 0x0fa000},
    {name = "top8b", start = 0x0fa000, size = 0x002000, probe = 0x0fc000},
    {name = "top16", start = 0x0fc000, size = 0x004000, probe = 0x0fbffe},
}

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

local function write_chip_erase()
    write_command(0x80)
    write_unlock_prefix()
    flash:write_u8(0x000aaa, 0x10)
end

local function byte(address)
    return flash:read_u8(address)
end

print(string.format(
    "MAME_FLASH_ERASE identity machine=%s version=%s",
    manager.machine.system.name,
    emu.app_version()
))

local frame = 0
local case_index = 0
local phase = "sector"
local chip_start_seconds = nil

local function begin_sector(index)
    local case = cases[index]
    local finish = case.start + case.size
    local before = case.start - 1

    write_program(before, 0x00)
    write_program(case.start, 0x00)
    write_program(finish - 1, 0x00)
    write_program(case.probe, 0x00)
    write_sector_erase(case.start)

    local selected_1 = byte(case.start)
    local selected_2 = byte(case.start)
    local selected_end = byte(finish - 1)
    local probe = byte(case.probe)
    local outside_before = byte(before)

    print(string.format(
        "MAME_FLASH_ERASE immediate case=%s start=%05X size=%05X " ..
        "probe_addr=%05X before=%02X selected=%02X,%02X " ..
        "selected_end=%02X probe=%02X",
        case.name,
        case.start,
        case.size,
        case.probe,
        outside_before,
        selected_1,
        selected_2,
        selected_end,
        probe
    ))
end

local function complete_sector(index)
    local case = cases[index]
    local finish = case.start + case.size
    local before = case.start - 1
    print(string.format(
        "MAME_FLASH_ERASE complete case=%s frame=%d before=%02X " ..
        "selected=%02X selected_end=%02X probe=%02X",
        case.name,
        frame,
        byte(before),
        byte(case.start),
        byte(finish - 1),
        byte(case.probe)
    ))
end

local function begin_chip_erase()
    write_program(0x000000, 0x00)
    write_program(0x010000, 0x00)
    write_program(0x0fc000, 0x00)
    write_program(0x0fffff, 0x00)
    write_chip_erase()
    chip_start_seconds = manager.machine.time.seconds
    print(string.format(
        "MAME_FLASH_ERASE chip_immediate start_seconds=%d " ..
        "array0=%02X array1=%02X " ..
        "stale_start=%02X stale_end=%02X",
        chip_start_seconds,
        byte(0x000000),
        byte(0x010000),
        byte(0x0fc000),
        byte(0x0fffff)
    ))
end

local function complete_chip_erase()
    print(string.format(
        "MAME_FLASH_ERASE chip_complete complete_seconds=%d " ..
        "array0=%02X array1=%02X " ..
        "stale_start=%02X stale_end=%02X",
        manager.machine.time.seconds,
        byte(0x000000),
        byte(0x010000),
        byte(0x0fc000),
        byte(0x0fffff)
    ))
end

cpu.state["PC"].value = 0
case_index = 1
begin_sector(case_index)

local frame_subscription
frame_subscription = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    if phase ~= "sector" then
        return
    end
    if byte(cases[case_index].start) ~= 0xff then
        if frame >= MAX_FRAMES then
            print("MAME_FLASH_ERASE timeout phase=sector")
            manager.machine:exit()
        end
        return
    end
    complete_sector(case_index)
    case_index = case_index + 1
    if case_index <= #cases then
        begin_sector(case_index)
    else
        phase = "chip"
        begin_chip_erase()
    end
end)

emu.register_periodic(function()
    if phase == "chip" and byte(0x0fc000) == 0xff then
        complete_chip_erase()
        phase = "done"
        manager.machine:exit()
    end
end)
