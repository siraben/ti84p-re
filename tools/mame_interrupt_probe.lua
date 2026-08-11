-- Legacy interrupt-mask, ON-edge, timer, and reset probe for MAME 0.287.

if _G.TI84_MAME_INTERRUPT_PROBE_STARTED then
    return
end
_G.TI84_MAME_INTERRUPT_PROBE_STARTED = true

local cpu = assert(manager.machine.devices[":maincpu"], "missing :maincpu")
local program = assert(cpu.spaces["program"], "maincpu has no program space")
local io = assert(cpu.spaces["io"], "maincpu has no I/O space")
local on_port = assert(manager.machine.ioport.ports[":ON"], "missing :ON")
local on_field
for _, field in pairs(on_port.fields) do
    if field.mask == 0x01 then
        on_field = field
    end
end
assert(on_field, "missing ON/OFF field")

local function set_on(pressed)
    on_field:set_value(pressed and 1 or 0)
end

local function park_cpu()
    io:write_u8(0x04, 0x00)
    program:write_u8(0xc000, 0xf3) -- DI
    program:write_u8(0xc001, 0x18) -- JR C001
    program:write_u8(0xc002, 0xfe)
    assert(program:read_u8(0xc000) == 0xf3, "C000 is not writable RAM")
    cpu.state["PC"].value = 0xc000
end

local function clear_programmable_timers()
    for setup = 0x30, 0x36, 3 do
        io:write_u8(setup, 0x00)
        io:write_u8(setup + 1, 0x00)
    end
end

local function statuses_for_masks(values)
    local status03 = {}
    local status04 = {}
    for index, value in ipairs(values) do
        io:write_u8(0x02, 0x00)
        io:write_u8(0x03, value)
        status03[index] = string.format("%02X", io:read_u8(0x03))
        status04[index] = string.format("%02X", io:read_u8(0x04))
    end
    return table.concat(status03), table.concat(status04)
end

set_on(false)
park_cpu()
clear_programmable_timers()
io:write_u8(0x03, 0x00)
io:write_u8(0x02, 0x00)

print(string.format(
    "MAME_INTERRUPT identity machine=%s version=%s",
    manager.machine.system.name,
    emu.app_version()
))
print(string.format(
    "MAME_INTERRUPT reset status02=%02X status03=%02X status04=%02X",
    io:read_u8(0x02), io:read_u8(0x03), io:read_u8(0x04)
))

local mask_values = { 0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0xff }
local mask03, mask04 = statuses_for_masks(mask_values)
print(string.format(
    "MAME_INTERRUPT masks values=000102040810FF status03=%s status04=%s",
    mask03, mask04
))

io:write_u8(0x02, 0x07)
local seed07 = io:read_u8(0x04)
io:write_u8(0x03, 0x01)
local keep_on = io:read_u8(0x04)
io:write_u8(0x02, 0x07)
io:write_u8(0x03, 0x06)
local keep_timers = io:read_u8(0x04)
io:write_u8(0x02, 0x07)
io:write_u8(0x03, 0xff)
local keep_all = io:read_u8(0x04)
io:write_u8(0x02, 0x07)
io:write_u8(0x03, 0x00)
local clear = io:read_u8(0x04)
print(string.format(
    "MAME_INTERRUPT injected seed07=%02X keep_on=%02X keep_timers=%02X " ..
    "keep_all=%02X clear=%02X status02=%02X",
    seed07, keep_on, keep_timers, keep_all, clear, io:read_u8(0x02)
))

io:write_u8(0x02, 0x00)
io:write_u8(0x03, 0x00)
set_on(false)

local phase = "press_masked"
local settle_frames = 0
local on_values = {}
local timer_values = {}
local reset_subscription
local frame_subscription

local function after_on_sample(next_phase)
    phase = next_phase
    -- Input fields update at the video boundary after this notifier.  Leave
    -- one further notifier idle so the 256 Hz callback samples the new level.
    settle_frames = 1
end

frame_subscription = emu.add_machine_frame_notifier(function()
    if settle_frames > 0 then
        settle_frames = settle_frames - 1
        return
    end
    if phase == "press_masked" then
        set_on(true)
        after_on_sample("read_masked")
        return
    end
    if phase == "read_masked" then
        on_values.masked_press = io:read_u8(0x04)
        io:write_u8(0x03, 0x01)
        phase = "read_held"
        return
    end
    if phase == "read_held" then
        on_values.held_enable = io:read_u8(0x04)
        set_on(false)
        after_on_sample("read_release")
        return
    end
    if phase == "read_release" then
        on_values.release = io:read_u8(0x04)
        set_on(true)
        after_on_sample("read_enabled_press")
        return
    end
    if phase == "read_enabled_press" then
        on_values.enabled_press = io:read_u8(0x04)
        set_on(false)
        after_on_sample("read_enabled_release")
        return
    end
    if phase == "read_enabled_release" then
        on_values.enabled_release = io:read_u8(0x04)
        io:write_u8(0x03, 0xfe)
        on_values.after_ack = io:read_u8(0x04)
        print(string.format(
            "MAME_INTERRUPT on masked_press=%02X held_enable=%02X " ..
            "release=%02X enabled_press=%02X enabled_release=%02X after_ack=%02X",
            on_values.masked_press, on_values.held_enable, on_values.release,
            on_values.enabled_press, on_values.enabled_release,
            on_values.after_ack
        ))
        io:write_u8(0x02, 0x00)
        io:write_u8(0x03, 0x02)
        phase = "timer1"
        return
    end
    if phase == "timer1" then
        timer_values.timer1 = io:read_u8(0x04)
        io:write_u8(0x02, 0x00)
        io:write_u8(0x03, 0x04)
        phase = "timer2"
        return
    end
    if phase == "timer2" then
        timer_values.timer2 = io:read_u8(0x04)
        io:write_u8(0x02, 0x00)
        io:write_u8(0x03, 0x06)
        phase = "timers_both"
        return
    end
    if phase == "timers_both" then
        timer_values.both = io:read_u8(0x04)
        io:write_u8(0x04, 0x00)
        io:write_u8(0x02, 0x00)
        io:write_u8(0x03, 0x02)
        phase = "timer_config00"
        return
    end
    if phase == "timer_config00" then
        timer_values.config00 = io:read_u8(0x04)
        io:write_u8(0x04, 0x06)
        io:write_u8(0x02, 0x00)
        io:write_u8(0x03, 0x02)
        phase = "timer_config06"
        return
    end
    if phase == "timer_config06" then
        timer_values.config06 = io:read_u8(0x04)
        print(string.format(
            "MAME_INTERRUPT timers timer1=%02X timer2=%02X both=%02X " ..
            "config00=%02X config06=%02X",
            timer_values.timer1, timer_values.timer2, timer_values.both,
            timer_values.config00, timer_values.config06
        ))
        set_on(false)
        io:write_u8(0x02, 0x07)
        io:write_u8(0x03, 0x07)
        local before = io:read_u8(0x04)
        reset_subscription = emu.add_machine_reset_notifier(function()
            local immediate03 = io:read_u8(0x03)
            local immediate04 = io:read_u8(0x04)
            local pc = cpu.state["PC"].value
            park_cpu()
            clear_programmable_timers()
            io:write_u8(0x02, 0x00)
            phase = "post_reset_timers"
            timer_values.soft_before = before
            timer_values.soft_immediate03 = immediate03
            timer_values.soft_immediate04 = immediate04
            timer_values.soft_pc = pc
        end)
        phase = "reset_pending"
        manager.machine:soft_reset()
        return
    end
    if phase == "post_reset_timers" then
        timer_values.soft_after_timers = io:read_u8(0x04)
        set_on(true)
        after_on_sample("post_reset_on")
        return
    end
    if phase == "post_reset_on" then
        print(string.format(
            "MAME_INTERRUPT soft_reset before=%02X immediate03=%02X " ..
            "immediate04=%02X after_timers=%02X after_on=%02X pc=%04X",
            timer_values.soft_before, timer_values.soft_immediate03,
            timer_values.soft_immediate04, timer_values.soft_after_timers,
            io:read_u8(0x04), timer_values.soft_pc
        ))
        set_on(false)
        manager.machine:exit()
    end
end)
