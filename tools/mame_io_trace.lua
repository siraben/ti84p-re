-- Trace selected Z80 I/O ports in MAME and optionally inject an ON press.

local cpu = manager.machine.devices[":maincpu"]
assert(cpu, "MAME machine has no :maincpu device")
local io = cpu.spaces["io"]
assert(io, "MAME :maincpu has no I/O address space")

local function env_number(name)
    local value = os.getenv(name)
    if not value or value == "" then
        return nil
    end
    return assert(tonumber(value), name .. " must be an integer")
end

local function selected_ports(spec)
    local result = {}
    for item in string.gmatch(spec, "[^,]+") do
        local first, last = string.match(item, "^%s*(%x+)%s*%-%s*(%x+)%s*$")
        if not first then
            first = assert(string.match(item, "^%s*(%x+)%s*$"), "invalid port: " .. item)
            last = first
        end
        first = tonumber(first, 16)
        last = tonumber(last, 16)
        assert(first <= last and last <= 0xff, "invalid port range: " .. item)
        for port = first, last do
            result[port] = true
        end
    end
    return result
end

local frame = 0
local previous = nil
local repeats = 0

local function flush_repeats()
    if not previous or repeats == 0 then
        return
    end
    print(string.format(
        "MAME_REPEAT pc_after=%04X %s (0x%02X) count=%d",
        previous.pc,
        previous.direction,
        previous.port,
        repeats
    ))
end

local function record(direction, port, value)
    local event = {
        direction = direction,
        port = port,
        value = value,
        pc = cpu.state["PC"].value,
        frame = frame,
    }
    if previous
        and previous.direction == event.direction
        and previous.port == event.port
        and previous.value == event.value
        and previous.pc == event.pc then
        repeats = repeats + 1
        return
    end
    flush_repeats()
    previous = event
    repeats = 0
    local arrow = direction == "IN" and "->" or "<-"
    print(string.format(
        "MAME_IO frame=%d pc_after=%04X %s (0x%02X) %s 0x%02X",
        frame,
        event.pc,
        direction,
        port,
        arrow,
        value
    ))
end

local ports = selected_ports(os.getenv("MAME_TRACE_PORTS") or "03,04,55,56")
local taps = {}
for port, _ in pairs(ports) do
    taps[#taps + 1] = io:install_read_tap(
        port,
        port,
        string.format("ti84_read_%02x", port),
        function(offset, data, mask)
            record("IN", offset, data)
            return data
        end
    )
    taps[#taps + 1] = io:install_write_tap(
        port,
        port,
        string.format("ti84_write_%02x", port),
        function(offset, data, mask)
            record("OUT", offset, data)
            return data
        end
    )
end

local press_frame = env_number("MAME_ON_PRESS_FRAME")
local release_frame = env_number("MAME_ON_RELEASE_FRAME")
local on_field = nil
if press_frame or release_frame then
    local on_port = assert(manager.machine.ioport.ports[":ON"], "machine has no :ON port")
    on_field = assert(on_port.fields["ON/OFF"], "machine has no ON/OFF field")
end

local frame_subscription = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    if press_frame and frame == press_frame then
        flush_repeats()
        previous = nil
        repeats = 0
        print(string.format("MAME_KEY frame=%d ON press", frame))
        on_field:set_value(1)
    elseif release_frame and frame == release_frame then
        flush_repeats()
        previous = nil
        repeats = 0
        print(string.format("MAME_KEY frame=%d ON release", frame))
        on_field:set_value(0)
    end
end)

local stop_subscription = emu.add_machine_stop_notifier(function()
    flush_repeats()
end)

print("MAME_TRACE machine=" .. manager.machine.system.name)
