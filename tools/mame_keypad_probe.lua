-- Live-input keypad-matrix probe for the MAME TI-84 Plus driver.

local cpu = assert(manager.machine.devices[":maincpu"], "missing :maincpu")
local io = assert(cpu.spaces["io"], "maincpu has no I/O space")
local columns = {}

for column = 0, 7 do
    local tag = string.format(":BIT%d", column)
    columns[column] = assert(
        manager.machine.ioport.ports[tag],
        "machine has no " .. tag .. " input port"
    )
end

local function clear_keys()
    for column = 0, 7 do
        for _, field in pairs(columns[column].fields) do
            field:set_value(0)
        end
    end
end

local function press_key(group, column)
    local wanted_mask = 1 << group
    for _, field in pairs(columns[column].fields) do
        if field.mask == wanted_mask then
            field:set_value(1)
            return
        end
    end
    error(string.format("missing keypad position %d:%d", group, column))
end

local cases = {
    { "release_ff", 0xff, { { 0, 0 } }, "0:0" },
    { "bit7_only", 0x7f, { { 0, 0 } }, "0:0" },
    { "single", 0xfe, { { 0, 0 } }, "0:0" },
    { "unselected", 0xfe, { { 1, 0 } }, "1:0" },
    { "same_column", 0xfc, { { 0, 0 }, { 1, 0 } }, "0:0,1:0" },
    { "rectangle", 0xfe, { { 0, 0 }, { 1, 0 }, { 1, 1 } }, "0:0,1:0,1:1" },
    { "column_seven", 0xf7, { { 3, 7 } }, "3:7" },
    { "all_selected", 0x00, { { 0, 0 }, { 1, 0 }, { 2, 1 } }, "0:0,1:0,2:1" },
}

local function apply_case(case)
    clear_keys()
    for _, key in ipairs(case[3]) do
        press_key(key[1], key[2])
    end
end

local function report_case(case)
    io:write_u8(0x01, case[2])
    print(string.format(
        "MAME_KEYPAD case name=%s mask=%02X pressed=%s read=%02X",
        case[1],
        case[2],
        case[4],
        io:read_u8(0x01)
    ))
end

print(string.format(
    "MAME_KEYPAD identity machine=%s version=%s",
    manager.machine.system.name,
    emu.app_version()
))

-- MAME latches values forced through input fields at the next video-frame
-- update. Apply and sample on separate frame callbacks so the probe observes
-- the same live-input path as an interactive key press.
local case_index = 1
local ready_to_read = false
local frame_subscription
frame_subscription = emu.add_machine_frame_notifier(function()
    local case = cases[case_index]
    if not ready_to_read then
        apply_case(case)
        ready_to_read = true
        return
    end
    report_case(case)
    case_index = case_index + 1
    ready_to_read = false
    if case_index > #cases then
        clear_keys()
        io:write_u8(0x01, 0xff)
        cpu.state["PC"].value = 0
        manager.machine:exit()
    end
end)
